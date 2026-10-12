"""翻譯記憶（TM）同官方快照嘅儲存格式：壓縮 JSON。

- ``.json.zst`` 用 Python 3.14 內建嘅 ``compression.zstd``（最快、體積最細）
- ``.json.xz`` 用標準庫 ``lzma``（任何 Python 3 都可以）
- ``.json`` 純文字

統一用 UTF-8，唔 escape 中文，方便 diff 同 review。
"""

from __future__ import annotations

import json
import os
from typing import Any


def dump(obj: Any, path: str, level: int = 10) -> None:
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if path.endswith(".zst"):
        from compression import zstd

        payload = zstd.compress(data, level=level)
    elif path.endswith(".xz"):
        import lzma

        payload = lzma.compress(data, preset=6)
    else:
        payload = data
    with open(path, "wb") as fh:
        fh.write(payload)


def load(path: str) -> Any:
    with open(path, "rb") as fh:
        payload = fh.read()
    if path.endswith(".zst"):
        from compression import zstd

        payload = zstd.decompress(payload)
    elif path.endswith(".xz"):
        import lzma

        payload = lzma.decompress(payload)
    return json.loads(payload.decode("utf-8"))


def is_cjk(text: str) -> bool:
    return any("\u3400" <= ch <= "\u9fff" or "\uf900" <= ch <= "\ufaff" for ch in text)
