"""由遊戲 pak 抽出官方 en-US L10NString.dat。

UE Pak（version 11）內部嘅 L10NString.dat 係逐塊（默認 64 KiB）Oodle 壓縮，
所以要：讀 pak entry -> 逐塊 ooz.decompress -> 拼返成 v2 容器 dat。
2026-10-14 新版亦支援未壓縮、AES-256-ECB 加密嘅 entry；pak key 由本機提供。

用法::

    python pak_extract.py "<AION2>\\Aion2\\Content\\Paks\\L10N\\Text\\en-US\\pakchunk502000-Windows_0_P.pak" out.dat
    python pak_extract.py --find-game D:\\SteamLibrary\\steamapps\\common\\AION2 out.dat
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
from typing import List, Tuple

import ooz
from Crypto.Cipher import AES

PAK_MAGIC = 0x5A6F12E1
PAK_VERSION = 11
ENTRY_NAME = "L10NString.dat"
DEFAULT_PAK = r"Aion2\Content\Paks\L10N\Text\en-US\pakchunk502000-Windows_0_P.pak"


def load_pak_key() -> bytes:
    """Pak key stays local, separate from the L10N container keys."""
    value = os.environ.get("AION2_PAK_KEY")
    if not value:
        path = os.environ.get("AION2_PAK_KEYS") or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "pak-keys.json")
        if not os.path.exists(path):
            raise RuntimeError("新版 pak 需要外層密鑰：設定 AION2_PAK_KEY 或本機 pak-keys.json")
        with open(path, encoding="utf-8") as fh:
            value = json.load(fh)["default"]
    key = bytes.fromhex(value)
    if len(key) != 32:
        raise RuntimeError("pak key 必須係 32 bytes")
    return key


class PakEntry:
    def __init__(self, data: bytes, offset: int = 0):
        self.offset, self.size, self.uncompressed, self.method = struct.unpack_from("<qqqi", data, offset)
        if self.method == 0:
            # Uncompressed FPakEntry: hash, flags byte, compression block size.
            self.flags = data[offset + 48]
            self.payload_start = offset + 53
            self.blocks = 0
            self.ends = []
            return
        self.blocks = struct.unpack_from("<i", data, offset + 48)[0]
        self.payload_start = struct.unpack_from("<q", data, offset + 52)[0]
        # 每個 block 嘅壓縮結束位置：16-byte 條目，只用頭 8 bytes（已對 7 個語系 pak 驗證）
        self.ends = [struct.unpack_from("<Q", data, offset + 60 + 16 * i)[0] for i in range(self.blocks)]


def read_entry(data: bytes, name: str = ENTRY_NAME) -> PakEntry:
    if struct.unpack_from("<I", data, len(data) - 221 + 17)[0] != PAK_MAGIC:
        raise RuntimeError("唔係 UE pak（magic 唔對）")
    version = struct.unpack_from("<I", data, len(data) - 221 + 21)[0]
    if version != PAK_VERSION:
        raise RuntimeError(f"未支援嘅 pak version {version}（現時支援 {PAK_VERSION}）")
    # 只有一個檔案嘅 L10N pak：entry 一定由 0 開始
    entry = PakEntry(data, 0)
    return entry


def extract_dat(pak_path: str, block_size: int = 65536) -> bytes:
    with open(pak_path, "rb") as fh:
        data = fh.read()
    entry = read_entry(data)
    if entry.method == 0:
        encrypted = bool(entry.flags & 1)
        stored_size = (entry.size + 15) // 16 * 16 if encrypted else entry.size
        payload = data[entry.payload_start:entry.payload_start + stored_size]
        if entry.size != entry.uncompressed or len(payload) != stored_size:
            raise RuntimeError("未壓縮 pak entry 長度唔一致")
        # UE hashes the stored bytes, excluding AES alignment padding.
        if hashlib.sha1(payload[:entry.size]).digest() != data[28:48]:
            raise RuntimeError("未壓縮 pak entry SHA-1 唔一致")
        out = AES.new(load_pak_key(), AES.MODE_ECB).decrypt(payload) if encrypted else payload
        out = out[:entry.uncompressed]
        if out[:4] != struct.pack("<I", 2):
            raise RuntimeError("抽出嘅資料唔係 v2 L10N 容器，請檢查 pak key")
        return out
    if entry.ends[-1] - entry.payload_start != entry.size:
        raise RuntimeError("pak block table 同 entry 大小唔一致")
    out = bytearray()
    for i in range(entry.blocks):
        start = entry.payload_start if i == 0 else entry.ends[i - 1]
        end = entry.ends[i]
        want = min(block_size, entry.uncompressed - len(out))
        block = ooz.decompress(data[start:end], want)
        if block is None or len(block) != want:
            raise RuntimeError(f"block {i} 解壓失敗（{start}..{end}）")
        out += block
    if len(out) != entry.uncompressed:
        raise RuntimeError("拼出嚟嘅長度同 pak entry 唔一致")
    return bytes(out)


def find_pak(game_dir: str) -> str:
    path = os.path.join(game_dir, DEFAULT_PAK)
    if not os.path.exists(path):
        raise SystemExit(f"搵唔到 {path}")
    return path


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="由 AION2 官方 pak 抽出 L10NString.dat")
    ap.add_argument("pak", nargs="?", help="pakchunk502000-Windows_0_P.pak 路徑")
    ap.add_argument("--find-game", metavar="DIR", help="由遊戲根目錄自動搵 pak")
    ap.add_argument("--out", default="official-en-US.dat", help="輸出 dat 路徑")
    args = ap.parse_args(argv)

    pak = find_pak(args.find_game) if args.find_game else args.pak
    if not pak:
        ap.error("要提供 pak 路徑或者 --find-game")
    dat = extract_dat(pak)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "wb") as fh:
        fh.write(dat)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import l10n

    packed, etype, aligned, raw = l10n.header(dat)
    print(f"抽出 {len(dat)} bytes -> {args.out}")
    print(f"  packed={packed} etype={etype} aligned={aligned} raw={raw}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
