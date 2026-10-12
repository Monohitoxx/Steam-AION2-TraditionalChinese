# 語言包同步 pipeline

官方遊戲更新之後，用呢個 pipeline 自動同步繁體中文語言包、搵出新增／改動嘅文字。

## 現狀（重要）

| 步驟 | 狀態 |
|---|---|
| 由官方 pak 抽出 `L10NString.dat`（UE Pak v11 + 逐塊 Oodle） | ✅ 完成，7 個語系實測無誤 |
| 解出 v2 容器標頭（BLAKE3 keystream，唔需要 key） | ✅ 完成 |
| 用 AES key 解密本體 | ⚠️ **卡住**：官方更新換咗 key，`keys.json` 已失效（見下） |
| 對照表 parse / build、翻譯記憶（TM）、diff 報告、重建 dat | ✅ 完成（用舊 key 做過 15 萬條完整回歸測試：重建後內容 0 差異） |

`keycheck.py` 會直接講你知 key 係唔係仍然有效：

```
$ python keycheck.py --game "D:\SteamLibrary\steamapps\common\AION2"
語系 en-US　seed 12138667997771595427　keys.json 734 條
官方 dat 3739380 bytes：packed=3739314 etype=2 aligned=3739360 raw=17403168
結果：key 已過期 —— keys.json 嘅 L10NString_en-US key 已經過期（解密結果唔符合格式）。
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
| `l10n.py` | v2 容器：標頭、`decrypt` / `encrypt`、對照表 `parse` / `build`、密鑰表載入；key 過期會擲 `KeyMissing` 並講清楚原因 |
| `pak_extract.py` | 由官方 `pakchunk502000-Windows_0_P.pak` 逐塊 Oodle 解壓，抽出 v2 dat（`--find-game` 可自動搵路徑） |
| `keycheck.py` | 檢查 `keys.json` 對唔對得住官方最新 dat（回傳 0 / 2 / 3 方便 CI 判斷） |
| `keyfind.py` | **官方換 key 之後自己搵返**：掃描遊戲記憶體 dump（或 live process），用「本體頭 32 bytes 明文係 0」驗證，搵到就寫入 `keys.json` |
| `tm_export.py` | 由任何 dat 匯出**純文字**翻譯記憶（換 key 都唔會失去譯文） |
| `sync.py` | 主 pipeline：抽 dat → diff 官方新舊 → 疊 TM／簡體來源 → 重建 dat → 出報告 |
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
+0x14  ...      AES-256-ECB 加密本體 = 32 個 zero byte + LZ4 block + 補零至 16 對齊
```

- `seed = u64_le(blake3("L10NString_en-US")[:8])`
- `HEADER_ROOT = u64_le(blake3(pack("<Q", 0xCD02190910CE83F6))[:8])`
- `header_key(seed, htype=3) = blake3(pack("<QQiI", HEADER_ROOT, seed, htype, 0))` ← 標頭 keystream，**唔需要密鑰表**
- 本體 AES key = `keys.json[seed]` ← **官方更新會換，係 pipeline 唯一外部輸入**

**官方 pak**（UE Pak v11，`pakchunk502000-Windows_0_P.pak`）：

- pak index 用 `AES-256-ECB` + 固定 pak key 加密（`pak_extract.py` 內）
- entry 逐塊 Oodle 壓縮（默認 64 KiB），需要 `pyooz`（`ooz.decompress`）
- entry 內 layout：`+0` FPakEntry（offset/size/usize/method/20-byte hash）、`+48` block 數、`+52` 壓縮資料起點、`+60` 每 16 bytes 一個 block 結束位置（已對 7 個語系 pak 驗證）

**解壓後對照表**：

```
int32 version = 1 | fstring namespace("AION2") | int32 count | count × (fstring key, fstring value) | 4 zero bytes
fstring：int32 n（n=0 空；n>0 → n bytes UTF-8 含 \0；n<0 → |n| 個 UTF-16LE code unit 含 0x0000）
```

## key 問題（現時唯一 blocker）

官方 **2026-10-09** 更新之後，`L10NString.dat` 本體嘅 AES key 換咗：

- 舊 `keys.json`（734 條）**冇一條**可以解開新 dat（7 個語系統統唔得）
- 新 `AION2.exe` 入面搵唔到 32-byte 對齊嘅 key（4.89M 個候選全掃過），所以 key 唔係明文寫死喺 exe
- `AppData\Local\CrashDumps` 嘅 minidump 只有 crash 相關記憶體，冇 L10N 資料／key

即係：**現時 Release 嘅語言包（用舊 key）喺 10/09 之後嘅客戶端應該已經讀唔到**，要換 key 之後重新打包。

取得新 key 嘅方法（由易到難）：

1. **問簡體漢化圈／社群**（最快）：nanhezzb 嘅 `Aion2-Chinese-Patch` 生態、迅游／UU／A2Box 補丁都要用同一條 key，佢哋更新補丁時就一定有。拿到之後放落 `keys.json`（格式：`{"<seed 十進位>": "<32 bytes hex>"}`，seed 用 `keycheck.py` 會印出嚟）。
2. **由遊戲記憶體自己搵**（自足、可重複，推薦）——見下面「自己搵 key」。
3. **逆向 exe 搵推導公式**（最花時間）：**現階段唔可行**，因為 `AION2.exe` 被 NCGuard 加殼。證據：
   - PE section 名係 `.ncg0`–`.ncg6`（NCGuard），最大嘅 `.ncg0` 有 145 MB、熵值 **7.899**（加密／壓縮過）
   - entry point 係 VM/混淆 stub（`eb 03 … e8 00 00 00 00 9c 41 57 41 56 41 55`）
   - 全檔搵唔到任何已知常數／字串：BLAKE3 IV、`0xCD02190910CE83F6` root、pak AES key、`L10NString_`、`.dll`（import 都加密）
   要行呢條路就要：喺 OEP dump 解密後嘅 image、修 IAT、再對反滙編嘅 code 做 xref 分析（NCGuard 有反調試／反 dump）。真要做可以日後再講。

## 自己搵 key（官方換 key 之後）

原理：v2 容器本體頭 32 bytes 明文一定係 0，所以正確嘅 key 一定滿足

```
AES-256-ECB_decrypt(dat[0x14:0x34], key) == bytes(32)
```

喺遊戲記憶體裡面逐個 32-byte 視窗試呢個條件就搵到（兩個 AES block 都係 0 → 假陽性率 2⁻²⁵⁶）。

```bash
# 1) 開住遊戲（入到登入畫面已經夠），整個 full memory dump
procdump -ma AION2.exe aion2.dmp
#    或者：工作管理員 → 右鍵遊戲 process → 「建立傾印檔案」

# 2) 由 dump 搵 key（自動寫入 keys.json）
python tools/langpack/keyfind.py --dump aion2.dmp --dat official-en-US.dat --write-keys

# 3) 確認 + 同步
python tools/langpack/keycheck.py official-en-US.dat
python tools/langpack/sync.py --game "D:\SteamLibrary\steamapps\common\AION2" --build
```

亦可以直接讀 live process（唔需要 dump 檔，但要開住遊戲）：

```bash
python tools/langpack/keyfind.py --process AION2.exe --dat official-en-US.dat --write-keys
```

實測（用假 dump 植一條已知 key）：48 MB dump、stride 8 → 21.8 秒搵到，寫入 `keys.json` 之後成功解密 152,723 條 ✓。真機行 multiprocessing 會快好幾倍；dump 大（GB 級）就用 `--stride 8`（預設）甚至 `--stride 16`。

注意：

- 掃描係**唯讀**（`ReadProcessMemory`），唔會改遊戲任何嘢；但讀遊戲記憶體有可能被 NCGuard 視為外掛行為，風險自負。
- 遊戲要**載入過語言檔**先會有 key（入到登入畫面通常已經載入）；搵唔到就試 `--stride 4` 或者整一個更大嘅 dump。
- 只需要 en-US `L10NString` 呢一條 key（官方 dat 同社群簡體 dat 都係 en-US 語系檔）。

搵到新 key 之後，只要 `keycheck.py` 轉綠燈，`sync.py` 就可以一次過做完同步、報告同打包。

## 注意

- `keys.json` 係敏感資料，唔好 commit／貼出嚟（`.gitignore` 已經封咗）。
- `pyooz`（Oodle）同 `blake3` 係必要依賴；Python 3.14 內建 `compression.zstd` 令 TM／快照更細，3.13 就要用 `.json.xz`。
- 官方更新之後流程：`keycheck` → 有新 key 就 `sync --game … --build` → 睇 `reports/*-to-translate.tsv` 補翻譯 → 再跑一次 `sync`。
- 官方換咗 key 時：`pak_extract` → `keyfind`（dump 或 live process）→ `sync --build`，全程唔需要靠社群。
