# Runtime unpack + xref 掃描（搵 key 推導公式）

目標：搞清楚遊戲到底點樣由「表名／語系」算出 `L10NString_en-US` 嘅 AES key。
成功之後每次官方更新都可以自己計，唔需要再 dump 記憶體。

## 現況

| 項目 | 狀態 |
|---|---|
| `AION2.exe` 靜態分析 | ❌ **NCGuard 加殼**：section 名 `.ncg0`–`.ncg6`、`.ncg0`（145 MB）熵值 **7.899**、entry point 係 VM stub、連 `.dll`／`L10NString_`／BLAKE3 IV／root 常數都搵唔到（全部加密） |
| Runtime image 抽取工具 | ✅ `minidump.py` + `unpack.py`（已喺真 WER dump 上驗證） |
| 常數搜尋 + xref 掃描 | ✅ `xref.py`（合成 image 3/3 命中；真 binary `blake3.pyd` 命中 7 + 26 個 RIP-relative 引用） |
| 手上嘅 dump 夠唔夠 | ❌ WER 自動 minidump 只覆蓋 AION2.exe **1.8 %**（7.4 MB / 407.6 MB），冇 L10N 字串、冇 crypto 常數 |
| **需要嘅嘢** | **一個完整 dump**（`procdump -ma`，GB 級），喺遊戲行緊、入到登入畫面之後整 |

## 工具

| 檔案 | 作用 |
|---|---|
| `minidump.py` | 解析 Windows minidump：module 清單、記憶體範圍（VA ↔ 檔案 offset）、`read_va()`、`dump_module()` |
| `mdinfo.py` | 列 module／覆蓋率；喺 dump 內搵 hex pattern（會報 VA） |
| `unpack.py` | 由 dump／live process 抽出 module 喺記憶體嘅映像，再檢查完整度 marker |
| `scanmem.py` | **全 process 記憶體掃 marker**（BLAKE3 IV／root 常數／`L10NString_`／自訂 hex/ASCII）—— packer 真正解密後嘅 image 唔喺 module 範圍，所以要先靠佢定位；可把命中嘅 region 抽成檔案 |
| `findrefs.py` | **喺 live process 搵「邊段 code 引用某個 VA」**（RIP-relative 掃描，只掃可執行頁；會印 region base／保護屬性同抽檔指令）—— 用嚟由資料（IV 表、字串）反搵 code |
| `xref.py` | 喺 image／region 檔案內搵常數（BLAKE3 IV / root 常數 / 自訂 hex / ASCII），再搵邊度用 RIP-relative 引用佢，並印出附近 bytes |

## 實測發現（2026-10-13）

- `unpack.py --game … --process AION2.exe` 成功讀出 **407.5 MB** 完整映像（PID 42396）
- 但嗰個 0x140000000 映像係 **NCGuard 加密 stub**：

  | section | 大小 | 磁碟熵 | 記憶體熵 | 同磁碟相同 |
  |---|---|---|---|---|
  | `.ncg0`（加密 code） | 145,941,504 | 7.899 | **0.000（全零）** | 0.5% |
  | `.ncg2` | 88,576 | 0.000 | 0.000 | 100% |
  | `.ncg3` | 12,800 | 2.588 | 2.666 | 98.8% |
  | `.ncg4` | 10,294,784 | 6.808 | 6.808 | 100% |
  | `.ncg5` | 202,752 | 6.860 | 6.860 | 100% |
  | `.ncg6` | 1,024 | 0.235 | 0.235 | 100% |

- 即係 `L10NString_`、BLAKE3 IV、`.dll` 字串全部唔喺 module 映像裡面 —— NCGuard 另外配置記憶體再解密。所以流程要改成：**scanmem 全記憶體搵 marker → 抽命中 region → xref**。

## 步驟

```bash
# 0) 確認遊戲 process 名（主程式叫 AION2.exe；未開遊戲就冇）
python tools/re/unpack.py --list-processes

# 1) 遊戲入到登入畫面／角色選單之後，全記憶體搵 marker（唔需要 dump 檔）
python tools/re/scanmem.py --process AION2.exe --preset blake3 --find-ascii L10NString_
#     讀唔到就試管理員身分執行；亦可用 --pid <PID>

# 2) 由命中位址所屬 region 嘅 base 抽一段出嚟（size 用 scanmem 報嘅 region size）
python tools/re/scanmem.py --process AION2.exe --dump-region 0x1d24de60000 --size 0x100000 --out region.bin

# 3) 喺抽到嘅 region 做 xref（base 用 region VA）
python tools/re/xref.py region.bin --base 0x1d24de60000 --preset blake3 --span 0x100

# 4) 最重要：搵「邊段 code 引用呢個 VA」（唔使 dump，直接掃 live process 嘅可執行頁）
python tools/re/findrefs.py --process AION2.exe --target 0x5968d40:IV64 --target 0x5968e40:IV32 --context 64
#     支援三種引用形式：RIP-relative、絕對 `[disp32]`（ModRM 04 + SIB 25）、
#     `mov r32/r64, imm`（即絕對位址）。命中會印 region base/size/保護屬性 + 一行現成嘅
#     scanmem --dump-region 指令，照跑就可以把嗰塊 code 抽出嚟分析。
#     註：位移可以好大（例如 +90 MB），唔可以假設高位 byte 一定係 00/FF。
#     如果 0 命中，加 --all-regions（連非可執行／保護屬性特別嘅頁都掃）。

# 1B)（後備）完整 dump 路線
procdump -ma AION2.exe aion2-full.dmp
python tools/re/scanmem.py --dump aion2-full.dmp --preset blake3
```
```

`--span N` 係指「指向目標 ±N bytes 之內都當係引用」，因為程式通常會引用表格中間某個欄位。

`unpack.py` 會自動檢查完整度：要有 `L10NString_` 字串同 BLAKE3 IV 先算抽得夠齊。`--game` 模式會先試磁碟 PE 嘅 preferred base（唔靠 module snapshot），讀唔到（ASLR 移位／權限）就自動改用 module snapshot。

## 有 image 之後嘅分析計劃

1. **確認 image 完整**：`xref.py --find-ascii L10NString_` 應該搵到種子字串；`--preset blake3` 應該搵到 IV（64-bit 或 32-bit 形式都會試）。
2. **搵標頭 keystream 嘅計算點**：搵 root 常數 `0xCD02190910CE83F6` 嘅引用。已知公式係
   `header_key(seed, htype=3) = blake3(pack("<QQiI", HEADER_ROOT, seed, 3, 0))`，
   喺 code 上應該見到「砌一個 20-byte 緩衝區（root/seed/type/0）→ call blake3 → 拎頭 16 bytes」。
3. **睇 AES key 係推導定查表**：
   - 推導：同一段 code 附近會有另一個 type 常數（例如 1、2 或 4）＋ 一樣嘅 blake3 調用；
     試 `blake3(pack("<QQiI", ROOT, seed, htype, 0))` 各種 htype，睇下能唔能夠解開官方 dat。
   - 查表：會見到一個 32-byte 間距嘅表格（734 條 key 就係咁嚟）＋ 一個 look-up（seed → index）。
     咁就要搞清楚 seed 係點 map 去 index（可能係排序／hash），或者直接由表格抽 key。
4. **落碼驗證**：寫落 `tools/langpack/derive_key.py`，直接對最新官方 dat 做 `keycheck` 級驗證
   （`AES_dec(dat[0x14:0x34], key) == 0`）。呢一步先算真正成功。

## 注意

- NCGuard 係客戶端防護：dump 遊戲記憶體有可能被視為外掛行為，風險自負（同 `tools/langpack/keyfind.py` 一樣）。
- 建議喺**登入畫面之後**（唔係啟動器畫面）dump，確保 L10N 已經解密／載入。
- WER 自動 dump（`%LOCALAPPDATA%\CrashDumps`）唔夠用；一定要完整 dump。
- 如果 image 完整但 xref 一個都搵唔到，可能 NCGuard 會即時抹走／還原部分頁面，可以試多次 dump 或者喺唔同時間點 dump。
