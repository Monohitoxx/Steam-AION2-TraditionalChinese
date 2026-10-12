"""由遊戲記憶體搵出 L10NString 嘅 AES key（官方每次更新換 key 時用）。

原理：v2 容器本體頭 32 bytes 明文一定係 0，所以正確嘅 key 一定滿足

    AES-256-ECB_decrypt(dat[0x14:0x34], key) == bytes(32)

喺記憶體裡面逐個 32-byte 視窗試呢個條件（兩個 AES block 都係 0，假陽性率 2^-256）。

兩種來源：

1. **記憶體 dump 檔**（推薦，最安全）：遊戲行緊嘅時候用 procdump / 工作管理員整
   個 full dump，之後離線掃描。例：
       procdump -ma AION2.exe aion2.dmp
       python keyfind.py --dump aion2.dmp --dat official-en-US.dat --write-keys

2. **直接讀 live process**（唔需要 dump，但要開住遊戲）：
       python keyfind.py --process AION2.exe --dat official-en-US.dat

搵到之後會印出 key，可以用 --write-keys 直接寫入 keys.json（seed 由 dat 嘅語系算出）。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
import sys
import time
from ctypes import wintypes
from multiprocessing import Pool
from typing import Iterable, List, Tuple

from Crypto.Cipher import AES

import l10n

WINDOW = 32
DEFAULT_STRIDE = 8  # 32-byte key 唔會奇形怪狀對齊，通常 8 或 16


def load_probe(dat_path: str, locale: str) -> bytes:
    dat = open(dat_path, "rb").read()
    packed, etype, aligned, raw = l10n.header(dat, locale)
    if etype != 2:
        raise SystemExit(f"唔係預期嘅容器（etype={etype}）")
    probe = dat[0x14:0x14 + WINDOW]
    if probe[:16] != probe[16:32]:
        raise SystemExit("警告：dat 頭兩個 AES block 唔相同，格式可能變咗，請先檢查 l10n.py")
    return probe


def matches(key: bytes, probe: bytes) -> bool:
    try:
        return AES.new(key, AES.MODE_ECB).decrypt(probe) == bytes(WINDOW)
    except Exception:
        return False


# ---------------------------------------------------------------- dump 檔


def _scan_chunk(args) -> List[Tuple[int, str]]:
    path, start, end, probe, stride = args
    hits: List[Tuple[int, str]] = []
    with open(path, "rb") as fh:
        fh.seek(start)
        buf = fh.read(end - start + WINDOW)
    for off in range(0, len(buf) - WINDOW + 1, stride):
        if matches(buf[off:off + WINDOW], probe):
            hits.append((start + off, buf[off:off + WINDOW].hex()))
    return hits


def scan_dump(path: str, probe: bytes, stride: int, workers: int) -> List[Tuple[int, str]]:
    size = os.path.getsize(path)
    if workers <= 1:
        return _scan_chunk((path, 0, size, probe, stride))
    chunk = max(4 << 20, (64 << 20) // max(1, workers) * 8)
    jobs = [(path, off, min(off + chunk, size), probe, stride) for off in range(0, size, chunk)]
    hits: List[Tuple[int, str]] = []
    pool = None
    try:
        pool = Pool(workers)
        iterator = pool.imap_unordered(_scan_chunk, jobs)
        for result in iterator:
            hits.extend(result)
        pool.close()
        pool.join()
        return hits
    except (OSError, PermissionError, ImportError) as exc:
        # 某啲受限環境（例如沙箱）唔准開 named pipe，multiprocessing 會失敗 -> 改用 thread
        if pool is not None:
            try:
                pool.terminate()
            except Exception:
                pass
        print(f"（multiprocessing 唔可用：{exc}；改用 thread）")
        from concurrent.futures import ThreadPoolExecutor

        hits = []
        with ThreadPoolExecutor(max_workers=workers) as pool2:
            for result in pool2.map(_scan_chunk, jobs):
                hits.extend(result)
        return hits


# ---------------------------------------------------------------- live process

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100
READABLE = (0x02, 0x04, 0x20, 0x40)  # RO, RW, EXEC_R, EXEC_RW


class MEMORY_BASIC_INFORMATION64(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_ulonglong),
        ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", wintypes.DWORD),
        ("__alignment1", wintypes.DWORD),
        ("RegionSize", ctypes.c_ulonglong),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("__alignment2", wintypes.DWORD),
    ]


def find_pid(name: str) -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    TH32CS_SNAPPROCESS = 0x2

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    name_l = name.lower()
    pid = 0
    if kernel32.Process32First(snap, ctypes.byref(entry)):
        while True:
            exe = entry.szExeFile.decode("mbcs", "replace").lower()
            if exe == name_l or exe.startswith(name_l):
                pid = entry.th32ProcessID
                break
            if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(snap)
    return pid


def scan_process(pid: int, probe: bytes, stride: int) -> List[Tuple[int, str]]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess 失敗（錯誤 {ctypes.get_last_error()}）—— 可能要用管理員身分執行")
    hits: List[Tuple[int, str]] = []
    mbi = MEMORY_BASIC_INFORMATION64()
    address = 0
    buf = ctypes.create_string_buffer(16 << 20)
    read = ctypes.c_size_t()
    total = 0
    while kernel32.VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)):
        if mbi.State == MEM_COMMIT and mbi.Protect in READABLE and mbi.Protect != PAGE_NOACCESS and not (mbi.Protect & PAGE_GUARD):
            region = mbi.RegionSize
            off = 0
            while off < region:
                want = min(len(buf), region - off)
                if kernel32.ReadProcessMemory(handle, ctypes.c_void_p(mbi.BaseAddress + off), buf, want, ctypes.byref(read)):
                    data = buf.raw[:read.value]
                    total += len(data)
                    for i in range(0, len(data) - WINDOW + 1, stride):
                        if matches(data[i:i + WINDOW], probe):
                            hits.append((mbi.BaseAddress + off + i, data[i:i + WINDOW].hex()))
                off += want
        address = mbi.BaseAddress + mbi.RegionSize
        if address <= 0 or address > 0x7FFFFFFFFFFF:
            break
    kernel32.CloseHandle(handle)
    print(f"  已掃描 {total >> 20} MB")
    return hits


# ---------------------------------------------------------------- main


def write_keys(path: str, seed: int, key_hex: str) -> None:
    data = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    data[str(seed)] = key_hex
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=0)
        fh.write("\n")
    print(f"已寫入 {path}（seed {seed}）")


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="由遊戲記憶體搵 L10NString AES key")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--dump", help="記憶體 dump 檔（procdump -ma / 工作管理員建立傾印）")
    src.add_argument("--process", help="遊戲 process 名（例如 AION2.exe）")
    ap.add_argument("--pid", type=int, help="直接指定 PID")
    ap.add_argument("--dat", required=True, help="官方 dat（官方 en-US 語言包）")
    ap.add_argument("--locale", default="en-US")
    ap.add_argument("--stride", type=int, default=DEFAULT_STRIDE, help="掃描步進（預設 8）")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    ap.add_argument("--write-keys", nargs="?", const="keys.json", help="把搵到嘅 key 寫入 keys.json")
    args = ap.parse_args(argv)

    probe = load_probe(args.dat, args.locale)
    seed = l10n.seed_for(args.locale)
    print(f"語系 {args.locale}　seed {seed}　目標：AES_decrypt(dat[0x14:0x34], key) == 0")

    started = time.time()
    if args.dump:
        print(f"掃描 dump：{args.dump}（stride={args.stride}, workers={args.workers}）")
        hits = scan_dump(args.dump, probe, args.stride, args.workers)
    else:
        pid = args.pid or find_pid(args.process)
        if not pid:
            raise SystemExit(f"搵唔到 process：{args.process}")
        print(f"掃描 process {args.process} (PID {pid})（stride={args.stride}）")
        hits = scan_process(pid, probe, args.stride)
    elapsed = time.time() - started

    # 去重
    unique = {}
    for off, key in hits:
        unique.setdefault(key, off)
    print(f"用了 {elapsed:.1f} 秒，找到 {len(unique)} 個符合條件嘅 key")
    for key, off in unique.items():
        print(f"  key={key}  (第一個位置 0x{off:x})")
    if not unique:
        print("搵唔到 —— 可能遊戲未載入語言檔、dump 唔夠完整，或者 stride 太大（試 --stride 4）")
        return 2
    if args.write_keys:
        for key in unique:
            write_keys(args.write_keys, seed, key)
            break  # 同一個 seed 只需要一條 key
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
