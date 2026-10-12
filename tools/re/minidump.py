"""極簡 Windows Minidump（.dmp）解析：module 清單 + 記憶體範圍 → VA 對映。

只依賴標準庫，方便喺任何 Python 3 上面行。

用法::

    from minidump import MiniDump
    md = MiniDump(r"aion2.dmp")
    for m in md.modules:
        print(m.name, hex(m.base), hex(m.size))
    data = md.read_va(0x140001000, 64)      # 由 VA 讀記憶體
    for start, size, off in md.ranges: ...  # VA -> 檔案 offset
"""

from __future__ import annotations

import struct
from typing import Dict, Iterator, List, Optional, Tuple

MINIDUMP_SIGNATURE = 0x504D444D  # 'MDMP'
MODULE_LIST_STREAM = 4
MEMORY_LIST_STREAM = 5
MEMORY64_LIST_STREAM = 9


class Module:
    __slots__ = ("base", "size", "name", "timestamp")

    def __init__(self, base: int, size: int, name: str, timestamp: int):
        self.base = base
        self.size = size
        self.name = name
        self.timestamp = timestamp

    def __repr__(self) -> str:
        return f"<Module {self.name} base=0x{self.base:x} size=0x{self.size:x}>"


class MiniDump:
    def __init__(self, path: str):
        self.path = path
        self.fh = open(path, "rb")
        self.size = self._file_size()
        self.streams: Dict[int, Tuple[int, int]] = {}
        self.modules: List[Module] = []
        self.ranges: List[Tuple[int, int, int]] = []  # (VA, size, file offset)
        self._parse()

    def _file_size(self) -> int:
        import os

        return os.path.getsize(self.path)

    def _read(self, off: int, size: int) -> bytes:
        self.fh.seek(off)
        return self.fh.read(size)

    def _parse(self) -> None:
        head = self._read(0, 32)
        signature, version, num_streams, dir_rva = struct.unpack_from("<IIII", head, 0)
        if signature != MINIDUMP_SIGNATURE:
            raise ValueError(f"唔係 minidump（signature=0x{signature:x}）")
        for i in range(num_streams):
            stype, size, rva = struct.unpack_from("<III", self._read(dir_rva + i * 12, 12), 0)
            self.streams[stype] = (rva, size)
        if MODULE_LIST_STREAM in self.streams:
            self._parse_modules(*self.streams[MODULE_LIST_STREAM])
        if MEMORY64_LIST_STREAM in self.streams:
            self._parse_memory64(*self.streams[MEMORY64_LIST_STREAM])
        elif MEMORY_LIST_STREAM in self.streams:
            self._parse_memory32(*self.streams[MEMORY_LIST_STREAM])
        self.ranges.sort()

    def _parse_modules(self, rva: int, size: int) -> None:
        count = struct.unpack_from("<I", self._read(rva, 4), 0)[0]
        off = rva + 4
        for _ in range(count):
            base, isize, checksum, timestamp, name_rva = struct.unpack_from("<QIIII", self._read(off, 24), 0)
            name = self._read_string(name_rva)
            self.modules.append(Module(base, isize, name, timestamp))
            off += 108  # sizeof(MINIDUMP_MODULE)
        self.modules.sort(key=lambda m: m.base)

    def _read_string(self, rva: int) -> str:
        length = struct.unpack_from("<I", self._read(rva, 4), 0)[0]
        raw = self._read(rva + 4, length)
        return raw.decode("utf-16le", "replace")

    def _parse_memory64(self, rva: int, size: int) -> None:
        count, base_rva = struct.unpack_from("<QQ", self._read(rva, 16), 0)
        off = rva + 16
        data_off = base_rva
        for _ in range(count):
            start, dsize = struct.unpack_from("<QQ", self._read(off, 16), 0)
            self.ranges.append((start, dsize, data_off))
            data_off += dsize
            off += 16

    def _parse_memory32(self, rva: int, size: int) -> None:
        count = struct.unpack_from("<I", self._read(rva, 4), 0)[0]
        off = rva + 4
        for _ in range(count):
            start, dsize, data_rva = struct.unpack_from("<QII", self._read(off, 16), 0)
            self.ranges.append((start, dsize, data_rva))
            off += 16

    # ---------------------------------------------------------------- 讀取

    def read_va(self, va: int, size: int) -> Optional[bytes]:
        """由 VA 讀 size bytes；跨唔到範圍就回傳 None。"""
        for start, dsize, off in self.ranges:
            if start <= va and va + size <= start + dsize:
                return self._read(off + (va - start), size)
        return None

    def find_module(self, name: str) -> Optional[Module]:
        needle = name.lower()
        for m in self.modules:
            if m.name.lower().endswith(needle):
                return m
        return None

    def iter_module_regions(self, module: Module) -> Iterator[Tuple[int, int, int]]:
        """回傳屬於某個 module 嘅 (VA, size, file offset) 片段。"""
        end = module.base + module.size
        for start, dsize, off in self.ranges:
            if start >= module.base and start + dsize <= end:
                yield start, dsize, off
            elif start < end and start + dsize > module.base:
                # 有重疊：裁剪
                lo = max(start, module.base)
                hi = min(start + dsize, end)
                yield lo, hi - lo, off + (lo - start)

    def dump_module(self, name: str, out_path: str, pad_to_size: bool = True) -> Tuple[int, int]:
        """把 module 喺記憶體嘅內容（解密後）寫成 flat image，回傳 (base, 寫入 bytes)。"""
        module = self.find_module(name)
        if module is None:
            raise SystemExit(f"dump 裡面搵唔到 module {name}")
        buf = bytearray(module.size if pad_to_size else 0)
        written = 0
        for va, size, off in self.iter_module_regions(module):
            data = self._read(off, size)
            rel = va - module.base
            if rel < 0:
                continue
            if rel + size > len(buf):
                buf.extend(bytes(rel + size - len(buf)))
            buf[rel:rel + size] = data
            written += size
        with open(out_path, "wb") as fh:
            fh.write(buf)
        return module.base, written
