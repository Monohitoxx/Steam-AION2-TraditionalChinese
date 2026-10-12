"""查看 minidump：module 清單、記憶體範圍、搵常數。

用法::

    python mdinfo.py aion2.dmp                     # 列 module + 範圍
    python mdinfo.py aion2.dmp --find AION2.exe    # 只列某 module
    python mdinfo.py aion2.dmp --grep f683ce10091902cd   # 喺 dump 搵 hex
"""

from __future__ import annotations

import argparse
import sys
from typing import List

from minidump import MiniDump


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="minidump 資訊 / 常數搜尋")
    ap.add_argument("dump")
    ap.add_argument("--find", help="只顯示名稱含呢個字串嘅 module")
    ap.add_argument("--grep", help="喺 dump 檔案搵 hex pattern（例如 f683ce10091902cd）")
    ap.add_argument("--limit", type=int, default=60)
    args = ap.parse_args(argv)

    md = MiniDump(args.dump)
    print(f"{args.dump}: {md.size / 1048576:.1f} MB　modules={len(md.modules)}　memory ranges={len(md.ranges)}")
    total = sum(s for _, s, _ in md.ranges)
    print(f"dump 內記憶體總量：{total / 1048576:.1f} MB")

    for m in md.modules:
        if args.find and args.find.lower() not in m.name.lower():
            continue
        regions = list(md.iter_module_regions(m))
        covered = sum(s for _, s, _ in regions)
        print(f"  0x{m.base:012x} size=0x{m.size:<9x} 覆蓋={covered / 1048576:7.1f} MB  {m.name}")

    if args.grep:
        needle = bytes.fromhex(args.grep)
        hits = 0
        for start, size, off in md.ranges:
            md.fh.seek(off)
            remaining = size
            buf = b""
            base = start
            # 逐段讀，記住 pattern 可能跨 buffer
            CHUNK = 16 << 20
            pos = 0
            while pos < size:
                data = md.fh.read(min(CHUNK, size - pos))
                if not data:
                    break
                hay = buf + data
                base_va = base + pos - len(buf)
                i = hay.find(needle)
                while i != -1:
                    hits += 1
                    if hits <= args.limit:
                        print(f"  hit @ VA 0x{base_va + i:x}  (region 0x{start:x}+0x{size:x})")
                    i = hay.find(needle, i + 1)
                buf = hay[-len(needle):]
                pos += len(data)
        print(f"  合共 {hits} 個符合")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
