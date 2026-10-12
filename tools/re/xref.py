"""RIP-relative xref 掃描器：喺（runtime dump 出嚟嘅）image 裡面搵常數，再搵邊度引用佢。

x86-64 用 RIP-relative 定址，指令格式係 `opcode modrm disp32`，目標位址 =
（指令結束位址，即 disp32 之後）+ disp32。所以只要假設「任何 4 bytes 都可能係 disp32」，
就可以反推佢指向邊個 VA，再同目標常數比對；加埋對前綴 bytes 嘅合理性檢查減少假陽性。

用法::

    python xref.py AION2.unpacked.bin --base 0x140000000 --preset blake3
    python xref.py AION2.unpacked.bin --base 0x140000000 --find-hex f683ce10091902cd
    python xref.py AION2.unpacked.bin --base 0x140000000 --find-ascii L10NString_
"""

from __future__ import annotations

import argparse
import struct
import sys
from typing import Dict, List, Optional, Sequence, Tuple

# BLAKE3 / SHA-256 IV（64-bit 版同 32-bit 版都會搵）＋ 已知 root 常數
BLAKE3_IV64 = [0x6A09E667F3BCC908, 0xBB67AE8584CAA73B, 0x3C6EF372FE94F82B, 0xA54FF53A5F1D36F1,
               0x510E527FADE682D1, 0x9B05688C2B3E6C1F, 0x1F83D9ABFB41BD6B, 0x5BE0CD19137E2179]
BLAKE3_IV32 = [0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A, 0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19]
PRESETS = {
    "blake3": {
        "blake3 IV[0..7] (64-bit 連續)": b"".join(struct.pack("<Q", v) for v in BLAKE3_IV64),
        "blake3 IV[0..7] (32-bit 連續)": b"".join(struct.pack("<I", v) for v in BLAKE3_IV32),
        "rootConst 0xCD02190910CE83F6": struct.pack("<Q", 0xCD02190910CE83F6),
    },
    "aion2": {
        "rootConst 0xCD02190910CE83F6": struct.pack("<Q", 0xCD02190910CE83F6),
        "pakKey": bytes.fromhex("06038EF544B6007614F8574F1B7C2A3F0D565F74CDCC1B366B4EA1A17B97CBFF"),
    },
}

# 可能係 RIP-relative 嘅 ModRM（mod=00, rm=101）
RIP_MODRM = {0x05, 0x0D, 0x15, 0x1D, 0x25, 0x2D, 0x35, 0x3D}
REX = set(range(0x40, 0x50))
OPCODES = {0x8B, 0x8D, 0x89, 0x3B, 0x39, 0x03, 0x2B, 0x33, 0x0B, 0x23, 0x85, 0x8A, 0x88,
           0xC7, 0xC6, 0xFF, 0x8F, 0x0F}  # 0x0F 涵蓋 movzx/movsx 等兩 byte opcode


def find_all(hay: bytes, needle: bytes) -> List[int]:
    out, i = [], hay.find(needle)
    while i != -1:
        out.append(i)
        i = hay.find(needle, i + 1)
    return out


TWOBYTE = {0xB6, 0xB7, 0xBE, 0xBF, 0x10, 0x11, 0x28, 0x29, 0x6F, 0x7F, 0x6E, 0x7E, 0xD6, 0xEF, 0x57, 0x7F}


def plausible_prefix(image: bytes, disp_off: int) -> Optional[int]:
    """disp_off 係 disp32 起點；回傳指令起點（如果睇落似 RIP-relative 指令）。

    由最長嘅可能前綴（VEX/REX+0F）試到最短，揀最具體嘅一個，減少報錯位址。
    """
    if disp_off < 2 or image[disp_off - 1] not in RIP_MODRM:
        return None
    for start in range(max(0, disp_off - 6), disp_off - 1):
        b = image[start]
        n = disp_off - 1 - start  # opcode 同 ModRM 之間仲有幾多 bytes
        if n == 4:
            if b == 0xC4:  # VEX3
                return start
        elif n == 3:
            if b in (0x66, 0xF2, 0xF3) and image[start + 1] == 0x0F and image[start + 2] in TWOBYTE:
                return start
            if b in REX and image[start + 1] == 0x0F and image[start + 2] in TWOBYTE:
                return start
            if b == 0xC5:  # VEX2
                return start
        elif n == 2:
            if b == 0x0F and image[start + 1] in TWOBYTE:
                return start
            if b in REX and image[start + 1] in OPCODES:
                return start
        elif n == 1:
            if b in OPCODES:
                return start
    return None


def resolved_target(image: bytes, base: int, disp_off: int) -> int:
    disp = struct.unpack_from("<i", image, disp_off)[0]
    return base + disp_off + 4 + disp


def scan_xrefs(image: bytes, base: int, targets: Dict[str, int],
               span: int = 0) -> Dict[str, List[Tuple[int, int]]]:
    """搵 RIP-relative 引用。span > 0 時，指向目標 ±span 之內都當係（例如引用表格中間）。"""
    hits: Dict[str, List[Tuple[int, int]]] = {k: [] for k in targets}
    ranges = [(va - span, va + span, name) for name, va in targets.items()]
    n = len(image)
    for i in range(0, n - 4):
        if image[i + 3] not in (0x00, 0x01, 0x02, 0x03, 0x7F, 0xFF):
            # disp32 高位通常係 0x00（同一 module 內）或者 0xFF（負向）
            continue
        va = resolved_target(image, base, i)
        name = None
        for lo, hi, candidate in ranges:
            if lo <= va <= hi:
                name = candidate
                break
        if name is None:
            continue
        start = plausible_prefix(image, i)
        if start is None:
            continue
        hits[name].append((start, i))
    return hits


def hexdump(data: bytes, base: int, width: int = 16) -> None:
    for i in range(0, len(data), width):
        row = data[i:i + width]
        print(f"    {base + i:012x}  " + row.hex(" "))


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RIP-relative xref 掃描（BLAKE3 常數 / root 常數）")
    ap.add_argument("image", help="unpack 出嚟嘅 image（flat，由 module base 開始）")
    ap.add_argument("--base", default="0x140000000", help="image 對應嘅 VA base")
    ap.add_argument("--preset", choices=sorted(PRESETS), help="用內建常數組")
    ap.add_argument("--find-hex", action="append", default=[], help="額外搵 hex pattern（可多次）")
    ap.add_argument("--find-ascii", action="append", default=[], help="額外搵 ASCII 字串（可多次）")
    ap.add_argument("--context", type=int, default=48, help="每個 xref 前後顯示幾多 bytes")
    ap.add_argument("--max", type=int, default=40, help="每個常數最多顯示幾個 xref")
    ap.add_argument("--span", type=int, default=0, help="指向目標 ±span bytes 之內都當係 xref")
    args = ap.parse_args(argv)

    base = int(args.base, 0)
    image = open(args.image, "rb").read()
    print(f"image {args.image}：{len(image)} bytes（{len(image) / 1048576:.1f} MB），base 0x{base:x}")

    patterns: Dict[str, bytes] = {}
    if args.preset:
        patterns.update(PRESETS[args.preset])
    for i, h in enumerate(args.find_hex):
        patterns[f"hex[{i}] {h}"] = bytes.fromhex(h)
    for i, s in enumerate(args.find_ascii):
        patterns[f"ascii[{i}] {s}"] = s.encode()

    targets: Dict[str, int] = {}
    for name, needle in patterns.items():
        offs = find_all(image, needle)
        print(f"\n=== {name}：{len(offs)} 個位置 ===")
        for off in offs[:8]:
            print(f"    VA 0x{base + off:x}  (offset 0x{off:x})")
            if len(offs) <= 8:
                targets[f"{name}@0x{off:x}"] = base + off

    if not targets:
        print("\n（冇任何可追蹤嘅常數位置；試下 --find-hex / --find-ascii）")
        return 1

    print(f"\n=== 掃描 {len(targets)} 個目標嘅 RIP-relative xref（span={args.span}）===")
    hits = scan_xrefs(image, base, targets, args.span)
    total = 0
    for name, sites in hits.items():
        total += len(sites)
        print(f"\n--- {name}：{len(sites)} 個 xref ---")
        for start, disp_off in sites[:args.max]:
            print(f"  指令 @0x{base + start:x} (RVA 0x{start:x})")
            lo = max(0, start - args.context)
            hexdump(image[lo:min(len(image), start + args.context)], base + lo)
    print(f"\n合共 {total} 個 xref")
    return 0 if total else 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
