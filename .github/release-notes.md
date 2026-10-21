AION2 國際服（Steam / PURPLE）繁體中文語言包，同步 **10 月 21 日**的遊戲版本，共 153,185 筆文字。

補譯新增的 143 筆文字，並覆核 227 筆改動：英雄級別遠征藝術品、外觀、艾瑞爾碎片、守護力道具，以及副本成就次數、稱號能力數值與顯示設定說明。

## 使用方法

1. 關閉遊戲。
2. 下載並執行下方的 `AION2_CHT.exe`。
3. 確認遊戲路徑後按「安裝」，啟動遊戲即可。

工具啟動時會自動檢查有沒有新版本，有新版可以直接在工具內一按更新（下載後會用 Release 附帶的 SHA-256 驗證，再替換並重新啟動）。

想換回英文時按「還原英文」。遊戲更新後需要重新安裝一次。

## 注意

- **SmartScreen 攔截（未簽章 exe 一定會遇到）**：見到「Microsoft Defender SmartScreen 已防止某個無法辨識的應用程式啟動」時，按「**更多資訊**」→「**仍要執行**」。
  想以後唔再彈，可以先解除封鎖（任選一個）：
  - 右鍵 `AION2_CHT.exe` →「內容」→「一般」→ 最下面勾「**解除封鎖**」→「確定」。
  - 或者開 PowerShell 打：`Unblock-File .\AION2_CHT.exe`
  - 或者用命令列下載（`Invoke-WebRequest` 唔會加互聯網標記）：
    `powershell -c "iwr https://github.com/Monohitoxx/Steam-AION2-TraditionalChinese/releases/latest/download/AION2_CHT.exe -OutFile AION2_CHT.exe; .\AION2_CHT.exe"`
- 部分防毒軟體亦會誤報（原因見 [防毒軟體誤報](https://github.com/Monohitoxx/Steam-AION2-TraditionalChinese#防毒軟體誤報)）。
- 可以用下方的 `AION2_CHT.exe.sha256` 核對檔案：`certutil -hashfile AION2_CHT.exe SHA256`。
- 勾選「同時安裝中文字型」時，首次會下載約 20 MB 的字型。
- 這是非官方的玩家自製語言包，使用風險自負。

詳細說明請看 [README](https://github.com/Monohitoxx/Steam-AION2-TraditionalChinese#readme)。
