# AION2 國際服 · 繁體中文語言包

<p align="center">
  <img src="docs/screenshot.png" alt="AION2 繁體中文語言包安裝工具" width="496">
</p>

給 **AION2（永恆之塔 2）國際服（Steam / PURPLE）** 使用的繁體中文語言包，附一個輕便的一鍵安裝工具。

- 單一 exe、約 4 MB，免安裝，語言包已內嵌
- 自動尋找 Steam 的遊戲安裝路徑
- 一鍵安裝、一鍵還原英文
- 支援 64 位元 Windows 10 / 11

> 台服本身已是繁體中文，不需要這個語言包。

## 下載

到 [**Releases**](https://github.com/Monohitoxx/Steam-AION2-TraditionalChinese/releases/latest) 下載 `AION2_CHT.exe`。

## 使用方法

1. 關閉遊戲。
2. 執行 `AION2_CHT.exe`。工具會自動找到遊戲路徑；找不到時按「瀏覽…」選擇 AION2 的安裝資料夾（例如 `D:\SteamLibrary\steamapps\common\AION2`）。
3. 按「安裝」，完成後啟動遊戲即可。
4. 想換回英文時按「還原英文」。

### 關於中文字型

勾選「同時安裝中文字型」時，工具會安裝含完整中日韓字形的 Noto Sans CJK 字型，讓遊戲內的中文顯示更完整。字型約 20 MB，沒有包在 exe 裡，首次安裝時會從本倉庫下載。也可以自行下載 [`langpack/NotoSans-Bold.ufont`](langpack/NotoSans-Bold.ufont) 放在 exe 旁邊，工具會優先使用本機檔案。

## 注意事項

- **遊戲更新後需要重新安裝**：Steam 更新會把語言檔蓋回英文，再開一次工具按「安裝」即可。遊戲新增的文字要等語言包更新後才會有中文。
- **還原英文**：安裝時會把原始英文語言檔備份到遊戲目錄下的 `_AION2_CHT_Backup`。如果之前用過其他漢化工具、原始檔已不在，工具無法還原，請在 Steam 對 AION2 執行「驗證遊戲檔案完整性」。
- **防毒軟體警告**：exe 沒有數位簽章，第一次執行時 SmartScreen 可能會攔截，按「其他資訊 → 仍要執行」即可。原始碼都在本倉庫，Release 內的 exe 由 GitHub Actions 從原始碼建置。
- **沒有寫入權限**：遊戲裝在 `Program Files` 之類的位置時，請以系統管理員身分執行。
- **風險自負**：這是非官方的玩家自製語言包，會替換遊戲的語言檔，與 NCSOFT 無關。

## 語言包內容

- 目前版本同步 **10 月 5 日**的遊戲版本，共 152,723 筆文字。
- 補上原本未翻譯的成就、道具、稱號與介面文字。
- 刻意保留英文的部分：伺服器名稱、`MAX`／`PVP`／`DPS` 等慣用縮寫、圖形技術名稱。

發現錯字或漏翻，歡迎開 [Issue](https://github.com/Monohitoxx/Steam-AION2-TraditionalChinese/issues) 回報。

## 運作原理

遊戲的所有文字都在 `L10NString.dat` 這個「鍵 → 文字」對照表裡。國際服沒有中文語系，所以語言包的做法是替換**英文語系（en-US）**的文字檔，遊戲以為自己在顯示英文，實際讀到的是中文。

安裝時會做三件事：

| 動作 | 檔案 |
|---|---|
| 把原始英文語言 pak 備份後換成空檔，讓遊戲改讀外部文字檔 | `Aion2\Content\Paks\L10N\Text\en-US\pakchunk502000-Windows_0_P.*` |
| 寫入繁體中文文字檔 | `Aion2\Content\L10N\Text\en-US\L10NString.dat` |
| （選用）安裝中文字型 | `Aion2\Content\UI\Font\NotoSans-Bold.ufont` |

## 從原始碼建置

不需要安裝任何開發工具，使用 Windows 內建的 .NET Framework 編譯器：

```bat
build.bat
```

會在同一個資料夾產生 `AION2_CHT.exe`，並把 `langpack\L10NString.dat` 內嵌進去。更新語言包後重新執行一次即可。

| 檔案 | 說明 |
|---|---|
| `AION2_CHT.cs` | 安裝工具原始碼（C# / WinForms） |
| `build.bat` | 建置腳本 |
| `langpack/L10NString.dat` | 繁體中文語言包 |
| `langpack/NotoSans-Bold.ufont` | 中文字型（Noto Sans CJK） |

安裝工具也支援命令列：

```bat
AION2_CHT.exe /install "D:\SteamLibrary\steamapps\common\AION2" [/nofont]
AION2_CHT.exe /uninstall "D:\SteamLibrary\steamapps\common\AION2"
```
