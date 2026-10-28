// AION2 國際服繁體中文語言包安裝工具
// 以 Windows 內建的 .NET Framework 編譯器建置（見 build.bat），語言包本體內嵌於 exe。
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Forms;
using Microsoft.Win32;

// 版本資訊：有完整 metadata 的執行檔比較唔會被防毒啟發式當成「免洗 dropper」，亦係程式碼簽章的必要條件。
// Release workflow 會用 tag 名（v1.2.3 → 1.2.3.0）覆寫下面兩個版本號。
[assembly: AssemblyTitle("AION2 繁體中文語言包安裝工具")]
[assembly: AssemblyDescription("AION2 國際服（Steam / PURPLE）繁體中文語言包安裝工具")]
[assembly: AssemblyProduct("AION2 繁體中文語言包")]
[assembly: AssemblyCompany("Monohitoxx")]
[assembly: AssemblyCopyright("Copyright © Monohitoxx")]
[assembly: AssemblyVersion("1.0.5.0")]
[assembly: AssemblyFileVersion("1.0.5.0")]

static class Patch
{
    public const string PackVersion = "同步 10 月 21 日版本";
    const string SteamAppId = "3393110";
    const string EnPakDir = @"Aion2\Content\Paks\L10N\Text\en-US";
    const string EnPakName = "pakchunk502000-Windows_0_P";
    const string DatPath = @"Aion2\Content\L10N\Text\en-US\L10NString.dat";
    const string FontPath = @"Aion2\Content\UI\Font\NotoSans-Bold.ufont";
    const string BackupDir = "_AION2_CHT_Backup";
    const string FontName = "NotoSans-Bold.ufont";
    const string FontMd5 = "3dd7f29fd6f36d1fe71a2daf4a03a59c";
    const string FontUrl = "https://raw.githubusercontent.com/Monohitoxx/Steam-AION2-TraditionalChinese/main/langpack/NotoSans-Bold.ufont";
    static readonly string[] PakExts = { ".pak", ".sig", ".ucas", ".utoc" };
    static readonly string[] GameProcesses = { "AION2", "Aion2", "Aion2-Win64-Shipping" };

    public enum State { NoGame, NotInstalled, Installed, NeedsReinstall, OtherPatch }

    public static bool IsGameDir(string dir)
    {
        return !string.IsNullOrEmpty(dir) && Directory.Exists(Path.Combine(dir, @"Aion2\Content\Paks"));
    }

    // 使用者可能選到遊戲目錄底下的子資料夾，往上找到真正的根目錄
    public static string ResolveGameDir(string dir)
    {
        try
        {
            for (int i = 0; i < 5 && !string.IsNullOrEmpty(dir); i++)
            {
                if (IsGameDir(dir)) return dir.TrimEnd('\\');
                dir = Path.GetDirectoryName(dir.TrimEnd('\\'));
            }
        }
        catch (ArgumentException) { }
        return null;
    }

    public static string FindGameDir()
    {
        var libraries = new List<string>();
        foreach (var key in new[] { @"HKEY_CURRENT_USER\Software\Valve\Steam", @"HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Valve\Steam" })
        {
            foreach (var name in new[] { "SteamPath", "InstallPath" })
            {
                var steam = Registry.GetValue(key, name, null) as string;
                if (string.IsNullOrEmpty(steam)) continue;
                steam = steam.Replace('/', '\\');
                libraries.Add(steam);
                var vdf = Path.Combine(steam, @"steamapps\libraryfolders.vdf");
                if (!File.Exists(vdf)) continue;
                foreach (Match m in Regex.Matches(File.ReadAllText(vdf), "\"path\"\\s+\"([^\"]+)\""))
                    libraries.Add(m.Groups[1].Value.Replace(@"\\", @"\"));
            }
        }
        foreach (var lib in libraries)
        {
            try
            {
                var acf = Path.Combine(lib, @"steamapps\appmanifest_" + SteamAppId + ".acf");
                if (!File.Exists(acf)) continue;
                var m = Regex.Match(File.ReadAllText(acf), "\"installdir\"\\s+\"([^\"]+)\"");
                var dir = Path.Combine(lib, @"steamapps\common", m.Success ? m.Groups[1].Value : "AION2");
                if (IsGameDir(dir)) return dir;
            }
            catch (IOException) { }
        }
        return null;
    }

    // ---- 自動搜尋遊戲資料夾 ----
    // Steam 版通常在 x:\SteamLibrary\steamapps\common\AION2，PURPLE 版通常在 x:\AION2。
    // 兩者資料夾名稱都是全大寫的 AION2，所以直接找名字是 AION2 而且有 Aion2\Content\Paks 的資料夾。

    static List<string> DriveRoots()
    {
        var roots = new List<string>();
        try
        {
            foreach (var d in DriveInfo.GetDrives())
            {
                try
                {
                    if (!d.IsReady) continue;
                    if (d.DriveType != DriveType.Fixed && d.DriveType != DriveType.Removable) continue;
                    roots.Add(d.RootDirectory.FullName.TrimEnd('\\') + "\\");
                }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
        }
        catch (IOException) { }
        return roots;
    }

    static void AddDir(List<string> list, string dir)
    {
        if (!IsGameDir(dir)) return;
        var full = dir.TrimEnd('\\');
        foreach (var d in list)
            if (string.Equals(d, full, StringComparison.OrdinalIgnoreCase)) return;
        list.Add(full);
    }

    // 快速檢查：Steam 註冊表 + 每個磁碟的常見位置（唔掃全碟）
    public static List<string> QuickGameDirs()
    {
        var list = new List<string>();
        AddDir(list, FindGameDir());
        foreach (var root in DriveRoots())
        {
            AddDir(list, Path.Combine(root, "AION2"));
            AddDir(list, Path.Combine(root, @"SteamLibrary\steamapps\common\AION2"));
            AddDir(list, Path.Combine(root, @"Steam\steamapps\common\AION2"));
            AddDir(list, Path.Combine(root, @"Program Files (x86)\Steam\steamapps\common\AION2"));
            AddDir(list, Path.Combine(root, @"Program Files\Steam\steamapps\common\AION2"));
            AddDir(list, Path.Combine(root, @"Program Files (x86)\NC\AION2"));
            AddDir(list, Path.Combine(root, @"Program Files\NC\AION2"));
            AddDir(list, Path.Combine(root, @"Program Files (x86)\NCSOFT\AION2"));
            AddDir(list, Path.Combine(root, @"Program Files\NCSOFT\AION2"));
        }
        return list;
    }

    const int ScanMaxDepth = 5;
    const int ScanMaxResults = 12;
    static readonly string[] ScanSkipNames = {
        "windows", "$recycle.bin", "system volume information", "programdata", "recovery", "perflogs",
        "msocache", "config.msi", "appdata", "node_modules", ".git", ".svn", "temp", "tmp", "onedrive",
        "$windows.~bt", "$windows.~ws"
    };

    static bool IsSkipName(string name)
    {
        var lower = name.ToLowerInvariant();
        foreach (var s in ScanSkipNames)
            if (s == lower) return true;
        return false;
    }

    // 掃描所有本機磁碟（最多 5 層），回傳所有有效的 AION2 資料夾
    public static List<string> ScanGameDirs(Action<string> progress, Func<bool> cancelled)
    {
        var found = new List<string>();
        int visited = 0;
        foreach (var root in DriveRoots())
        {
            if (cancelled != null && cancelled()) break;
            ScanTree(root, ScanMaxDepth, found, progress, cancelled, ref visited);
        }
        found.Sort(delegate(string a, string b)
        {
            int c = a.Length.CompareTo(b.Length);
            return c != 0 ? c : string.Compare(a, b, StringComparison.OrdinalIgnoreCase);
        });
        return found;
    }

    static void ScanTree(string root, int maxDepth, List<string> found, Action<string> progress, Func<bool> cancelled, ref int visited)
    {
        var queue = new Queue<KeyValuePair<string, int>>();
        queue.Enqueue(new KeyValuePair<string, int>(root, 0));
        while (queue.Count > 0)
        {
            if (cancelled != null && cancelled()) return;
            if (found.Count >= ScanMaxResults) return;
            var node = queue.Dequeue();
            string[] subs;
            try { subs = Directory.GetDirectories(node.Key); }
            catch (UnauthorizedAccessException) { continue; }
            catch (IOException) { continue; }
            visited++;
            if (progress != null && visited % 128 == 0) progress(node.Key);
            foreach (var sub in subs)
            {
                string name;
                try { name = Path.GetFileName(sub); }
                catch (ArgumentException) { continue; }
                if (string.IsNullOrEmpty(name)) continue;
                if (name.Equals("AION2", StringComparison.OrdinalIgnoreCase))
                {
                    if (IsGameDir(sub)) AddDir(found, sub);
                    continue; // 唔需要再深入遊戲資料夾
                }
                if (node.Value + 1 >= maxDepth) continue;
                if (IsSkipName(name)) continue;
                try { if ((File.GetAttributes(sub) & FileAttributes.ReparsePoint) != 0) continue; }
                catch (IOException) { continue; }
                catch (UnauthorizedAccessException) { continue; }
                queue.Enqueue(new KeyValuePair<string, int>(sub, node.Value + 1));
            }
        }
    }

    public static bool GameRunning()
    {
        foreach (var name in GameProcesses)
            if (Process.GetProcessesByName(name).Length > 0) return true;
        return false;
    }

    static byte[] PackData()
    {
        using (var s = Assembly.GetExecutingAssembly().GetManifestResourceStream("cht.dat"))
        {
            var data = new byte[s.Length];
            int read = 0;
            while (read < data.Length) read += s.Read(data, read, data.Length - read);
            return data;
        }
    }

    static string Md5(byte[] data)
    {
        using (var md5 = MD5.Create()) return BitConverter.ToString(md5.ComputeHash(data)).Replace("-", "").ToLowerInvariant();
    }

    static string Md5File(string path)
    {
        using (var md5 = MD5.Create())
        using (var s = File.OpenRead(path))
            return BitConverter.ToString(md5.ComputeHash(s)).Replace("-", "").ToLowerInvariant();
    }

    // en-US 的語言 pak 是否已被換成 0 位元組佔位檔（或被刪掉）。
    // 遊戲更新會把 pak 還原，所以判斷「裝唔裝到」一定要睇實際檔案，唔可以睇備份資料夾。
    public static bool PakNeutralized(string game)
    {
        foreach (var ext in new[] { ".pak", ".ucas", ".utoc" })
        {
            var path = Path.Combine(game, EnPakDir, EnPakName + ext);
            if (File.Exists(path) && new FileInfo(path).Length > 0) return false;
        }
        return true;
    }

    public static State GetState(string game)
    {
        if (!IsGameDir(game)) return State.NoGame;
        var dat = Path.Combine(game, DatPath);
        if (!File.Exists(dat)) return State.NotInstalled;
        // 語言 pak 已被遊戲更新還原 → 遊戲會讀回英文，中文唔會生效
        if (!PakNeutralized(game)) return State.NeedsReinstall;
        return Md5File(dat) == Md5(PackData()) ? State.Installed : State.OtherPatch;
    }

    public static bool FontInstalled(string game)
    {
        var font = Path.Combine(game, FontPath);
        return File.Exists(font) && Md5File(font) == FontMd5;
    }

    // 字型來源：exe 旁邊的檔案優先，沒有才下載
    static string LocalFont()
    {
        var exeDir = Path.GetDirectoryName(Application.ExecutablePath);
        foreach (var p in new[] { Path.Combine(exeDir, FontName), Path.Combine(exeDir, "langpack", FontName) })
            if (File.Exists(p) && Md5File(p) == FontMd5) return p;
        return null;
    }

    static string DownloadFont(Action<int, string> progress)
    {
        var tmp = Path.Combine(Path.GetTempPath(), "AION2_CHT_" + FontName);
        if (File.Exists(tmp) && Md5File(tmp) == FontMd5) return tmp;
        ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072; // TLS 1.2
        var req = (HttpWebRequest)WebRequest.Create(FontUrl);
        req.Timeout = 30000;
        using (var resp = req.GetResponse())
        using (var src = resp.GetResponseStream())
        using (var dst = File.Create(tmp))
        {
            long total = resp.ContentLength, done = 0;
            var buf = new byte[81920];
            int n;
            while ((n = src.Read(buf, 0, buf.Length)) > 0)
            {
                dst.Write(buf, 0, n);
                done += n;
                if (total > 0) progress((int)(done * 100 / total), "下載字型中… " + (done >> 20) + " / " + (total >> 20) + " MB");
            }
        }
        if (Md5File(tmp) != FontMd5)
        {
            File.Delete(tmp);
            throw new IOException("字型下載不完整，請再試一次。");
        }
        return tmp;
    }

    public static void Install(string game, bool withFont, Action<int, string> progress)
    {
        progress(0, "備份原始英文語言檔…");
        var enDir = Path.Combine(game, EnPakDir);
        var backup = Path.Combine(game, BackupDir);
        Directory.CreateDirectory(enDir);
        foreach (var ext in PakExts)
        {
            var src = Path.Combine(enDir, EnPakName + ext);
            if (!File.Exists(src)) continue;
            // 0 位元組的 pak 是先前補丁留下的佔位檔，不是原始檔
            if (ext == ".pak" && new FileInfo(src).Length == 0) continue;
            Directory.CreateDirectory(backup);
            File.Copy(src, Path.Combine(backup, EnPakName + ext), true);
            File.Delete(src);
        }
        File.WriteAllBytes(Path.Combine(enDir, EnPakName + ".pak"), new byte[0]);

        progress(0, "寫入繁體中文語言包…");
        var dat = Path.Combine(game, DatPath);
        Directory.CreateDirectory(Path.GetDirectoryName(dat));
        File.WriteAllBytes(dat, PackData());

        if (withFont && !FontInstalled(game))
        {
            var font = LocalFont() ?? DownloadFont(progress);
            progress(100, "安裝字型…");
            var target = Path.Combine(game, FontPath);
            Directory.CreateDirectory(Path.GetDirectoryName(target));
            File.Copy(font, target, true);
        }
    }

    // 回傳 true 表示英文已還原；false 表示原始 pak 已不存在，需要 Steam/PURPLE 驗證檔案
    public static bool Uninstall(string game)
    {
        var dat = Path.Combine(game, DatPath);
        if (File.Exists(dat)) File.Delete(dat);
        if (FontInstalled(game)) File.Delete(Path.Combine(game, FontPath));

        var enDir = Path.Combine(game, EnPakDir);
        var backup = Path.Combine(game, BackupDir);
        var placeholder = Path.Combine(enDir, EnPakName + ".pak");
        bool hasBackup = File.Exists(Path.Combine(backup, EnPakName + ".pak"));

        if (hasBackup)
        {
            if (File.Exists(placeholder) && new FileInfo(placeholder).Length == 0) File.Delete(placeholder);
            foreach (var ext in PakExts)
            {
                var src = Path.Combine(backup, EnPakName + ext);
                if (!File.Exists(src)) continue;
                File.Copy(src, Path.Combine(enDir, EnPakName + ext), true);
                File.Delete(src);
            }
            if (Directory.GetFileSystemEntries(backup).Length == 0) Directory.Delete(backup);
            return true;
        }

        // 冇備份：如果原始 pak 已經在（例如遊戲更新時還原過），刪掉外部 dat 就已經是英文
        if (PakNeutralized(game))
        {
            // 只剩我們留下的 0 位元組佔位檔，刪掉後要玩家自己驗證檔案
            if (File.Exists(placeholder) && new FileInfo(placeholder).Length == 0) File.Delete(placeholder);
            return false;
        }
        return true;
    }
}

public class MainForm : Form
{
    readonly TextBox pathBox = new TextBox();
    readonly Label stateLabel = new Label();
    readonly Label statusLabel = new Label();
    readonly CheckBox fontCheck = new CheckBox();
    readonly Button browseButton = new Button();
    readonly Button installButton = new Button();
    readonly Button uninstallButton = new Button();
    readonly ProgressBar progressBar = new ProgressBar();
    readonly BackgroundWorker worker = new BackgroundWorker();
    readonly BackgroundWorker scanWorker = new BackgroundWorker();
    readonly BackgroundWorker updateWorker = new BackgroundWorker();
    readonly BackgroundWorker downloadWorker = new BackgroundWorker();
    bool userPicked;
    bool updatePrompted;

    public MainForm()
    {
        Text = "AION2 繁體中文語言包";
        Font = new Font("Microsoft JhengHei UI", 9f);
        AutoScaleDimensions = new SizeF(96f, 96f);
        AutoScaleMode = AutoScaleMode.Dpi;
        ClientSize = new Size(480, 250);
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;

        var title = new Label { Text = "AION2 國際服 · 繁體中文語言包", Font = new Font(Font.FontFamily, 13f, FontStyle.Bold), Location = new Point(16, 14), AutoSize = true };
        var version = new Label { Text = Patch.PackVersion + " · 工具 v" + Updater.CurrentText, ForeColor = SystemColors.GrayText, Location = new Point(18, 44), AutoSize = true };
        var pathLabel = new Label { Text = "遊戲安裝路徑", Location = new Point(18, 76), AutoSize = true };
        pathBox.SetBounds(18, 96, 362, 23);
        browseButton.Text = "瀏覽…";
        browseButton.SetBounds(388, 95, 74, 25);
        stateLabel.SetBounds(18, 126, 444, 20);
        fontCheck.Text = "同時安裝中文字型（建議，首次需下載約 20 MB）";
        fontCheck.Checked = true;
        fontCheck.SetBounds(18, 150, 444, 22);
        installButton.Text = "安裝";
        installButton.SetBounds(18, 182, 218, 32);
        uninstallButton.Text = "還原英文";
        uninstallButton.SetBounds(244, 182, 218, 32);
        progressBar.SetBounds(18, 182, 444, 32);
        progressBar.Visible = false;
        statusLabel.SetBounds(18, 222, 444, 20);
        statusLabel.ForeColor = SystemColors.GrayText;
        Controls.AddRange(new Control[] { title, version, pathLabel, pathBox, browseButton, stateLabel, fontCheck, installButton, uninstallButton, progressBar, statusLabel });
        AcceptButton = installButton;

        pathBox.TextChanged += delegate { RefreshState(); };
        browseButton.Click += delegate { Browse(); };
        installButton.Click += delegate { Start(true); };
        uninstallButton.Click += delegate { Start(false); };
        worker.WorkerReportsProgress = true;
        worker.DoWork += DoWork;
        worker.ProgressChanged += ShowProgress;
        worker.RunWorkerCompleted += Completed;

        // 自動更新：背景檢查 GitHub Release tag，有新版就問用戶
        updateWorker.DoWork += UpdateDoWork;
        updateWorker.RunWorkerCompleted += UpdateCompleted;
        downloadWorker.WorkerReportsProgress = true;
        downloadWorker.DoWork += DownloadDoWork;
        downloadWorker.ProgressChanged += ShowProgress;
        downloadWorker.RunWorkerCompleted += DownloadCompleted;

        // 先在背景快速找出遊戲路徑，再於背景掃描所有磁碟（Steam 版與 PURPLE 版都支援）
        scanWorker.WorkerReportsProgress = true;
        scanWorker.WorkerSupportsCancellation = true;
        scanWorker.DoWork += ScanDoWork;
        scanWorker.ProgressChanged += delegate(object s, ProgressChangedEventArgs e)
        {
            if (!worker.IsBusy && !userPicked) statusLabel.Text = "自動搜尋 AION2 資料夾… " + Shorten((string)e.UserState);
        };
        scanWorker.RunWorkerCompleted += ScanCompleted;
        Shown += delegate
        {
            scanWorker.RunWorkerAsync();
            if (!Updater.Disabled) updateWorker.RunWorkerAsync();
        };
        FormClosing += delegate { scanWorker.CancelAsync(); };

        var quick = Patch.QuickGameDirs();
        if (quick.Count > 0) pathBox.Text = quick[0];
        RefreshState();
        ActiveControl = installButton.Enabled ? (Control)installButton : browseButton;
    }

    static string Shorten(string path)
    {
        if (string.IsNullOrEmpty(path)) return "";
        return path.Length <= 42 ? path : "…" + path.Substring(path.Length - 41);
    }

    void ScanDoWork(object sender, DoWorkEventArgs e)
    {
        e.Result = Patch.ScanGameDirs(
            delegate(string path) { scanWorker.ReportProgress(0, path); },
            delegate { return scanWorker.CancellationPending; });
    }

    void ScanCompleted(object sender, RunWorkerCompletedEventArgs e)
    {
        if (userPicked || worker.IsBusy) return;
        var found = e.Error == null ? e.Result as List<string> : null;
        if (found == null || found.Count == 0)
        {
            if (GameDir == null)
            {
                RefreshState();
                statusLabel.Text = "找不到遊戲，請按「瀏覽…」選擇 AION2 的安裝資料夾。";
            }
            else
            {
                statusLabel.Text = "";
            }
            return;
        }
        if (found.Count == 1)
        {
            if (GameDir == null) pathBox.Text = found[0];
            RefreshState();
            statusLabel.Text = "已自動找到：" + Shorten(found[0]);
            return;
        }
        // 找到多個（例如同時裝了 Steam 版與 PURPLE 版）→ 問用戶要用哪一個
        using (var pick = new PickFolderForm(found, GameDir))
        {
            if (pick.ShowDialog(this) == DialogResult.OK && !string.IsNullOrEmpty(pick.Selected))
            {
                userPicked = true;
                pathBox.Text = pick.Selected;
            }
        }
        statusLabel.Text = "";
        RefreshState();
    }

    string GameDir { get { return Patch.ResolveGameDir(pathBox.Text.Trim().Trim('"')); } }

    void RefreshState()
    {
        Patch.State state;
        try { state = GameDir == null ? Patch.State.NoGame : Patch.GetState(GameDir); }
        catch (IOException) { state = Patch.State.NoGame; }
        catch (UnauthorizedAccessException) { state = Patch.State.NoGame; }
        switch (state)
        {
            case Patch.State.NoGame:
                stateLabel.Text = "找不到遊戲，請選擇 AION2 的安裝資料夾。";
                stateLabel.ForeColor = Color.Firebrick;
                break;
            case Patch.State.NotInstalled:
                stateLabel.Text = "狀態：尚未安裝（目前為英文）";
                stateLabel.ForeColor = SystemColors.ControlText;
                break;
            case Patch.State.Installed:
                stateLabel.Text = "狀態：已安裝此版本的繁體中文語言包";
                stateLabel.ForeColor = Color.SeaGreen;
                break;
            case Patch.State.NeedsReinstall:
                stateLabel.Text = "狀態：語言檔已被遊戲更新還原，請再按「安裝」";
                stateLabel.ForeColor = Color.Firebrick;
                break;
            case Patch.State.OtherPatch:
                stateLabel.Text = "狀態：已安裝其他版本的語言包，可直接覆蓋安裝";
                stateLabel.ForeColor = Color.DarkGoldenrod;
                break;
        }
        installButton.Enabled = state != Patch.State.NoGame;
        installButton.Text = state == Patch.State.Installed || state == Patch.State.NeedsReinstall ? "重新安裝" : "安裝";
        uninstallButton.Enabled = state == Patch.State.Installed || state == Patch.State.NeedsReinstall || state == Patch.State.OtherPatch;
    }

    void Browse()
    {
        userPicked = true;
        scanWorker.CancelAsync();
        using (var dialog = new FolderBrowserDialog { Description = "請選擇 AION2 的安裝資料夾（Steam 版例如 D:\\SteamLibrary\\steamapps\\common\\AION2；PURPLE 版例如 D:\\AION2）", ShowNewFolderButton = false })
        {
            if (Directory.Exists(pathBox.Text)) dialog.SelectedPath = pathBox.Text;
            if (dialog.ShowDialog(this) != DialogResult.OK) return;
            pathBox.Text = Patch.ResolveGameDir(dialog.SelectedPath) ?? dialog.SelectedPath;
        }
        statusLabel.Text = "";
    }

    void Start(bool install)
    {
        if (Patch.GameRunning())
        {
            MessageBox.Show(this, "遊戲正在執行中，請先關閉遊戲再操作。", Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        SetBusy(true);
        worker.RunWorkerAsync(new object[] { install, GameDir, fontCheck.Checked });
    }

    void SetBusy(bool busy)
    {
        installButton.Visible = uninstallButton.Visible = !busy;
        progressBar.Visible = busy;
        progressBar.Style = ProgressBarStyle.Marquee;
        pathBox.Enabled = browseButton.Enabled = fontCheck.Enabled = !busy;
    }

    void ShowProgress(object sender, ProgressChangedEventArgs e)
    {
        progressBar.Style = e.ProgressPercentage > 0 ? ProgressBarStyle.Continuous : ProgressBarStyle.Marquee;
        progressBar.Value = Math.Min(100, e.ProgressPercentage);
        statusLabel.Text = (string)e.UserState;
    }

    void UpdateDoWork(object sender, DoWorkEventArgs e)
    {
        e.Result = Updater.Check();
    }

    void UpdateCompleted(object sender, RunWorkerCompletedEventArgs e)
    {
        // 冇網絡、GitHub API 出錯、或者用戶已經有其他操作：靜靜咁算，唔阻礙主要功能
        if (e.Error != null || e.Result == null) return;
        var rel = (Updater.Release)e.Result;
        if (!Updater.IsNewer(rel) || updatePrompted || worker.IsBusy || downloadWorker.IsBusy) return;
        updatePrompted = true;
        var answer = MessageBox.Show(this,
            "發現新版本 " + rel.Tag + "（目前 v" + Updater.CurrentText + "）。\n\n要立即自動下載並更新嗎？更新完會自動重新啟動。",
            Text, MessageBoxButtons.YesNo, MessageBoxIcon.Information);
        if (answer != DialogResult.Yes)
        {
            statusLabel.Text = "有新版本 " + rel.Tag + "：" + Updater.ReleasePage;
            return;
        }
        SetBusy(true);
        statusLabel.Text = "下載更新中…";
        downloadWorker.RunWorkerAsync(rel);
    }

    void DownloadDoWork(object sender, DoWorkEventArgs e)
    {
        e.Result = Updater.Prepare((Updater.Release)e.Argument, downloadWorker.ReportProgress);
    }

    void DownloadCompleted(object sender, RunWorkerCompletedEventArgs e)
    {
        SetBusy(false);
        if (e.Error != null)
        {
            statusLabel.Text = "更新失敗。";
            MessageBox.Show(this, "自動更新失敗：" + e.Error.Message + "\n\n可以到 Release 頁面手動下載：\n" + Updater.ReleasePage,
                Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        var file = (string)e.Result;
        try
        {
            Process.Start(file, "/selfupdate " + Process.GetCurrentProcess().Id + " \"" + Application.ExecutablePath + "\"");
            Application.Exit();
        }
        catch (Exception ex)
        {
            statusLabel.Text = "更新失敗。";
            MessageBox.Show(this, "已下載更新檔但無法啟動它：" + ex.Message + "\n\n檔案位置：\n" + file + "\n請手動執行該檔案。",
                Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    void DoWork(object sender, DoWorkEventArgs e)
    {
        var args = (object[])e.Argument;
        var game = (string)args[1];
        if ((bool)args[0])
        {
            Patch.Install(game, (bool)args[2], worker.ReportProgress);
            e.Result = "安裝完成，重新啟動遊戲後生效。";
        }
        else
        {
            e.Result = Patch.Uninstall(game)
                ? "已還原為英文。"
                : "已移除語言包，但找不到原始英文檔的備份。\n請在 Steam 對 AION2 執行「驗證遊戲檔案完整性」來還原英文。";
        }
    }

    void Completed(object sender, RunWorkerCompletedEventArgs e)
    {
        SetBusy(false);
        RefreshState();
        if (e.Error == null)
        {
            statusLabel.Text = ((string)e.Result).Split('\n')[0];
            MessageBox.Show(this, (string)e.Result, Text, MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }
        statusLabel.Text = "操作失敗。";
        var message = e.Error is UnauthorizedAccessException
            ? "沒有寫入遊戲資料夾的權限，請以系統管理員身分執行本工具。"
            : e.Error is WebException
                ? "字型下載失敗：" + e.Error.Message + "\n\n語言包本體已安裝。可以取消勾選字型後直接使用，或稍後再試。"
                : e.Error.Message;
        MessageBox.Show(this, message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
    }
}

// 找到多個 AION2 資料夾時，讓使用者選擇要安裝哪一個（也可以自己瀏覽）
public class PickFolderForm : Form
{
    readonly ListBox list = new ListBox();

    public string Selected { get; private set; }

    public PickFolderForm(List<string> items, string preselect)
    {
        Text = "選擇 AION2 安裝資料夾";
        Font = new Font("Microsoft JhengHei UI", 9f);
        AutoScaleDimensions = new SizeF(96f, 96f);
        AutoScaleMode = AutoScaleMode.Dpi;
        ClientSize = new Size(480, 250);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        ShowInTaskbar = false;
        StartPosition = FormStartPosition.CenterParent;

        var label = new Label { Text = "找到多個 AION2 資料夾，請選擇要安裝的遊戲：", Location = new Point(14, 12), AutoSize = true };
        list.SetBounds(14, 38, 452, 158);
        list.Items.AddRange(items.ToArray());
        if (!string.IsNullOrEmpty(preselect))
        {
            for (int i = 0; i < list.Items.Count; i++)
                if (string.Equals((string)list.Items[i], preselect, StringComparison.OrdinalIgnoreCase)) { list.SelectedIndex = i; break; }
        }
        if (list.SelectedIndex < 0 && list.Items.Count > 0) list.SelectedIndex = 0;

        var ok = new Button { Text = "確定", DialogResult = DialogResult.OK };
        ok.SetBounds(224, 206, 76, 28);
        var browse = new Button { Text = "瀏覽…" };
        browse.SetBounds(308, 206, 76, 28);
        var cancel = new Button { Text = "取消", DialogResult = DialogResult.Cancel };
        cancel.SetBounds(392, 206, 74, 28);
        browse.Click += delegate
        {
            using (var dialog = new FolderBrowserDialog { Description = "請選擇 AION2 的安裝資料夾", ShowNewFolderButton = false })
            {
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                Selected = Patch.ResolveGameDir(dialog.SelectedPath) ?? dialog.SelectedPath;
                DialogResult = DialogResult.OK;
                Close();
            }
        };
        AcceptButton = ok;
        CancelButton = cancel;
        Controls.AddRange(new Control[] { label, list, ok, browse, cancel });
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        if (DialogResult == DialogResult.OK && string.IsNullOrEmpty(Selected) && list.SelectedItem != null)
            Selected = (string)list.SelectedItem;
        base.OnFormClosing(e);
    }
}

// 自動更新：檢查 GitHub Release 嘅 tag，同執行檔版本比較，有新版就下載、驗證、自我替換再重啟。
static class Updater
{
    public const string ReleasePage = "https://github.com/Monohitoxx/Steam-AION2-TraditionalChinese/releases/latest";
    const string ApiUrl = "https://api.github.com/repos/Monohitoxx/Steam-AION2-TraditionalChinese/releases/latest";
    const string AssetName = "AION2_CHT.exe";
    const string ShaAssetName = "AION2_CHT.exe.sha256";

    public class Release
    {
        public string Tag;
        public Version Version;
        public string ExeUrl;
        public string Digest;   // 由 GitHub API 提供（可能冇）
        public string ShaUrl;   // 另外上載嘅 .sha256 檔（可能冇）
        public string PageUrl;
    }

    // 測試用：可以用環境變數指向本機 JSON file://
    public static string FeedUrl
    {
        get
        {
            var custom = Environment.GetEnvironmentVariable("AION2_CHT_UPDATE_URL");
            return string.IsNullOrEmpty(custom) ? ApiUrl : custom;
        }
    }

    public static bool Disabled
    {
        get { return Environment.GetEnvironmentVariable("AION2_CHT_NO_UPDATE") == "1"; }
    }

    // 更新檔放 %LOCALAPPDATA%\AION2_CHT\update（比 TEMP 少啲防毒疑慮）；測試可以用環境變數改
    public static string UpdateDir
    {
        get
        {
            var custom = Environment.GetEnvironmentVariable("AION2_CHT_UPDATE_DIR");
            if (!string.IsNullOrEmpty(custom)) return custom;
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AION2_CHT", "update");
        }
    }

    // 更新完成之後，新版本開機時順手清走舊下載
    public static void CleanupDownloads()
    {
        try
        {
            var dir = UpdateDir;
            if (string.IsNullOrEmpty(dir) || !Directory.Exists(dir)) return;
            var self = Application.ExecutablePath;
            if (!string.IsNullOrEmpty(self) && self.StartsWith(dir, StringComparison.OrdinalIgnoreCase)) return;
            foreach (var file in Directory.GetFiles(dir))
                try { File.Delete(file); } catch (IOException) { } catch (UnauthorizedAccessException) { }
        }
        catch (Exception) { }
    }

    public static Version Current
    {
        get { return Assembly.GetExecutingAssembly().GetName().Version; }
    }

    public static string CurrentText
    {
        get { var v = Current; return v.Major + "." + v.Minor + "." + v.Build; }
    }

    public static Version ParseTag(string tag)
    {
        if (string.IsNullOrEmpty(tag)) return null;
        var m = Regex.Match(tag, @"(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?");
        if (!m.Success) return null;
        Func<Group, int> num = delegate(Group g) { return g.Success ? int.Parse(g.Value) : 0; };
        return new Version(num(m.Groups[1]), num(m.Groups[2]), num(m.Groups[3]), num(m.Groups[4]));
    }

    static string FetchText(string url, int timeoutMs)
    {
        ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072; // TLS 1.2
        var req = WebRequest.Create(url);
        req.Timeout = timeoutMs;
        var http = req as HttpWebRequest;
        if (http != null)
        {
            http.UserAgent = "AION2_CHT-Updater";
            http.Accept = "application/vnd.github+json";
        }
        using (var resp = req.GetResponse())
        using (var stream = resp.GetResponseStream())
        using (var reader = new StreamReader(stream, Encoding.UTF8))
            return reader.ReadToEnd();
    }

    static string JsonString(string json, string key)
    {
        var m = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*\"([^\"]*)\"");
        return m.Success ? m.Groups[1].Value : null;
    }

    static string AssetField(string json, string asset, string field, string pattern)
    {
        var m = Regex.Match(json, "\"name\"\\s*:\\s*\"" + Regex.Escape(asset) + "\"[\\s\\S]{0,3000}?\"" + field + "\"\\s*:\\s*\"(" + pattern + ")\"");
        return m.Success ? m.Groups[1].Value : null;
    }

    // 檢查 GitHub 上面嘅最新 release；網絡失敗會擲 WebException
    public static Release Check()
    {
        var json = FetchText(FeedUrl, 10000);
        var rel = new Release();
        rel.Tag = JsonString(json, "tag_name");
        rel.PageUrl = JsonString(json, "html_url");
        rel.Version = ParseTag(rel.Tag);
        rel.ExeUrl = AssetField(json, AssetName, "browser_download_url", "[^\"]+");
        if (rel.ExeUrl == null) rel.ExeUrl = JsonString(json, "browser_download_url");
        var digest = AssetField(json, AssetName, "digest", "[^\"]+");
        if (!string.IsNullOrEmpty(digest) && digest.StartsWith("sha256:")) rel.Digest = digest.Substring(7);
        rel.ShaUrl = AssetField(json, ShaAssetName, "browser_download_url", "[^\"]+");
        if (rel.Version == null)
            throw new InvalidOperationException("GitHub release 冇可辨識嘅版本 tag：" + (rel.Tag ?? "(null)"));
        return rel;
    }

    public static bool IsNewer(Release rel)
    {
        return rel != null && rel.Version != null && rel.Version > Current;
    }

    public static string Sha256File(string path)
    {
        using (var sha = SHA256.Create())
        using (var s = File.OpenRead(path))
            return BitConverter.ToString(sha.ComputeHash(s)).Replace("-", "").ToLowerInvariant();
    }

    static string Download(string url, string dest, Action<int, string> progress)
    {
        var req = WebRequest.Create(url);
        req.Timeout = 30000;
        using (var resp = req.GetResponse())
        using (var src = resp.GetResponseStream())
        using (var dst = File.Create(dest))
        {
            long total = resp.ContentLength, done = 0;
            var buf = new byte[81920];
            int n;
            while ((n = src.Read(buf, 0, buf.Length)) > 0)
            {
                dst.Write(buf, 0, n);
                done += n;
                if (progress != null && total > 0) progress((int)(done * 100 / total), "下載更新中… " + (done >> 20) + " / " + (total >> 20) + " MB");
            }
        }
        return dest;
    }

    // 下載 -> 驗證 SHA-256 -> 交畀新版本自己做替換
    public static string Prepare(Release rel, Action<int, string> progress)
    {
        if (rel == null || string.IsNullOrEmpty(rel.ExeUrl)) throw new InvalidOperationException("release 冇 exe 下載連結");
        Directory.CreateDirectory(UpdateDir);
        var tmp = Path.Combine(UpdateDir, "AION2_CHT-" + rel.Version + ".exe");
        Download(rel.ExeUrl, tmp, progress);
        var expected = rel.Digest;
        if (string.IsNullOrEmpty(expected) && !string.IsNullOrEmpty(rel.ShaUrl))
        {
            try
            {
                var text = FetchText(rel.ShaUrl, 15000).Trim();
                var m = Regex.Match(text, "[0-9a-fA-F]{64}");
                if (m.Success) expected = m.Value.ToLowerInvariant();
            }
            catch (WebException) { }
        }
        if (!string.IsNullOrEmpty(expected))
        {
            var actual = Sha256File(tmp);
            if (!string.Equals(actual, expected, StringComparison.OrdinalIgnoreCase))
            {
                File.Delete(tmp);
                throw new IOException("下載嘅更新檔 SHA-256 唔對，已取消更新。");
            }
        }
        return tmp;
    }

    // 由新版本執行：等舊 process 收工 -> 覆蓋 -> 重新啟動
    public static int SelfUpdate(string[] args)
    {
        int pid = 0;
        int.TryParse(args.Length > 1 ? args[1] : "", out pid);
        string target = args.Length > 2 ? args[2] : null;
        bool restart = Array.IndexOf(args, "/norestart") < 0;
        if (string.IsNullOrEmpty(target)) { Console.WriteLine("用法：/selfupdate <pid> <target.exe> [/norestart]"); return 2; }

        if (pid > 0)
        {
            try { Process.GetProcessById(pid).WaitForExit(30000); }
            catch (ArgumentException) { }
            catch (InvalidOperationException) { }
        }
        string self = Assembly.GetExecutingAssembly().Location;
        Exception last = null;
        for (int i = 0; i < 25; i++)
        {
            try { File.Copy(self, target, true); last = null; break; }
            catch (IOException ex) { last = ex; }
            catch (UnauthorizedAccessException ex) { last = ex; }
            System.Threading.Thread.Sleep(400);
        }
        if (last != null)
        {
            var message = "自動更新失敗（檔案被鎖住或者冇寫入權限）：" + last.Message + "\n請手動下載最新版本：\n" + ReleasePage;
            Console.WriteLine(message);
            try { MessageBox.Show(message, "AION2 繁體中文語言包", MessageBoxButtons.OK, MessageBoxIcon.Warning); }
            catch (Exception) { }
            return 1;
        }
        Console.WriteLine("已更新到 " + target);
        if (restart)
        {
            try { Process.Start(target); }
            catch (Exception ex) { Console.WriteLine("重新啟動失敗：" + ex.Message); }
        }
        return 0;
    }

    // 命令列：/checkupdate 只報告；/update 直接下載 + 自我更新
    public static int CliCheck()
    {
        try
        {
            var rel = Check();
            Console.WriteLine("目前版本：v" + CurrentText);
            Console.WriteLine("最新版本：" + rel.Tag + "　" + (rel.PageUrl ?? ReleasePage));
            if (IsNewer(rel))
            {
                Console.WriteLine("有新版本可以更新。");
                return 1;
            }
            Console.WriteLine("已經係最新版本。");
            return 0;
        }
        catch (Exception ex)
        {
            Console.WriteLine("檢查更新失敗：" + ex.Message);
            return 2;
        }
    }

    public static int CliUpdate(string[] args)
    {
        bool noRestart = Array.IndexOf(args, "/norestart") >= 0;
        try
        {
            var rel = Check();
            if (!IsNewer(rel))
            {
                Console.WriteLine("已經係最新版本（v" + CurrentText + "）。");
                return 0;
            }
            Console.WriteLine("發現新版本 " + rel.Tag + "，開始下載…");
            int lastPct = -1;
            var file = Prepare(rel, delegate(int pct, string msg)
            {
                if (pct >= lastPct + 10 || pct >= 100) { lastPct = pct; Console.WriteLine("  下載中… " + pct + "%"); }
            });
            Console.WriteLine("已下載並驗證：" + file);
            try
            {
                var psi = "/selfupdate " + Process.GetCurrentProcess().Id + " \"" + Application.ExecutablePath + "\"" + (noRestart ? " /norestart" : "");
                Process.Start(file, psi);
                Console.WriteLine("已交由新版本完成替換，本程序結束。");
                return 0;
            }
            catch (Exception ex)
            {
                Console.WriteLine("啟動更新程序失敗：" + ex.Message);
                return 4;
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine("更新失敗：" + ex.Message);
            return 3;
        }
    }
}

static class Program
{
    [DllImport("user32.dll")]
    static extern bool SetProcessDPIAware();

    // 命令列：/install、/uninstall、/scan、/checkupdate、/update [/norestart]、/selfupdate（內部用）
    [STAThread]
    static int Main(string[] args)
    {
        if (args.Length >= 1 && args[0] == "/selfupdate")
            return Updater.SelfUpdate(args);
        if (args.Length >= 1 && args[0] == "/checkupdate")
            return Updater.CliCheck();
        if (args.Length >= 1 && args[0] == "/update")
            return Updater.CliUpdate(args);
        // /noupdate 只係一個旗標，可以同其他參數一齊用（先抽走再判斷動作）
        var rest = new List<string>(args);
        if (rest.Remove("/noupdate"))
            Environment.SetEnvironmentVariable("AION2_CHT_NO_UPDATE", "1");
        args = rest.ToArray();

        Updater.CleanupDownloads();
        if (args.Length >= 1 && args[0] == "/scan")
        {
            var found = Patch.ScanGameDirs(null, null);
            foreach (var dir in found) Console.WriteLine(dir);
            return found.Count > 0 ? 0 : 2;
        }
        if (args.Length >= 2 && (args[0] == "/install" || args[0] == "/uninstall"))
        {
            var game = Patch.ResolveGameDir(args[1]);
            if (game == null) return 2;
            try
            {
                if (args[0] == "/install") Patch.Install(game, Array.IndexOf(args, "/nofont") < 0, delegate { });
                else return Patch.Uninstall(game) ? 0 : 3;
                return 0;
            }
            catch (Exception) { return 1; }
        }
        SetProcessDPIAware();
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new MainForm());
        return 0;
    }
}
