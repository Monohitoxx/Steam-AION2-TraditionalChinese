# 語言包同步 pipeline

官方遊戲更新之後，用呢個 pipeline 自動同步繁體中文語言包、搵出新增／改動嘅文字。

## 現狀

| 步驟 | 狀態 |
|---|---|
| 由官方 pak 抽出 `L10NString.dat`（UE Pak v11 + 逐塊 Oodle） | ✅ 完成，7 個語系實測無誤 |
| 解出 v2 容器標頭（BLAKE3 keystream，唔需要 key） | ✅ 完成 |
| 用 AES key 解密本體 | ✅ 完成（key 由 `keys.json` 提供，唔會 commit；**10-09 格式更新後仍然有效**） |
| 對照表 parse / build、翻譯記憶（TM）、diff 報告、重建 dat | ✅ 完成（10 萬條級完整回歸測試：重建後內容 0 差異） |
| 依官方 10-09 版本重建 | ✅ 152,774 條，沿用官方 32-byte 前綴 |

`keycheck.py` 會直接講你知 key 係唔係仍然有效：

```
$ python keycheck.py --game "D:\SteamLibrary\steamapps\common\AION2"
語系 en-US　seed 12138667997771595427　keys.json 1 條
官方 dat 3739380 bytes：packed=3739314 etype=2 aligned=3739360 raw=17403168
結果：key 有效 ✓
```

## 快速開始

```bash
pip install -r tools/langpack/requirements.txt
export AION2_KEYS=/path/to/keys.json          # 或者放 tools/langpack/keys.json（已 gitignore）

# 1) 檢查 key 仲 work 唔 work（官方更新後必做）
python tools/langpack/keycheck.py --game "D:\SteamLibrary\steamapps\common\AION2"

# 2) 官方更新之後同步（會出報告 + 新 dat，可加 --build 順手重編 exe）
python tools/langpack/sync.py --game "D:\SteamLibrary\steamapps\common\AION2" --build

# 3) 想睇報告但唔寫 dat
python tools/langpack/sync.py --official-dat official-en-US.dat --dry-run
```

第一次由舊語言包建立翻譯記憶（key 未過期時做，之後換 key 都唔怕）：

```bash
python tools/langpack/tm_export.py langpack/L10NString.dat tools/langpack/tm/zh-TW.json.zst
```

## 工具

| 檔案 | 作用 |
|---|---|
| `l10n.py` | v2 容器：標頭、`decrypt` / `encrypt`（可指定 32-byte 前綴）、對照表 `parse` / `build`、密鑰表載入 |
| `pak_extract.py` | 由官方 `pakchunk502000-Windows_0_P.pak` 逐塊 Oodle 解壓，抽出 v2 dat（`--find-game` 可自動搵路徑） |
| `keycheck.py` | 檢查 `keys.json` 對唔對得住官方最新 dat（回傳 0 / 2 / 3 方便 CI 判斷） |
| `tm_export.py` | 由任何 dat 匯出**純文字**翻譯記憶（換 key 都唔會失去譯文） |
| `sync.py` | 主 pipeline：抽 dat → diff 官方新舊 → 疊 TM／簡體來源 → 重建 dat（沿用官方前綴）→ 出報告 |
| `store.py` | TM / 快照格式（壓縮 JSON：`.json.zst` / `.json.xz` / `.json`） |

## 目錄

```
tools/langpack/
├── tm/zh-TW.json.zst        # 翻譯記憶（純文字，2.5 MB，建議 commit）
├── snapshots/en-US.json.zst # 上次官方英文快照（diff 用，官方更新後由 sync.py 更新）
├── reports/                 # 每次同步嘅報告（gitignore）
└── keys.json                # AES 密鑰表（gitignore，唔好公開）
```

`sync.py` 每次會出：

- `reports/<時間>-summary.md`：新增／英文改動／已移除／待翻譯 嘅統計同清單
- `reports/<時間>-new.tsv`、`-changed.tsv`、`-removed.tsv`、`-to-translate.tsv`：逐條 key + 官方文字 + 現時譯文（可以直接掉入翻譯工具）
- 更新後嘅 TM、官方快照、`langpack/L10NString.dat`（`--build` 會再跑 `build.bat` 包 exe）

分類定義：

| 分類 | 意思 | 要點做 |
|---|---|---|
| 新增 | 官方加咗嘅 key | 睇 `-new.tsv`，冇中文就翻譯 |
| 英文改動 | 同一個 key，官方英文唔同咗 | 舊譯文保留但列入 `需覆核`（`-changed.tsv` 有註記） |
| 已移除 | 官方刪咗嘅 key | 通常唔使理，會由新 dat 剔走 |
| 待翻譯 | 現時仍然係英文 | 主要工作清單 |

## 格式備忘

**v2 容器**（little-endian）：

```
+0x00  uint32   版本 = 2
+0x04  16 bytes 標頭 = pack("<iiii", packed, etype=2, aligned, raw_size) XOR header_key(seed)
+0x14  ...      AES-256-ECB 加密本體 = 32 bytes 前綴 + LZ4 block + 補零至 16 對齊
```

- `seed = u64_le(blake3("L10NString_en-US")[:8])`
- `HEADER_ROOT = u64_le(blake3(pack("<Q", 0xCD02190910CE83F6))[:8])`
- `header_key(seed, htype=3) = blake3(pack("<QQiI", HEADER_ROOT, seed, htype, 0))` ← 標頭 keystream，**唔需要密鑰表**
- 本體 AES key = `keys.json[seed]`

**⚠️ 2026-10-09 官方更新：32 bytes 前綴由「32 個零」變成隨機 metadata**

| | body[0x00:0x20] | body[0x20:…] |
|---|---|---|
| 舊（≤ 10-05） | `00 ×32` | LZ4 block |
| 新（10-09 之後） | 32 bytes 隨機 metadata | **完全一樣**嘅 LZ4 block |

- **AES key 冇換** ✓（同一條 key 仍然解得到新 dat：152,774 條）
- 前綴唔係 hash（試過 `blake3(raw)`／`blake3(packed)` 都唔中）→ 所以 **重建時沿用官方嘅前綴** 最安全
- `l10n.py` 已改成：`decrypt()` 直接試 LZ4（唔再要求零前綴）、新增 `body_prefix()`、`encrypt(..., prefix=…)`；`sync.py` 自動沿用官方前綴

**官方 pak**（UE Pak v11，`pakchunk502000-Windows_0_P.pak`）：

- pak index 用 `AES-256-ECB` + 固定 pak key 加密（`pak_extract.py` 內）
- entry 逐塊 Oodle 壓縮（默認 64 KiB），需要 `pyooz`（`ooz.decompress`）
- entry 內 layout：`+0` FPakEntry（offset/size/usize/method/20-byte hash）、`+48` block 數、`+52` 壓縮資料起點、`+60` 每 16 bytes 一個 block 結束位置（已對 7 個語系 pak 驗證）

**解壓後對照表**：

```
int32 version = 1 | fstring namespace("AION2") | int32 count | count × (fstring key, fstring value) | 4 zero bytes
fstring：int32 n（n=0 空；n>0 → n bytes UTF-8 含 \0；n<0 → |n| 個 UTF-16LE code unit 含 0x0000）
```

## AES key（`keys.json`）

本體用 AES-256-ECB 加密，key 由 `keys.json` 提供（格式 `{"<seed 十進位>": "<32 bytes hex>"}`，seed 用 `keycheck.py` 會印出嚟）。**key 唔會 commit**，`.gitignore` 已經封咗 `keys.json`。

- 官方 2026-10-09 更新**冇換 key**（同一條 key 仍然解得到新 dat），只係本體頭 32 bytes 由零改成 metadata ✓
- 官方更新之後先跑 `keycheck.py`：綠燈就直接 `sync`；萬一將來真係換 key，就要向社群取得新 key 放落 `keys.json`，同樣跑 `keycheck.py` 確認之後再 `sync`

## 注意

- `keys.json` 係敏感資料，唔好 commit／貼出嚟（`.gitignore` 已經封咗）。
- `pyooz`（Oodle）同 `blake3` 係必要依賴；Python 3.14 內建 `compression.zstd` 令 TM／快照更細，3.13 就要用 `.json.xz`。
- 官方更新之後流程：`keycheck` → `sync --game … --build` → 睇 `reports/*-to-translate.tsv` 補翻譯 → 再跑一次 `sync`。
