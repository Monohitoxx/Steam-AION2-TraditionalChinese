"""喺 live process（或 dump）搵「邊段 code RIP-relative 引用某個 VA」。

用途：已知 BLAKE3 IV 表 / L10N 字串 / 其他常數喺記憶體邊個位（例如 0x5968d40），
搵返邊個 function 用佢 —— 即係 key 推導、L10N loader 嘅位置。

用法::

    python findrefs.py --process AION2.exe --target 0x5968d40 --target 0x5968e40
    python findrefs.py --process AION2.exe --target 0x5968d40 --span 0x100 --context 64
    python findrefs.py --dump aion2-full.dmp --target 0x5968d40
"""

from __future__ import annotations

import argparse
import ctypes
import os
import re
import struct
import sys
from ctypes import wintypes
from typing import Dict, List, Sequence, Tuple

from minidump import MiniDump
from unpack import (MEMORY_BASIC_INFORMATION64, PROCESS_QUERY_INFORMATION, PROCESS_VM_READ,
                    MEM_COMMIT, PAGE_GUARD, find_pid)
from xref import plausible_prefix

EXEC_PROTECT = (0x10, 0x20, 0x40, 0x80)  # EXECUTE, EXECUTE_READ, EXECUTE_READWRITE, EXECUTE_WRITECOPY
READ_PROTECT = (0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80)
# disp32 嘅最高 byte：同 module 內嘅引用通常係 00/01/02/03，負向就係 FF/7F
CAND_HIGH = re.compile(rb'[\x00-\x03\x7f\xff]')


class Region:
    __slots__ = ('base', 'size', 'protect')

    def __init__(self, base: int, size: int, protect: int = 0):
        self.base, self.size, self.protect = base, size, protect


def live_regions(pid: int, exec_only: bool) -> List[Region]:
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        raise SystemExit(f'OpenProcess 失敗（錯誤 {ctypes.get_last_error()}）—— 試下用管理員身分執行')
    out: List[Region] = []
    mbi = MEMORY_BASIC_INFORMATION64()
    address = 0
    while address < 0x7FFFFFFFFFFF and kernel32.VirtualQueryEx(
            handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)):
        allowed = EXEC_PROTECT if exec_only else READ_PROTECT
        if (mbi.State == MEM_COMMIT and mbi.Protect in allowed and not (mbi.Protect & PAGE_GUARD)):
            out.append(Region(mbi.BaseAddress, mbi.RegionSize, mbi.Protect))
        address = mbi.BaseAddress + mbi.RegionSize
        if mbi.RegionSize == 0:
            break
    kernel32.CloseHandle(handle)
    return out


def read_bytes(pid: int, base: int, size: int):
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        return None
    buf = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t()
    ok = kernel32.ReadProcessMemory(handle, ctypes.c_void_p(base), buf, size, ctypes.byref(read))
    kernel32.CloseHandle(handle)
    return buf.raw[:read.value] if ok and read.value else None


# --- RIP-relative 指令前綴（ModRM mod=00, rm=101 -> disp32）---------------------------
_MODRM = b'[\x05\x0d\x15\x1d\x25\x2d\x35\x3d]'
_OP = b'[\x8b\x8d\x89\x3b\x39\x03\x2b\x33\x0b\x23\x85\x8a\x88\xc7\xc6\xff]'
_TWO = b'[\x10\x11\x28\x29\x6f\x7f\x6e\x7e\xd6\xef\xb6\xb7\xbe\xbf]'
_REX = b'[\x40-\x4f]'
# 每個 pattern 用 lookbehind 鎖住「disp32 前面一定係合法指令前綴」，
# 再用 (....)  捕捉 4 bytes 嘅 disp32。
_PREFIX_PATTERNS = [
    _REX + _OP + _MODRM,          # REX + op + modrm
    b'[\x66\xf2\xf3]\x0f' + _TWO + _MODRM,  # 66/F2/F3 + 0F xx + modrm
    _REX + b'\x0f' + _TWO + _MODRM,        # REX + 0F xx + modrm
    b'\x0f' + _TWO + _MODRM,               # 0F xx + modrm（例如 movdqa/movups xmm, [rip+…]）
    _OP + _MODRM,                 # 無 REX
    b'\xc5.' + _OP + _MODRM,      # VEX2
    b'\xc4..' + _OP + _MODRM,     # VEX3
]
CAND_RE = [re.compile(b'(?<=' + p + b')(....)', re.DOTALL) for p in _PREFIX_PATTERNS]

# --- x64 絕對定址形式（non-PIE／protector 虛擬化 code 常用）-------------------------
#   ModRM=04 + SIB=25 + disp32  ->  [disp32]（絕對位址）
_ABS = b'\x04\x25'
_ABS_PATTERNS = [
    _REX + _OP + _ABS,
    _OP + _ABS,
    b'[\x66\xf2\xf3]\x0f' + _TWO + _ABS,
    _REX + b'\x0f' + _TWO + _ABS,
    b'\x0f' + _TWO + _ABS,
]
ABS_RE = [re.compile(b'(?<=' + p + b')(....)', re.DOTALL) for p in _ABS_PATTERNS]
IMM32_RE = re.compile(b'(?<=[\xb8-\xbf])(....)', re.DOTALL)      # mov r32, imm32
IMM64_RE = re.compile(b'(?<=\x48[\xb8-\xbf])(........)', re.DOTALL)  # mov r64, imm64


def scan_block(data: bytes, chunk_va: int, targets: List[Tuple[int, str]], span: int):
    """回傳 [(instruction_va, target_name)]。

    同時處理三種引用方式（遊戲用邊種就要靠實測）：
      1. RIP-relative：`disp32` 令 `chunk_va + j + 4 + disp == 目標`
      2. 絕對記憶體運算元：`REX? op 04 25 disp32` -> `[disp32]`（位址就係 disp32 本身）
      3. 立即數：`mov r32, imm32` / `mov r64, imm64`（imm 就係位址）
    用 regex lookbehind 鎖住合法指令前綴，候選數係「真正指令」級別。
    """
    hits = []
    n = len(data)

    def record(va: int, instr_va: int):
        for tva, tname in targets:
            if tva - span <= va <= tva + span:
                hits.append((instr_va, tname))
                return

    for pattern in CAND_RE:
        for match in pattern.finditer(data):
            j = match.start()
            if j + 4 > n:
                continue
            disp = struct.unpack_from('<i', data, j)[0]
            start = plausible_prefix(data, j)
            if start is not None:
                record(chunk_va + j + 4 + disp, chunk_va + start)
    for pattern in ABS_RE:
        for match in pattern.finditer(data):
            j = match.start()
            va = struct.unpack_from('<I', data, j)[0]
            record(va, chunk_va + j - 3)
    for pattern, size, signed in ((IMM32_RE, 4, False), (IMM64_RE, 8, False)):
        for match in pattern.finditer(data):
            j = match.start()
            va = int.from_bytes(data[j:j + size], 'little')
            if 0 < va < (1 << 40):
                record(va, chunk_va + max(0, j - 1))
    return hits


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='搵邊段 code RIP-relative 引用指定 VA')
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--process')
    src.add_argument('--pid', type=int)
    src.add_argument('--dump')
    ap.add_argument('--target', action='append', required=True,
                    help='目標 VA（可多次）。支援 0x1234 或者 0x1234:名稱')
    ap.add_argument('--span', default='0', help='目標 ±span 之內都算（預設 0）')
    ap.add_argument('--context', type=int, default=48, help='命中處顯示前後幾多 bytes')
    ap.add_argument('--max', type=int, default=8, help='每個目標最多顯示幾個命中')
    ap.add_argument('--exec-only', action='store_true', default=True, help='只掃可執行頁（預設）')
    ap.add_argument('--all-regions', action='store_true', help='連非可執行頁都掃（慢好多）')
    args = ap.parse_args(argv)

    targets = []
    for spec in args.target:
        if ':' in spec:
            va_s, name = spec.split(':', 1)
        else:
            va_s, name = spec, spec
        targets.append((int(va_s, 0), name))
    span = int(args.span, 0)
    print('目標：' + ', '.join(f'{n}@0x{v:x}' for v, n in targets) + f'（span={span}）')

    hits: Dict[str, List[Tuple[int, int, int, int]]] = {n: [] for _, n in targets}
    if args.dump:
        md = MiniDump(args.dump)
        regions = [Region(s, size) for s, size, _ in md.ranges]
        read = lambda base, size: md.read_va(base, size)  # noqa: E731
    else:
        pid = args.pid or find_pid(args.process)
        if not pid:
            return 2
        regions = live_regions(pid, not args.all_regions)
        read = lambda base, size: read_bytes(pid, base, size)  # noqa: E731

    prot_names = {0x1: 'NOACCESS', 0x2: 'RO', 0x4: 'RW', 0x8: 'WC', 0x10: 'EXEC',
                  0x20: 'EXEC_R', 0x40: 'EXEC_RW', 0x80: 'EXEC_WC'}
    total = sum(r.size for r in regions)
    print(f'掃描 {len(regions)} 個 region，合共 {total / 1048576:.1f} MB')
    chunk = 16 << 20
    scanned = 0
    next_report = 0
    for region in regions:
        off = 0
        while off < region.size:
            want = min(chunk, region.size - off)
            data = read(region.base + off, want)
            if data:
                scanned += len(data)
                for va, name in scan_block(data, region.base + off, targets, span):
                    if len(hits[name]) < args.max:
                        hits[name].append((va, region.base, region.size, region.protect))
            off += want
            if scanned >= next_report:
                next_report = scanned + (32 << 20)
                print(f'  已掃 {scanned / 1048576:.0f} / {total / 1048576:.0f} MB')

    print('\n=== 結果 ===')
    any_hit = False
    for _, name in targets:
        found = hits[name]
        any_hit = any_hit or bool(found)
        print(f'  {name}: {len(found)} 個命中')
        for va, rbase, rsize, rprot in found:
            print(f'    指令 @0x{va:x}　[region 0x{rbase:x} + 0x{rsize:x} '
                  f'{prot_names.get(rprot, hex(rprot))}]')
            print(f'      → 抽返嚟分析：scanmem.py --process {args.process or "AION2.exe"} '
                  f'--dump-region 0x{rbase:x} --size 0x{rsize:x} --out {name}_{rbase:x}.bin')
            if args.dump:
                data = read(va - args.context, args.context * 2)
            else:
                data = read_bytes(pid, va - args.context, args.context * 2)
            if data:
                base = va - args.context
                for i in range(0, len(data), 16):
                    print(f'      {base + i:012x}  ' + data[i:i + 16].hex(' '))
    if not any_hit:
        print('  （冇命中）—— 可能引用者用咗非 RIP-relative 形式、頁面被保護，或者目標 VA 唔啱')
        return 2
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(main())
