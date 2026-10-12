"""由 minidump 抽出某個 module 喺記憶體嘅映像（即係 packer 解密之後嘅 code），並檢查完整度。

用法::

    python unpack.py --dump aion2.dmp --module AION2.exe --out AION2.unpacked.bin
    python unpack.py --dump aion2.dmp --list            # 睇下有咩 module
"""

from __future__ import annotations

import argparse
import ctypes
import os
import struct
import sys
from ctypes import wintypes
from typing import Sequence, Tuple

from minidump import MiniDump

MARKERS = {
    "MZ header": b"MZ",
    "ascii L10NString_": b"L10NString_",
    "ascii en-US": b"en-US",
    "blake3 IV[0] (64-bit)": struct.pack("<Q", 0x6A09E667F3BCC908),
    "blake3 IV[0] (32-bit)": struct.pack("<I", 0x6A09E667),
    "rootConst 0xCD02190910CE83F6": struct.pack("<Q", 0xCD02190910CE83F6),
    "ascii .dll": b".dll",
}

# ---------------------------------------------------------------- live process

TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
READABLE = (0x02, 0x04, 0x20, 0x40, 0x08, 0x80)  # RO/RW/EXEC_R/EXEC_RW/WC/WC_EXEC


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD), ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.c_void_p), ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE), ("szModule", ctypes.c_char * 256), ("szExePath", ctypes.c_char * 260),
    ]


class MEMORY_BASIC_INFORMATION64(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_ulonglong), ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", wintypes.DWORD), ("__alignment1", wintypes.DWORD),
        ("RegionSize", ctypes.c_ulonglong), ("State", wintypes.DWORD), ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD), ("__alignment2", wintypes.DWORD),
    ]


def list_processes(needle: str = "") -> list:
    """列出 process（(pid, name)）；needle 非空就只列名稱含 needle 嘅。"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    TH32CS_SNAPPROCESS = 0x2

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260),
        ]

    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == ctypes.c_void_p(-1).value:
        raise SystemExit(f"CreateToolhelp32Snapshot 失敗（{ctypes.get_last_error()}）")
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    out = []
    if kernel32.Process32First(snap, ctypes.byref(entry)):
        while True:
            name = entry.szExeFile.decode("mbcs", "replace")
            if not needle or needle.lower() in name.lower():
                out.append((entry.th32ProcessID, name))
            if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(snap)
    return out


def process_memory_bytes(pid: int) -> int:
    """拎 process working set（用 QUERY_LIMITED_INFORMATION，受保護嘅 process 通常都開得到）。"""
    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return 0
    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
    kernel32.CloseHandle(handle)
    return counters.WorkingSetSize if ok else 0


def find_pid(name: str) -> int:
    """搵 process：先完全符合，再前綴，再包含。

    如果有多個同名 process（AION2.exe 會同時有 launcher 同遊戲本體），
    會揀 working set 最大嗰個（= 真正遊戲），並列晒出嚟。
    """
    wanted = name.lower()
    procs = list_processes()
    exact = [(pid, pname) for pid, pname in procs if pname.lower() == wanted]
    if not exact:
        prefix = [(pid, pname) for pid, pname in procs if pname.lower().startswith(wanted)]
        if len(prefix) == 1:
            print(f"（用前綴符合嘅 process：{prefix[0][1]} PID {prefix[0][0]}）")
            return prefix[0][0]
        contains = [(pid, pname) for pid, pname in procs if wanted in pname.lower()]
        if len(contains) == 1:
            print(f"（用包含符合嘅 process：{contains[0][1]} PID {contains[0][0]}）")
            return contains[0][0]
        if len(contains) > 1:
            print(f"「{name}」對中多個 process：")
            for pid, pname in contains:
                print(f"  PID {pid:<7} {process_memory_bytes(pid) / 1048576:8.1f} MB  {pname}")
            print("請用 --pid <PID> 指定其中一個")
            return 0
        print(f"搵唔到 process：{name}")
        guesses = [p for p in procs if any(k in p[1].lower() for k in ("aion", "purple", "steam", "nc"))]
        if guesses:
            print("而家有呢啲似樣嘅 process：")
            for pid, pname in guesses[:20]:
                print(f"  PID {pid:<7} {process_memory_bytes(pid) / 1048576:8.1f} MB  {pname}")
        else:
            print("（而家好似冇相關 process —— 遊戲係唔係未開？要開到入登入畫面先有 L10N 資料）")
        print("提示：遊戲主程式通常叫 AION2.exe；亦可以用 --list-processes 睇全部。")
        return 0
    if len(exact) == 1:
        return exact[0][0]
    sized = [(process_memory_bytes(pid), pid, pname) for pid, pname in exact]
    sized.sort(reverse=True)
    print("同名 process 有多個，揀 working set 最大嗰個（通常係遊戲本體；另外嗰個係 launcher）：")
    for mb, pid, pname in sized:
        mark = "  <- 用呢個" if (pid, pname) == (sized[0][1], sized[0][2]) else ""
        print(f"  PID {pid:<7} {mb / 1048576:8.1f} MB  {pname}{mark}")
    return sized[0][1]


def live_module(pid: int, module_name: str) -> Tuple[int, int]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if not snap or snap == ctypes.c_void_p(-1).value:
        raise SystemExit(f"CreateToolhelp32Snapshot(module) 失敗（錯誤 {ctypes.get_last_error()}）"
                         "—— 可能係權限問題，試下用管理員身分執行")
    entry = MODULEENTRY32()
    entry.dwSize = ctypes.sizeof(MODULEENTRY32)
    found = None
    if kernel32.Module32First(snap, ctypes.byref(entry)):
        while True:
            name = entry.szModule.decode("mbcs", "replace")
            if name.lower() == module_name.lower():
                found = (entry.modBaseAddr or 0, entry.modBaseSize)
                break
            if not kernel32.Module32Next(snap, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(snap)
    if not found:
        raise SystemExit(f"process {pid} 裡面搵唔到 module {module_name}")
    return found


def read_bytes(pid: int, base: int, size: int):
    """讀一段記憶體；讀唔到回傳 None。"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess 失敗（錯誤 {ctypes.get_last_error()}）—— 試下用管理員身分執行")
    buf = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t()
    ok = kernel32.ReadProcessMemory(handle, ctypes.c_void_p(base), buf, size, ctypes.byref(read))
    kernel32.CloseHandle(handle)
    if not ok or not read.value:
        return None
    return buf.raw[:read.value]


def size_of_image(image: bytes) -> int:
    """由已讀入嘅 PE 頭拎 SizeOfImage（讀唔到 header 就回傳 0）。"""
    if len(image) < 0x1000 or image[:2] != b"MZ":
        return 0
    try:
        pe_off = struct.unpack_from("<I", image, 0x3C)[0]
        if image[pe_off:pe_off + 4] != b"PE\0\0":
            return 0
        opt = pe_off + 24
        return struct.unpack_from("<I", image, opt + 56)[0]
    except Exception:
        return 0


def read_range(pid: int, base: int, size: int, out_path: str, include_guard: bool = False) -> int:
    """由 live process 讀 [base, base+size) 寫入檔案（讀唔到嘅頁面補 0），回傳實際讀到嘅 bytes。"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        raise SystemExit(f"OpenProcess 失敗（錯誤 {ctypes.get_last_error()}）—— 試下用管理員身分執行")
    mbi = MEMORY_BASIC_INFORMATION64()
    buf = ctypes.create_string_buffer(4 << 20)
    read = ctypes.c_size_t()
    written = 0
    with open(out_path, "wb") as fh:
        address = base
        end = base + size
        while address < end and kernel32.VirtualQueryEx(
                handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            region_end = mbi.BaseAddress + mbi.RegionSize
            readable = (mbi.State == MEM_COMMIT and mbi.Protect in READABLE
                        and (include_guard or not (mbi.Protect & PAGE_GUARD)))
            while address < region_end and address < end:
                want = min(len(buf), region_end - address, end - address)
                data = None
                if readable and kernel32.ReadProcessMemory(
                        handle, ctypes.c_void_p(address), buf, want, ctypes.byref(read)) and read.value:
                    data = buf.raw[:read.value]
                    written += len(data)
                if data is None:
                    data = bytes(want)
                fh.write(data)
                address += want
    kernel32.CloseHandle(handle)
    return written


def pe_image_info(path: str) -> Tuple[int, int, int]:
    """由磁碟上嘅 exe 讀 (image base, size of image, entry RVA)。"""
    with open(path, "rb") as fh:
        data = fh.read(0x1000)
    if data[:2] != b"MZ":
        raise SystemExit(f"{path} 唔係 PE")
    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_off:pe_off + 4] != b"PE\0\0":
        raise SystemExit(f"{path} PE header 唔對")
    opt = pe_off + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    base = struct.unpack_from("<Q", data, opt + 24)[0] if magic == 0x20B else struct.unpack_from("<I", data, opt + 28)[0]
    entry = struct.unpack_from("<I", data, opt + 16)[0]
    size = struct.unpack_from("<I", data, opt + 56)[0]
    return base, size, entry


def game_exe_path(game_dir: str) -> str:
    import os

    for rel in (r"Aion2\Binaries\Win64\AION2.exe", r"Aion2\Binaries\Win64\Aion2.exe"):
        path = os.path.join(game_dir, rel)
        if os.path.exists(path):
            return path
    raise SystemExit(f"{game_dir} 裡面搵唔到 AION2.exe")


def dump_live_module(pid: int, module_name: str, out_path: str) -> Tuple[int, int]:
    base, size = live_module(pid, module_name)
    written = read_range(pid, base, size, out_path)
    return base, written


# ---------------------------------------------------------------- 輸出 / main


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="抽 module 喺記憶體嘅映像（runtime unpack）")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--dump", help="minidump 檔")
    ap.add_argument("--process", help="live process 名（遊戲主程式叫 AION2.exe）")
    ap.add_argument("--game", help="遊戲根目錄：自動搵 AION2.exe + 用磁碟 PE 嘅 base/size 讀記憶體（唔靠 module snapshot）")
    ap.add_argument("--pid", type=int, help="直接指定 PID（等同 --process）")
    ap.add_argument("--exe", help="配合 --process：用磁碟上嘅 exe 拎 image base／size（替代 module snapshot）")
    ap.add_argument("--module", help="module 名（例如 AION2.exe）；--game/--exe 模式下可省略")
    ap.add_argument("--out", help="輸出 flat image 路徑")
    ap.add_argument("--list", action="store_true", help="只列出 module（配合 --dump）")
    ap.add_argument("--list-processes", action="store_true", help="列出相關 process（aion/purple/steam/nc）")
    ap.add_argument("--all-processes", action="store_true", help="列出全部 process")
    args = ap.parse_args(argv)

    if args.list_processes or args.all_processes:
        if args.all_processes:
            procs = list_processes()
        else:
            procs = [p for p in list_processes() if any(k in p[1].lower() for k in ("aion", "purple", "steam", "nc"))]
        for pid, pname in procs:
            print(f"  PID {pid:<7} {pname}")
        if not procs:
            print("（冇相關 process）")
        return 0
    if not args.dump and not args.process and not args.pid and not args.game:
        ap.error("要提供 --dump / --game / --process（用 --list-processes 睇有咩 process）")

    if args.dump:
        md = MiniDump(args.dump)
        print(f"{args.dump}: {md.size / 1048576:.1f} MB　modules={len(md.modules)}　ranges={len(md.ranges)}")
        if args.list or not args.module:
            for m in md.modules:
                covered = sum(s for _, s, _ in md.iter_module_regions(m))
                if covered or args.list:
                    print(f"  0x{m.base:012x} 0x{m.size:<9x} 覆蓋 {covered / 1048576:7.1f} MB  {m.name}")
            return 0
        module = md.find_module(args.module)
        if module is None:
            raise SystemExit(f"搵唔到 module {args.module}")
        regions = list(md.iter_module_regions(module))
        covered = sum(s for _, s, _ in regions)
        print(f"module {module.name} base=0x{module.base:x} size=0x{module.size:x}")
        print(f"dump 內覆蓋：{covered / 1048576:.1f} MB / {module.size / 1048576:.1f} MB"
              f"（{covered * 100.0 / max(1, module.size):.1f}%）")
        if not args.out:
            raise SystemExit("要 --out 先寫出 image")
        base, written = md.dump_module(args.module, args.out)
    else:
        exe_path = args.exe or (game_exe_path(args.game) if args.game else None)
        pid = args.pid or find_pid(args.process or (os.path.basename(exe_path) if exe_path else "AION2.exe"))
        if not pid:
            return 2
        if args.list and not args.module:
            print("（live 模式 --list 需要 --module；直接用 --dump 睇 module 清單）")
            return 0
        if not args.out:
            raise SystemExit("要 --out 先寫出 image")
        if exe_path and (args.game or args.exe):
            base, size, entry = pe_image_info(exe_path)
            print(f"磁碟 PE：base=0x{base:x} size=0x{size:x}（{size / 1048576:.1f} MB）entry=0x{entry:x}")
            probe = read_bytes(pid, base, 0x1000)
            if probe and probe[:2] == b"MZ":
                inmem = size_of_image(probe) or size
                print(f"確認 {args.module or os.path.basename(exe_path)} 喺 0x{base:x}（記憶體 SizeOfImage=0x{inmem:x}）")
                print(f"由 live process 讀記憶體（PID {pid}）…")
                written = read_range(pid, base, inmem, args.out)
            else:
                print(f"0x{base:x} 讀唔到 MZ（可能 ASLR 移位或者頁面唔可讀）→ 改用 module snapshot")
                module = args.module or os.path.basename(exe_path)
                base, written = dump_live_module(pid, module, args.out)
        else:
            print(f"由 live process 讀 module：{args.module}（PID {pid}）")
            base, written = dump_live_module(pid, args.module, args.out)

    image = open(args.out, "rb").read()
    print(f"已寫出 {args.out}（{len(image)} bytes，實際有內容 {written / 1048576:.1f} MB）")

    print("完整度檢查（marker 有冇出現）：")
    ok_crypto = False
    ok_strings = False
    for name, needle in MARKERS.items():
        count = image.count(needle)
        print(f"  {name:32s} {'✓' if count else '✗'}  {count}")
        if "blake3" in name and count:
            ok_crypto = True
        if name == "ascii L10NString_" and count:
            ok_strings = True
    print()
    if ok_strings and ok_crypto:
        print("→ image 睇落完整，可以跑：")
        print(f"   python xref.py {args.out} --base 0x{base:x} --preset blake3")
        return 0
    print("→ image 唔夠完整（WER 自動 minidump 通常只包含 crash 相關頁）。")
    print("   可以改用 live process：python unpack.py --process Aion2-Win64-Shipping.exe --module AION2.exe --out AION2.unpacked.bin")
    print("   或者整完整 dump：procdump -ma Aion2-Win64-Shipping.exe aion2-full.dmp")
    return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
