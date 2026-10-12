"""喺成個 process（或 minidump）嘅記憶體掃 marker，用嚟定位 packer 真正解密後嘅 image。

AION2.exe 嘅 module 映像（0x140000000）喺記憶體裡面仍然係 NCGuard 加密嘅 stub
（連 `.dll` / `L10NString_` 都搵唔到），真正嘅 code/data 通常喺其他 region
（動態配置、高位 heap 等）。所以要先「全記憶體搵 marker」，再針對有料嘅 region 做 xref。

用法::

    # live process：搵 L10N 字串 + BLAKE3 IV + root 常數
    python scanmem.py --process AION2.exe --preset blake3 --find-ascii L10NString_

    # 由 dump 檔掃
    python scanmem.py --dump aion2-full.dmp --preset blake3

    # 揀到有料嘅 region 之後，抽成檔案做 xref 分析
    python scanmem.py --process AION2.exe --dump-region 0x2651c9060 --size 0x100000 --out region.bin
"""

from __future__ import annotations

import argparse
import ctypes
import os
import struct
import sys
from ctypes import wintypes
from typing import Dict, List, Sequence, Tuple

from minidump import MiniDump
from unpack import (MEMORY_BASIC_INFORMATION64, PROCESS_QUERY_INFORMATION, PROCESS_VM_READ,
                    READABLE, MEM_COMMIT, PAGE_GUARD, find_pid, list_processes)

PRESETS = {
    "blake3": {
        "blake3 IV[0..7] (64-bit)": b"".join(struct.pack("<Q", v) for v in
                                             (0x6A09E667F3BCC908, 0xBB67AE8584CAA73B, 0x3C6EF372FE94F82B,
                                              0xA54FF53A5F1D36F1, 0x510E527FADE682D1, 0x9B05688C2B3E6C1F,
                                              0x1F83D9ABFB41BD6B, 0x5BE0CD19137E2179)),
        "blake3 IV[0..7] (32-bit)": b"".join(struct.pack("<I", v) for v in
                                             (0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
                                              0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19)),
        "rootConst 0xCD02190910CE83F6": struct.pack("<Q", 0xCD02190910CE83F6),
        "rootConst 32-bit 前半 0x10CE83F6": struct.pack("<I", 0x10CE83F6),
        "rootConst 32-bit 後半 0xCD021909": struct.pack("<I", 0xCD021909),
    },
    "aion2": {
        "rootConst 0xCD02190910CE83F6": struct.pack("<Q", 0xCD02190910CE83F6),
        "rootConst 32-bit 前半 0x10CE83F6": struct.pack("<I", 0x10CE83F6),
        "ascii L10NString": b"L10NString",
        "utf16 L10NString": "L10NString".encode("utf-16le"),
        "ascii L10N": b"L10N",
        "ascii en-US": b"en-US",
        "utf16 en-US": "en-US".encode("utf-16le"),
        "ascii ko-KR": b"ko-KR",
        "ascii AION2": b"AION2",
        "utf16 AION2": "AION2".encode("utf-16le"),
        "ascii String_UI_": b"String_UI_",
        "utf16 String_UI_": "String_UI_".encode("utf-16le"),
        "pakKey": bytes.fromhex("06038EF544B6007614F8574F1B7C2A3F0D565F74CDCC1B366B4EA1A17B97CBFF"),
    },
}


class Region:
    __slots__ = ("base", "size", "protect", "type")

    def __init__(self, base: int, size: int, protect: int = 0, rtype: int = 0):
        self.base, self.size, self.protect, self.type = base, size, protect, rtype


def live_regions(pid: int, include_guard: bool = False) -> List[Region]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess 失敗（錯誤 {ctypes.get_last_error()}）—— 試下用管理員身分執行")
    out: List[Region] = []
    mbi = MEMORY_BASIC_INFORMATION64()
    address = 0
    limit = 0x7FFFFFFFFFFF
    guarded = 0
    while address < limit and kernel32.VirtualQueryEx(
            handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)):
        if mbi.State == MEM_COMMIT and mbi.Protect in READABLE:
            if mbi.Protect & PAGE_GUARD:
                guarded += 1
                if not include_guard:
                    address = mbi.BaseAddress + mbi.RegionSize
                    continue
            out.append(Region(mbi.BaseAddress, mbi.RegionSize, mbi.Protect, mbi.Type))
        address = mbi.BaseAddress + mbi.RegionSize
        if mbi.RegionSize == 0:
            break
    kernel32.CloseHandle(handle)
    if guarded and not include_guard:
        print(f"（另有 {guarded} 個 PAGE_GUARD region 被跳過；packer 可能用 guard page 保護解密後嘅 code，"
              "可以加 --include-guard 試）")
    return out


def read_live(pid: int, base: int, size: int):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess 失敗（錯誤 {ctypes.get_last_error()}）")
    buf = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t()
    ok = kernel32.ReadProcessMemory(handle, ctypes.c_void_p(base), buf, size, ctypes.byref(read))
    kernel32.CloseHandle(handle)
    return buf.raw[:read.value] if ok and read.value else None


def find_pe_images(data: bytes, chunk_va: int):
    """喺一段記憶體搵「手動 map 嘅 PE image」（MZ + PE header + 合理 SizeOfImage）。"""
    out = []
    start = 0
    while True:
        i = data.find(b"MZ", start)
        if i == -1 or i + 0x100 > len(data):
            break
        try:
            pe_off = struct.unpack_from("<I", data, i + 0x3C)[0]
            if 0x40 <= pe_off <= 0x1000 and data[i + pe_off:i + pe_off + 4] == b"PE\0\0":
                opt = i + pe_off + 24
                magic = struct.unpack_from("<H", data, opt)[0]
                if magic in (0x10B, 0x20B):
                    size = struct.unpack_from("<I", data, opt + 56)[0]
                    if (1 << 20) <= size <= (4 << 30):
                        out.append((chunk_va + i, size))
        except Exception:
            pass
        start = i + 2
    return out


def scan_live(pid: int, patterns: Dict[str, bytes], chunk: int = 32 << 20, max_hits: int = 6,
              find_pe: bool = False, include_guard: bool = False):
    hits: Dict[str, List[Tuple[int, int]]] = {k: [] for k in patterns}
    per_region: Dict[str, int] = {}
    hit_regions: Dict[int, Region] = {}
    pe_images: List[Tuple[int, int, int]] = []
    regions = live_regions(pid, include_guard)
    total = sum(r.size for r in regions)
    print(f"可讀 region {len(regions)} 個，合共 {total / 1048576:.1f} MB")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    buf = ctypes.create_string_buffer(chunk)
    read = ctypes.c_size_t()
    scanned = 0
    next_report = 0
    for region in regions:
        off = 0
        while off < region.size:
            want = min(chunk, region.size - off)
            if not kernel32.ReadProcessMemory(handle, ctypes.c_void_p(region.base + off), buf, want,
                                              ctypes.byref(read)) or not read.value:
                off += want
                continue
            data = buf.raw[:read.value]
            scanned += len(data)
            for name, needle in patterns.items():
                start = 0
                while True:
                    i = data.find(needle, start)
                    if i == -1:
                        break
                    va = region.base + off + i
                    if len(hits[name]) < max_hits:
                        hits[name].append((va, region.size))
                    per_region[f"0x{region.base:x}"] = per_region.get(f"0x{region.base:x}", 0) + 1
                    hit_regions[region.base] = region
                    start = i + 1
            if find_pe:
                for va, size in find_pe_images(data, region.base + off):
                    pe_images.append((va, size, region.base))
                    hit_regions[region.base] = region
            off += want
        if scanned >= next_report:
            next_report = scanned + (64 << 20)
            print(f"  已掃 {scanned / 1048576:.0f} / {total / 1048576:.0f} MB")
    kernel32.CloseHandle(handle)
    return hits, per_region, hit_regions, pe_images


def scan_dump(path: str, patterns: Dict[str, bytes], max_hits: int = 6, find_pe: bool = False):
    md = MiniDump(path)
    hits: Dict[str, List[Tuple[int, int]]] = {k: [] for k in patterns}
    hit_regions: Dict[int, Region] = {}
    pe_images: List[Tuple[int, int, int]] = []
    print(f"{path}: {md.size / 1048576:.1f} MB，ranges={len(md.ranges)}")
    for start, size, off in md.ranges:
        data = md._read(off, size)
        for name, needle in patterns.items():
            i = data.find(needle)
            while i != -1:
                if len(hits[name]) < max_hits:
                    hits[name].append((start + i, size))
                hit_regions[start] = Region(start, size)
                i = data.find(needle, i + 1)
        if find_pe:
            for va, isize in find_pe_images(data, start):
                pe_images.append((va, isize, start))
                hit_regions[start] = Region(start, size)
    return hits, {}, hit_regions, pe_images


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="全 process／dump 記憶體 marker 掃描")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--process", help="process 名（AION2.exe）")
    src.add_argument("--pid", type=int, help="PID")
    src.add_argument("--dump", help="minidump 檔")
    ap.add_argument("--preset", choices=sorted(PRESETS), help="內建 marker 組")
    ap.add_argument("--find-hex", action="append", default=[], help="額外 hex pattern")
    ap.add_argument("--find-ascii", action="append", default=[], help="額外 ASCII pattern")
    ap.add_argument("--preset-aion2", action="store_true", help="等同 --preset aion2")
    ap.add_argument("--dump-region", help="抽某個 region（VA）")
    ap.add_argument("--dump-hits", metavar="DIR", help="把所有命中嘅 region 抽到 DIR（方便之後分析）")
    ap.add_argument("--max-region", default="64", help="--dump-hits 每個 region 最多抽幾 MB（預設 64）")
    ap.add_argument("--find-pe", action="store_true", help="同時搵手動 map 嘅 PE image（MZ + PE header）")
    ap.add_argument("--include-guard", action="store_true", help="連 PAGE_GUARD region 都掃（packer 可能用嚟保護解密後嘅 code）")
    ap.add_argument("--size", default="0x100000", help="配合 --dump-region 嘅大小")
    ap.add_argument("--out", help="配合 --dump-region 嘅輸出檔")
    ap.add_argument("--max-hits", type=int, default=6)
    args = ap.parse_args(argv)

    patterns: Dict[str, bytes] = {}
    if args.preset:
        patterns.update(PRESETS[args.preset])
    if args.preset_aion2:
        patterns.update(PRESETS["aion2"])
    for i, h in enumerate(args.find_hex):
        patterns[f"hex[{i}] {h}"] = bytes.fromhex(h)
    for i, s in enumerate(args.find_ascii):
        patterns[f"ascii[{i}] {s}"] = s.encode()
    if not patterns:
        patterns = dict(PRESETS["aion2"])

    if args.dump_region:
        if not args.out:
            raise SystemExit("--dump-region 要配 --out")
        base = int(args.dump_region, 0)
        size = int(args.size, 0)
        if args.dump:
            md = MiniDump(args.dump)
            data = md.read_va(base, size)
            if data is None:
                raise SystemExit(f"dump 裡面讀唔到 VA 0x{base:x}")
            open(args.out, "wb").write(data)
            print(f"已寫出 {args.out}（{len(data)} bytes，VA 0x{base:x}）")
            return 0
        pid = args.pid or find_pid(args.process)
        if not pid:
            return 2
        from unpack import read_range

        written = read_range(pid, base, size, args.out)
        print(f"已寫出 {args.out}（0x{base:x} 起 0x{size:x} bytes，實際讀到 {written / 1048576:.1f} MB；"
              "讀唔到嘅頁面補 0）")
        return 0

    if args.dump:
        hits, _, hit_regions, pe_images = scan_dump(args.dump, patterns, args.max_hits, args.find_pe)
        if pe_images:
            print(f"\n=== 搵到 {len(pe_images)} 個 PE image ===")
            for va, size, region_base in sorted(pe_images, key=lambda t: -t[1])[:12]:
                print(f"  PE @0x{va:x}  SizeOfImage=0x{size:x}（{size / 1048576:.1f} MB）region base 0x{region_base:x}")
    else:
        pid = args.pid or find_pid(args.process)
        if not pid:
            return 2
        print(f"掃描 process PID {pid}")
        hits, per_region, hit_regions, pe_images = scan_live(pid, patterns, max_hits=args.max_hits,
                                                            find_pe=args.find_pe, include_guard=args.include_guard)
        if per_region:
            top = sorted(per_region.items(), key=lambda kv: -kv[1])[:8]
            print("最多 marker 嘅 region：" + "  ".join(f"{k}({v})" for k, v in top))
        if pe_images:
            print(f"\n=== 搵到 {len(pe_images)} 個手動 map 嘅 PE image ===")
            for va, size, region_base in sorted(pe_images, key=lambda t: -t[1])[:12]:
                print(f"  PE @0x{va:x}  SizeOfImage=0x{size:x}（{size / 1048576:.1f} MB）region base 0x{region_base:x}")

    print("\n=== 結果 ===")
    for name, found in hits.items():
        print(f"  {name}: {len(found)} 個" + ("" if not found else ""))
        for va, region_size in found:
            print(f"      0x{va:x}（region size 0x{region_size:x}）")

    if args.dump_hits and (hit_regions or pe_images):
        os.makedirs(args.dump_hits, exist_ok=True)
        cap = int(float(args.max_region) * 1048576)
        if args.dump:
            md = MiniDump(args.dump)
            for base, region in sorted(hit_regions.items()):
                size = min(region.size, cap)
                data = md.read_va(base, size) or b""
                data += bytes(max(0, size - len(data)))
                out = os.path.join(args.dump_hits, f"region_{base:x}.bin")
                open(out, "wb").write(data)
                print(f"  抽出 {out}（0x{base:x} + 0x{size:x}）")
            for va, size, _ in sorted(pe_images, key=lambda t: -t[1])[:6]:
                size = min(size, cap)
                data = md.read_va(va, size) or b""
                data += bytes(max(0, size - len(data)))
                out = os.path.join(args.dump_hits, f"pe_{va:x}.bin")
                open(out, "wb").write(data)
                print(f"  抽出 {out}（PE image 0x{va:x} + 0x{size:x}）")
        else:
            from unpack import read_range

            pid = args.pid or find_pid(args.process)
            for base, region in sorted(hit_regions.items()):
                size = min(region.size, cap)
                out = os.path.join(args.dump_hits, f"region_{base:x}.bin")
                written = read_range(pid, base, size, out)
                print(f"  抽出 {out}（0x{base:x} + 0x{size:x}，實際 {written / 1048576:.1f} MB）")
            for va, size, _ in sorted(pe_images, key=lambda t: -t[1])[:6]:
                size = min(size, cap)
                out = os.path.join(args.dump_hits, f"pe_{va:x}.bin")
                written = read_range(pid, va, size, out)
                print(f"  抽出 {out}（PE image 0x{va:x} + 0x{size:x}，實際 {written / 1048576:.1f} MB）")

    if not any(hits.values()) and not pe_images:
        print("  （冇命中）")
        print("  提示：確認遊戲已經入到登入畫面／角色選單（L10N 已載入），或者加 --find-ascii 再試")
        return 2
    print("\n下一步：")
    print("  1) 如果 --find-pe 揾到好大（幾百 MB）嘅 PE image，就用 "
          "scanmem.py --dump-region <VA> --size 0x<SizeOfImage> --out image.bin 抽佢")
    print("  2) 再 xref.py image.bin --base <VA> --preset blake3 --span 0x100")
    print("  3) 或者直接 --dump-hits regions\\ 一次過抽晒所有命中 region，交俾我分析")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
