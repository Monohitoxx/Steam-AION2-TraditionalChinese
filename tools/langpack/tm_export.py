"""由一個 dat（舊語言包或者任何同語系 dat）匯出「翻譯記憶」TM。

TM 係純文字（壓縮 JSON），唔受官方換 key 影響，所以係 pipeline 嘅長期資產：
官方更新時，就算舊 dat 已經解唔開，只要留低 TM 就可以繼續同步。

用法::

    python tm_export.py langpack/L10NString.dat tools/langpack/tm/zh-TW.json.zst
"""

from __future__ import annotations

import argparse
import sys
from typing import List

import l10n
import store


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="由 dat 匯出純文字翻譯記憶")
    ap.add_argument("dat", help="來源 dat（例如 langpack/L10NString.dat）")
    ap.add_argument("out", nargs="?", default="tm/zh-TW.json.zst", help="輸出 TM 路徑")
    ap.add_argument("--locale", default="en-US", help="dat 屬於邊個語系 key（預設 en-US）")
    ap.add_argument("--keys", help="keys.json 路徑（預設 $AION2_KEYS 或同目錄 keys.json）")
    ap.add_argument("--only-translated", action="store_true", help="只匯出含中文嘅條目")
    args = ap.parse_args(argv)

    keys = l10n.load_keys(args.keys)
    raw = l10n.decrypt(open(args.dat, "rb").read(), args.locale, keys)
    namespace, entries = l10n.parse(raw)
    if args.only_translated:
        entries = [(k, v) for k, v in entries if store.is_cjk(v)]
    store.dump({"namespace": namespace, "locale": "zh-TW", "entries": entries}, args.out)
    print(f"匯出 {len(entries)} 條 -> {args.out}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
