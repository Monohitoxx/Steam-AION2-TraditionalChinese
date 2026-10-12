"""檢查 keys.json 係唔係仲可以解開官方語言包（官方每次更新都可能換 AES key）。

用法::

    python keycheck.py --game "D:\\SteamLibrary\\steamapps\\common\\AION2"
    python keycheck.py official-en-US.dat --locale en-US
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List

import l10n


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="檢查 L10NString.dat 嘅 AES key 係唔係有效")
    ap.add_argument("dat", nargs="?", help="官方 dat（可選，冇就用 --game 抽）")
    ap.add_argument("--game", help="遊戲根目錄")
    ap.add_argument("--locale", default="en-US")
    ap.add_argument("--keys", help="keys.json 路徑")
    args = ap.parse_args(argv)

    keys = l10n.load_keys(args.keys)
    seed = l10n.seed_for(args.locale)
    print(f"語系 {args.locale}　seed {seed}　keys.json {len(keys)} 條")

    dat_path = args.dat
    if not dat_path and args.game:
        import pak_extract

        dat_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "official.tmp.dat")
        with open(dat_path, "wb") as fh:
            fh.write(pak_extract.extract_dat(pak_extract.find_pak(args.game)))
        print(f"由 pak 抽出官方 dat -> {dat_path}")
    if not dat_path:
        ap.error("要提供 dat 或者 --game")

    dat = open(dat_path, "rb").read()
    packed, etype, aligned, raw_size = l10n.header(dat, args.locale)
    print(f"官方 dat {len(dat)} bytes：packed={packed} etype={etype} aligned={aligned} raw={raw_size}")

    key = keys.get(seed)
    if key is None:
        print("結果：keys.json **冇** 呢個語系嘅 key —— 需要新 key")
        return 2
    try:
        raw = l10n.decrypt(dat, args.locale, keys)
    except l10n.KeyMissing as exc:
        print(f"結果：key 已過期 —— {exc}")
        print(f"      現有 key {key.hex()}")
        return 3
    ns, entries = l10n.parse(raw)
    print(f"結果：key 有效 ✓　namespace={ns}　{len(entries)} 條")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
