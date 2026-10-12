"""AION2 L10NString.dat（v2 容器）讀寫 + 對照表解析。

容器格式（little-endian）::

    +0x00  uint32   版本 = 2
    +0x04  16 bytes 標頭 = pack("<iiii", packed, etype, aligned, raw_size) XOR header_key(seed)
    +0x14  ...      AES-256-ECB 加密本體 = 32 個 zero byte + LZ4 block + 補零至 16 對齊

解壓後（raw）是「鍵 -> 文字」對照表::

    int32    version = 1
    fstring  namespace（"AION2"）
    int32    entry_count
    entry_count × ( fstring key, fstring value )
    4 個 zero byte

`fstring`：先寫 int32 n；n == 0 空字串；n > 0 後面係 n bytes UTF-8（含 \0）；
n < 0 後面係 |n| 個 UTF-16LE code unit（含 0x0000）。

密鑰（KEYS）唔會跟 repo 一齊發佈：key = 32 bytes AES key，用 seed 做索引，
seed = blake3("L10NString_<locale>")[:8] 解成 u64。
"""

from __future__ import annotations

import io
import json
import os
import struct
from typing import Dict, Iterable, List, Tuple

import blake3
import lz4.block
from Crypto.Cipher import AES

HEADER_SIZE = 20

# 由遊戲常數推導出來的 header keystream root（同官方一致，唔需要密鑰表）
HEADER_ROOT = struct.unpack("<Q", blake3.blake3(struct.pack("<Q", 0xCD02190910CE83F6)).digest()[:8])[0]


def h64(data: bytes) -> int:
    return struct.unpack("<Q", blake3.blake3(data).digest()[:8])[0]


def seed_for(locale: str = "en-US") -> int:
    return h64(f"L10NString_{locale}".encode())


def header_key(seed: int, htype: int = 3) -> bytes:
    return blake3.blake3(struct.pack("<QQiI", HEADER_ROOT, seed, htype, 0)).digest()


def xor(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


# ---------------------------------------------------------------- 密鑰表


def load_keys(path: str | None = None) -> Dict[int, bytes]:
    """讀 keys.json（{seed: hex}）。預設次序：參數 -> $AION2_KEYS -> tools/langpack/keys.json"""
    candidates = [path] if path else []
    env = os.environ.get("AION2_KEYS")
    if env:
        candidates.append(env)
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "keys.json"))
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            with open(candidate, "r", encoding="utf-8") as fh:
                return {int(k): bytes.fromhex(v) for k, v in json.load(fh).items()}
    return {}


def save_keys(keys: Dict[int, bytes], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({str(k): v.hex() for k, v in keys.items()}, fh, indent=0)
        fh.write("\n")


class KeyMissing(RuntimeError):
    """密鑰表裡面冇（或者已經過期）對應語系的 AES key。"""


# ---------------------------------------------------------------- 容器


def header(dat: bytes, locale: str = "en-US") -> Tuple[int, int, int, int]:
    """唔需要密鑰都可以讀出標頭四個欄位：packed, etype, aligned, raw_size。"""
    assert struct.unpack_from("<I", dat, 0)[0] == 2, "唔係 v2 容器"
    packed, etype, aligned, raw = struct.unpack("<iiii", xor(dat[4:20], header_key(seed_for(locale))))
    return packed, etype, aligned, raw


def decrypt(dat: bytes, locale: str = "en-US", keys: Dict[int, bytes] | None = None) -> bytes:
    """解密 + 解壓，回傳 raw 對照表。"""
    keys = keys if keys is not None else load_keys()
    seed = seed_for(locale)
    packed, etype, aligned, raw_size = header(dat, locale)
    assert etype == 2, f"未知嘅加密類型 {etype}"
    assert aligned == len(dat) - HEADER_SIZE, f"本體長度唔對：{aligned} vs {len(dat) - HEADER_SIZE}"
    key = keys.get(seed)
    if key is None:
        raise KeyMissing(
            f"keys.json 冇 L10NString_{locale} 嘅 key（seed={seed}）。"
            " 官方更新後可能換咗 key，需要重新取得（見 tools/langpack/README.md）。"
        )
    body = AES.new(key, AES.MODE_ECB).decrypt(dat[HEADER_SIZE:HEADER_SIZE + aligned])
    if body[:32] != bytes(32):
        raise KeyMissing(
            f"keys.json 嘅 L10NString_{locale} key 已經過期（解密結果唔符合格式）。"
            " 官方每次更新都可能換 key，需要重新取得（見 tools/langpack/README.md）。"
        )
    raw = lz4.block.decompress(body[0x20:0x20 + packed], uncompressed_size=raw_size)
    if len(raw) != raw_size:
        raise RuntimeError("LZ4 解壓長度唔對")
    return raw


def encrypt(raw: bytes, locale: str = "en-US", keys: Dict[int, bytes] | None = None) -> bytes:
    """壓縮 + 加密，回傳完整 v2 dat（可以直接寫入遊戲目錄）。"""
    keys = keys if keys is not None else load_keys()
    seed = seed_for(locale)
    key = keys.get(seed)
    if key is None:
        raise KeyMissing(f"keys.json 冇 L10NString_{locale} 嘅 key（seed={seed}）")
    packed = lz4.block.compress(raw, mode="high_compression", store_size=False)
    body = bytes(0x20) + packed
    body += bytes(-len(body) % 16)
    hdr = xor(struct.pack("<iiii", len(packed), 2, len(body), len(raw)), header_key(seed))
    return struct.pack("<I", 2) + hdr + AES.new(key, AES.MODE_ECB).encrypt(body)


def check_key(dat: bytes, locale: str = "en-US", keys: Dict[int, bytes] | None = None) -> bool:
    """檢查密鑰表係唔係仲可以解開呢個 dat（True = OK）。"""
    try:
        decrypt(dat, locale, keys)
        return True
    except (KeyMissing, AssertionError):
        return False


# ---------------------------------------------------------------- 對照表


def rd_fstring(r: io.BytesIO) -> str:
    n = struct.unpack("<i", r.read(4))[0]
    if n == 0:
        return ""
    if n > 0:
        return r.read(n)[:-1].decode("utf-8")
    return r.read(-n * 2)[:-2].decode("utf-16le")


def wr_fstring(s: str) -> bytes:
    if s == "":
        return struct.pack("<i", 0)
    if s.isascii():
        b = s.encode("ascii") + b"\0"
        return struct.pack("<i", len(b)) + b
    b = s.encode("utf-16le") + b"\0\0"
    return struct.pack("<i", -(len(b) // 2)) + b


def parse(raw: bytes) -> Tuple[str, List[Tuple[str, str]]]:
    r = io.BytesIO(raw)
    version = struct.unpack("<i", r.read(4))[0]
    assert version == 1, f"raw version = {version}"
    namespace = rd_fstring(r)
    count = struct.unpack("<i", r.read(4))[0]
    entries = [(rd_fstring(r), rd_fstring(r)) for _ in range(count)]
    trailer = r.read()
    assert trailer == bytes(4), "raw 結尾唔係 4 個 zero byte"
    return namespace, entries


def build(namespace: str, entries: Iterable[Tuple[str, str]]) -> bytes:
    out = [struct.pack("<i", 1), wr_fstring(namespace)]
    entries = list(entries)
    out.append(struct.pack("<i", len(entries)))
    for key, value in entries:
        out.append(wr_fstring(key))
        out.append(wr_fstring(value))
    out.append(bytes(4))
    return b"".join(out)
