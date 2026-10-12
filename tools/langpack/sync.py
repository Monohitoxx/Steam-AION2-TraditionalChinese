"""AION2 官方語言包更新 -> 繁體中文語言包同步 pipeline。

做嘅事：

1. 攞官方最新 en-US 對照表（``--game`` 自動由 pak 抽，或者 ``--official-dat``／``--official-json``）
2. 同上次嘅官方快照（``--snapshot``）比較，搵出 **新增 / 英文改動 / 已移除** 嘅鍵
3. 用翻譯記憶 TM（``--tm``，純文字，唔受官方換 key 影響）疊返我哋已有嘅譯文
4. 新鍵如果有簡體來源（``--chs``）就 OpenCC s2tw + 詞彙修正，冇就用英文並列入待翻譯清單
5. 輸出：新 ``langpack/L10NString.dat``（重新加密）、更新後嘅 TM、新嘅官方快照、報告

例::

    # 官方更新之後
    python sync.py --game "D:\\SteamLibrary\\steamapps\\common\\AION2" --chs chs.dat --build

    # 冇遊戲目錄時，用已抽出嘅 dat
    python sync.py --official-dat official-en-US.dat --dry-run
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import shutil
import subprocess
import sys
from typing import Dict, List, Sequence, Tuple

import l10n
import store

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

# 簡體 -> 台灣繁體：OpenCC s2tw 之後仍然會錯嘅常見字（只影響 --chs 來源）
S2TW_FIXES: Sequence[Tuple[str, str]] = (
    ("揹包", "背包"), ("揹", "背"),
    ("臺", "台"), ("制作", "製作"), ("自制", "自製"), ("佈", "布"), ("週圍", "周圍"),
    ("幹淨", "乾淨"), ("幹擾", "干擾"), ("幹脆", "乾脆"), ("幹涸", "乾涸"),
    ("永恒", "永恆"), ("伙伴", "夥伴"), ("團伙", "團夥"), ("瞭解", "了解"),
    ("雲芝", "雲芝"), ("遊標", "游標"), ("準確", "準確"),
)


def s2tw(text: str) -> str:
    try:
        import opencc

        global _CC
        try:
            _CC
        except NameError:
            _CC = opencc.OpenCC("s2tw")
        text = _CC.convert(text)
    except Exception:
        pass
    for src, dst in S2TW_FIXES:
        text = text.replace(src, dst)
    return text


def load_pairs(path: str) -> Tuple[str, List[Tuple[str, str]]]:
    obj = store.load(path)
    if isinstance(obj, dict) and "entries" in obj:
        return obj.get("namespace", "AION2"), [(k, v) for k, v in obj["entries"]]
    raise SystemExit(f"{path} 格式唔啱（要 {{'namespace':..., 'entries': [[key, value], ...]}}）")


def load_official(args) -> Tuple[str, List[Tuple[str, str]], str]:
    """回傳 (namespace, entries, 來源說明)"""
    if args.official_json:
        ns, entries = load_pairs(args.official_json)
        return ns, entries, f"plaintext {args.official_json}"
    dat = args.official_dat
    if not dat and args.game:
        import pak_extract

        pak = pak_extract.find_pak(args.game)
        dat = os.path.join(args.report_dir, "official-en-US.dat")
        os.makedirs(args.report_dir, exist_ok=True)
        with open(dat, "wb") as fh:
            fh.write(pak_extract.extract_dat(pak))
        print(f"由 pak 抽出官方 dat：{pak}\n  -> {dat}")
    if not dat:
        raise SystemExit("要提供 --game / --official-dat / --official-json 其中一個")
    raw = l10n.decrypt(open(dat, "rb").read(), args.locale, args.keys)
    ns, entries = l10n.parse(raw)
    return ns, entries, dat


def write_reports(report_dir: str, stamp: str, official: Dict[str, str], current: Dict[str, str],
                  new_keys: List[str], changed: List[str], removed: List[str], fuzzy: List[str],
                  to_translate: List[str], tm: Dict[str, str], source: str) -> str:
    os.makedirs(report_dir, exist_ok=True)
    base = os.path.join(report_dir, stamp)

    def dump_tsv(path: str, keys: Sequence[str], note: Dict[str, str] | None = None) -> None:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write("key\tofficial\tcurrent\tnote\n")
            for k in keys:
                note_val = (note or {}).get(k, "")
                fh.write(f"{k}\t{official.get(k, '')}\t{current.get(k, '')}\t{note_val}\n")

    dump_tsv(base + "-new.tsv", new_keys)
    dump_tsv(base + "-changed.tsv", changed, {k: "英文改動，譯文需覆核" for k in fuzzy})
    dump_tsv(base + "-removed.tsv", removed)
    dump_tsv(base + "-to-translate.tsv", to_translate)

    lines = [
        f"# 語言包同步報告 {stamp}",
        "",
        f"- 官方來源：`{source}`",
        f"- 官方條目：{len(official)}",
        f"- 新增：{len(new_keys)}　英文改動：{len(changed)}（其中 {len(fuzzy)} 條有舊譯文需覆核）　已移除：{len(removed)}",
        f"- 待翻譯（仲係英文）：{len(to_translate)}",
        f"- 本包條目：{len(current)}",
        "",
    ]
    for title, keys in (("新增條目", new_keys), ("英文改動", changed), ("已移除", removed), ("待翻譯（頭 200 條）", to_translate[:200])):
        lines.append(f"## {title}（{len(keys)}）")
        lines.append("")
        if not keys:
            lines += ["（無）", ""]
            continue
        lines += ["| key | 官方英文 | 現時譯文 |", "|---|---|---|"]
        for k in keys[:200]:
            official_text = official.get(k, "").replace("|", "\\|")
            current_text = current.get(k, "").replace("|", "\\|")
            lines.append(f"| `{k}` | {official_text} | {current_text} |")
        lines.append("")
    lines.append("> 分類檔：`-new.tsv` / `-changed.tsv` / `-removed.tsv` / `-to-translate.tsv`")
    path = base + "-summary.md"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AION2 語言包同步 pipeline")
    src = ap.add_argument_group("官方來源（三揀一）")
    src.add_argument("--game", help="AION2 遊戲根目錄（會自動由 pak 抽 en-US dat）")
    src.add_argument("--official-dat", help="已抽出嘅官方 en-US dat")
    src.add_argument("--official-json", help="純文字對照表（測試用）")
    ap.add_argument("--chs", help="簡體來源 dat（可選，用嚟補新鍵）")
    ap.add_argument("--tm", default=os.path.join(HERE, "tm", "zh-TW.json.zst"), help="翻譯記憶")
    ap.add_argument("--tm-out", help="輸出更新後嘅翻譯記憶（預設覆蓋 --tm）")
    ap.add_argument("--snapshot", default=os.path.join(HERE, "snapshots", "en-US.json.zst"), help="上次官方快照")
    ap.add_argument("--snapshot-out", help="輸出今次官方快照（預設覆蓋 --snapshot）")
    ap.add_argument("--keys", help="keys.json 路徑")
    ap.add_argument("--locale", default="en-US")
    ap.add_argument("--out", default=os.path.join(REPO, "langpack", "L10NString.dat"), help="輸出語言包 dat")
    ap.add_argument("--report-dir", default=os.path.join(HERE, "reports"))
    ap.add_argument("--dry-run", action="store_true", help="唔寫 dat，只出報告")
    ap.add_argument("--build", action="store_true", help="完成後執行 build.bat 重新打包 exe")
    args = ap.parse_args(argv)

    args.keys = l10n.load_keys(args.keys)
    namespace, official_entries, source = load_official(args)
    official = dict(official_entries)
    print(f"官方條目 {len(official)}（{source}）")

    tm: Dict[str, str] = {}
    if os.path.exists(args.tm):
        _, pairs = load_pairs(args.tm)
        tm = dict(pairs)
        print(f"翻譯記憶 {len(tm)} 條（{args.tm}）")
    else:
        print(f"（未有翻譯記憶 {args.tm}，可以用 tm_export.py 由舊 dat 匯出）")

    snapshot: Dict[str, str] = {}
    if os.path.exists(args.snapshot):
        _, pairs = load_pairs(args.snapshot)
        snapshot = dict(pairs)
        print(f"上次官方快照 {len(snapshot)} 條（{args.snapshot}）")

    chs: Dict[str, str] = {}
    if args.chs:
        _, chs_pairs = l10n.parse(l10n.decrypt(open(args.chs, "rb").read(), args.locale, args.keys))
        chs = dict(chs_pairs)
        print(f"簡體來源 {len(chs)} 條（{args.chs}）")

    new_keys = [k for k in official if k not in snapshot]
    changed = [k for k in official if k in snapshot and snapshot[k] != official[k]]
    removed = [k for k in snapshot if k not in official]
    fuzzy = [k for k in changed if k in tm]

    current: Dict[str, str] = {}
    origin: Dict[str, str] = {}
    for key, english in official_entries:
        tm_val = tm.get(key)
        prev_en = snapshot.get(key)
        # TM 入面只係抄返英文（未翻或者英文本身改咗）嘅話，唔算譯文
        is_fallback = bool(tm_val) and not store.is_cjk(tm_val) and (tm_val == english or tm_val == prev_en)
        if tm_val and not is_fallback:
            current[key] = tm_val
            origin[key] = "tm"
        elif key in chs and store.is_cjk(chs[key]):
            current[key] = s2tw(chs[key])
            origin[key] = "chs"
        elif tm_val:
            current[key] = tm_val
            origin[key] = "tm"
        else:
            current[key] = english
            origin[key] = "english"
    to_translate = [k for k, v in current.items() if not store.is_cjk(v) and v == official.get(k)]

    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    summary = write_reports(args.report_dir, stamp, official, current, new_keys, changed, removed,
                            fuzzy, to_translate, tm, source)
    print(f"報告：{summary}")
    print(f"新增 {len(new_keys)} / 英文改動 {len(changed)}（需覆核 {len(fuzzy)}）/ 已移除 {len(removed)} / 待翻譯 {len(to_translate)}")

    # 更新翻譯記憶：保留舊有譯文，加入今次所有條目
    new_tm = dict(tm)
    new_tm.update({k: v for k, v in current.items() if v})
    tm_out = args.tm_out or args.tm
    store.dump({"namespace": namespace, "locale": "zh-TW", "entries": list(new_tm.items())}, tm_out)
    print(f"翻譯記憶 -> {tm_out}（{len(new_tm)} 條）")

    snap_out = args.snapshot_out or args.snapshot
    store.dump({"namespace": namespace, "locale": "en-US", "entries": official_entries}, snap_out)
    print(f"官方快照 -> {snap_out}")

    if args.dry_run:
        print("（--dry-run，唔寫 dat）")
        return 0

    raw = l10n.build(namespace, [(k, current[k]) for k, _ in official_entries])
    dat = l10n.encrypt(raw, args.locale, args.keys)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "wb") as fh:
        fh.write(dat)
    print(f"語言包 -> {args.out}（{len(dat)} bytes, {len(current)} 條）")

    if args.build:
        bat = os.path.join(REPO, "build.bat")
        print(f"執行 {bat}")
        subprocess.run(["cmd", "/c", bat], check=True, cwd=REPO)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
