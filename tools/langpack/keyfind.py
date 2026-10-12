"""由遊戲記憶體搵出 L10NString 嘅 AES key（官方每次更新換 key 時用）。

原理：容器本體（dat[0x14:]）係 AES-256-ECB，明文開頭係 LZ4 壓縮流，
而壓縮流最初嘅 literal run 一定包含 raw table 嘅開頭 `01 00 00 00 "AION2"`。
所以正確嘅 key 會令：

    AES-256-ECB_decrypt(dat[0x14:0x14+0x60], key) 出現 b"AION2"（或 01 00 00 00 AION2）

喺記憶體逐個 32-byte 視窗試呢個條件（假陽性率極低），搵到之後再跑一次完整
l10n 解析確認。

（v2 舊格式仲有「本體頭 32 bytes 一定係零」呢個更強嘅條件，但 2026-10 更新之後
官方 dat 已經唔再符合，所以而家改用上面嘅已知明文方式。）

兩種來源：

1. **記憶體 dump 檔**（最安全）：遊戲行緊嘅時候用 procdump / 工作管理員整個 full dump：
       procdump -ma AION2.exe aion2.dmp
       python keyfind.py --dump aion2.dmp --dat official-en-US.dat --write-keys

2. **直接讀 live process**（唔需要 dump，但要開住遊戲，通常要管理員身分）：
       python keyfind.py --process AION2.exe --dat official-en-US.dat --write-keys
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
PROBE_LEN = 0x60  # 驗證候選 key 時解密幾多 bytes（要足夠包住 LZ4 開頭嘅 literal run）
DEFAULT_STRIDE = 8  # 32-byte key 唔會奇形怪狀對齊，通常 8 或 16
MARKERS = (b"AION2", b"\x01\x00\x00\x00AION2")


def load_probe(dat_path: str, locale: str) -> bytes:
    dat = open(dat_path, "rb").read()
    packed, etype, aligned, raw = l10n.header(dat, locale)
    if etype != 2:
        raise SystemExit(f"唔係預期嘅容器（etype={etype}）")
    probe = dat[0x14:0x14 + PROBE_LEN]
    if len(probe) < PROBE_LEN:
        raise SystemExit("dat 太短")
    if probe[:16] != probe[16:32]:
        # v2 舊格式本體頭 32 bytes 係零 → ECB 下頭兩個 ciphertext block 應該一樣。
        # 唔一樣代表格式改咗（2026-10 之後就係咁），唔再當錯誤，只用已知明文驗證。
        print("注意：dat 頭兩個 AES block 唔相同（新版格式），改用已知明文（AION2）驗證。")
    return probe


def matches(key: bytes, probe: bytes) -> bool:
    try:
        pt = AES.new(key, AES.MODE_ECB).decrypt(probe)
    except Exception:
        return False
    return any(m in pt for m in MARKERS)


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
    """同名 process（AION2.exe 會有 launcher + 遊戲本體）就揀 working set 最大嗰個。"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    TH32CS_SNAPPROCESS = 0x2

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    def mem_mb(pid: int) -> float:
        h = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not h:
            return 0.0
        c = PMC()
        c.cb = ctypes.sizeof(c)
        ok = psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb)
        kernel32.CloseHandle(h)
        return c.WorkingSetSize / 1048576 if ok else 0.0

    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    name_l = name.lower()
    found = []
    if kernel32.Process32First(snap, ctypes.byref(entry)):
        while True:
            exe = entry.szExeFile.decode("mbcs", "replace").lower()
            if exe == name_l or exe.startswith(name_l):
                found.append((entry.th32ProcessID, entry.szExeFile.decode("mbcs", "replace")))
            if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(snap)
    if not found:
        return 0
    if len(found) == 1:
        return found[0][0]
    sized = sorted(((mem_mb(p), p, n) for p, n in found), reverse=True)
    print("同名 process 有多個，揀 working set 最大嗰個（通常係遊戲本體）：")
    for mb, p, n in sized:
        print(f"  PID {p:<7} {mb:8.1f} MB  {n}{'  <- 用呢個' if p == sized[0][1] else ''}")
    return sized[0][1]


def list_regions(pid: int) -> List[Tuple[int, int]]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess 失敗（錯誤 {ctypes.get_last_error()}）—— 可能要用管理員身分執行")
    out: List[Tuple[int, int]] = []
    mbi = MEMORY_BASIC_INFORMATION64()
    address = 0
    while kernel32.VirtualQueryEx(handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)):
        if (mbi.State == MEM_COMMIT and mbi.Protect in READABLE
                and mbi.Protect != PAGE_NOACCESS and not (mbi.Protect & PAGE_GUARD)):
            out.append((mbi.BaseAddress, mbi.RegionSize))
        address = mbi.BaseAddress + mbi.RegionSize
        if address <= 0 or address > 0x7FFFFFFFFFFF:
            break
    kernel32.CloseHandle(handle)
    return out


def _scan_live_chunk(args) -> List[Tuple[int, str]]:
    pid, regions, probe, stride = args
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        return []
    hits: List[Tuple[int, str]] = []
    buf = ctypes.create_string_buffer(16 << 20)
    read = ctypes.c_size_t()
    for base, size in regions:
        off = 0
        while off < size:
            want = min(len(buf), size - off)
            if kernel32.ReadProcessMemory(handle, ctypes.c_void_p(base + off), buf, want, ctypes.byref(read)):
                data = buf.raw[:read.value]
                for i in range(0, len(data) - WINDOW + 1, stride):
                    if matches(data[i:i + WINDOW], probe):
                        hits.append((base + off + i, data[i:i + WINDOW].hex()))
            off += want
    kernel32.CloseHandle(handle)
    return hits


def scan_process(pid: int, probe: bytes, stride: int, workers: int = 1) -> List[Tuple[int, str]]:
    regions = list_regions(pid)
    total = sum(s for _, s in regions)
    print(f"可讀 region {len(regions)} 個，合共 {total / 1048576:.0f} MB")
    # 按大小平均分俾 worker
    groups: List[List[Tuple[int, int]]] = [[] for _ in range(max(1, workers))]
    loads = [0] * len(groups)
    for base, size in sorted(regions, key=lambda r: -r[1]):
        idx = loads.index(min(loads))
        groups[idx].append((base, size))
        loads[idx] += size
    jobs = [(pid, g, probe, stride) for g in groups if g]
    hits: List[Tuple[int, str]] = []
    if len(jobs) <= 1:
        hits = _scan_live_chunk(jobs[0])
    else:
        pool = None
        try:
            pool = Pool(len(jobs))
            for result in pool.imap_unordered(_scan_live_chunk, jobs):
                hits.extend(result)
                print(f"  完成一部分，暫時命中 {len(hits)}")
            pool.close()
            pool.join()
        except (OSError, PermissionError, ImportError) as exc:
            if pool is not None:
                try:
                    pool.terminate()
                except Exception:
                    pass
            print(f"（multiprocessing 唔可用：{exc}；改用 thread）")
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=len(jobs)) as pool2:
                for result in pool2.map(_scan_live_chunk, jobs):
                    hits.extend(result)
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
    print(f"語系 {args.locale}　seed {seed}　驗證方式：解密 dat[0x14:0x74] 要出現 \"AION2\" 已知明文")

    dat = open(args.dat, "rb").read()
    started = time.time()
    if args.dump:
        print(f"掃描 dump：{args.dump}（stride={args.stride}, workers={args.workers}）")
        hits = scan_dump(args.dump, probe, args.stride, args.workers)
    else:
        pid = args.pid or find_pid(args.process)
        if not pid:
            raise SystemExit(f"搵唔到 process：{args.process}")
        print(f"掃描 process {args.process} (PID {pid})（stride={args.stride}, workers={args.workers}）")
        hits = scan_process(pid, probe, args.stride, args.workers)
    elapsed = time.time() - started

    # 去重
    unique = {}
    for off, key in hits:
        unique.setdefault(key, off)
    print(f"用了 {elapsed:.1f} 秒，找到 {len(unique)} 個符合條件嘅候選")

    confirmed = {}
    for key_hex, off in unique.items():
        key = bytes.fromhex(key_hex)
        try:
            entries = l10n.decrypt(dat, key, args.locale)
        except Exception as exc:
            print(f"  {key_hex}  (0x{off:x}) → 完整解析失敗（{exc}）")
            continue
        print(f"  ★ {key_hex}  (0x{off:x}) → 成功解析 {len(entries)} 條 ✓")
        confirmed[key_hex] = off

    if not confirmed:
        if unique:
            print("有候選但完整解析唔成功 —— 可能係假陽性，試下 --stride 4 再掃。")
        else:
            print("搵唔到 —— 可能遊戲未載入語言檔、process 揀錯（要揀最大嗰個）、"
                  "或者要管理員身分；亦可以試 --stride 4。")
        return 2
    if args.write_keys:
        for key_hex in confirmed:
            write_keys(args.write_keys, seed, key_hex)
            break  # 同一個 seed 只需要一條 key
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
