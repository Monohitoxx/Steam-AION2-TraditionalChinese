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
using System.Text.RegularExpressions;
using System.Windows.Forms;
using Microsoft.Win32;

static class Patch
{
    public const string PackVersion = "同步 10 月 5 日版本";
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

    public enum State { NoGame, NotInstalled, Installed, OtherPatch }

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

    public static State GetState(string game)
    {
        if (!IsGameDir(game)) return State.NoGame;
        var dat = Path.Combine(game, DatPath);
        if (!File.Exists(dat)) return State.NotInstalled;
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

    // 回傳 true 表示已還原原始英文檔；false 表示沒有備份可還原
    public static bool Uninstall(string game)
    {
        var dat = Path.Combine(game, DatPath);
        if (File.Exists(dat)) File.Delete(dat);
        if (FontInstalled(game)) File.Delete(Path.Combine(game, FontPath));

        var enDir = Path.Combine(game, EnPakDir);
        var backup = Path.Combine(game, BackupDir);
        var placeholder = Path.Combine(enDir, EnPakName + ".pak");
        bool hasBackup = File.Exists(Path.Combine(backup, EnPakName + ".pak"));
        if (File.Exists(placeholder) && new FileInfo(placeholder).Length == 0) File.Delete(placeholder);
        if (!hasBackup) return false;
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
        var version = new Label { Text = Patch.PackVersion, ForeColor = SystemColors.GrayText, Location = new Point(18, 44), AutoSize = true };
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
        worker.ProgressChanged += delegate(object s, ProgressChangedEventArgs e)
        {
            progressBar.Style = e.ProgressPercentage > 0 ? ProgressBarStyle.Continuous : ProgressBarStyle.Marquee;
            progressBar.Value = Math.Min(100, e.ProgressPercentage);
            statusLabel.Text = (string)e.UserState;
        };
        worker.RunWorkerCompleted += Completed;

        pathBox.Text = Patch.FindGameDir() ?? "";
        RefreshState();
        ActiveControl = installButton.Enabled ? (Control)installButton : browseButton;
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
            case Patch.State.OtherPatch:
                stateLabel.Text = "狀態：已安裝其他版本的語言包，可直接覆蓋安裝";
                stateLabel.ForeColor = Color.DarkGoldenrod;
                break;
        }
        installButton.Enabled = state != Patch.State.NoGame;
        installButton.Text = state == Patch.State.Installed ? "重新安裝" : "安裝";
        uninstallButton.Enabled = state == Patch.State.Installed || state == Patch.State.OtherPatch;
    }

    void Browse()
    {
        using (var dialog = new FolderBrowserDialog { Description = "請選擇 AION2 的安裝資料夾（例如 D:\\SteamLibrary\\steamapps\\common\\AION2）", ShowNewFolderButton = false })
        {
            if (Directory.Exists(pathBox.Text)) dialog.SelectedPath = pathBox.Text;
            if (dialog.ShowDialog(this) != DialogResult.OK) return;
            pathBox.Text = Patch.ResolveGameDir(dialog.SelectedPath) ?? dialog.SelectedPath;
        }
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

static class Program
{
    [DllImport("user32.dll")]
    static extern bool SetProcessDPIAware();

    // 命令列：AION2_CHT.exe /install <遊戲路徑> [/nofont]　或　/uninstall <遊戲路徑>
    [STAThread]
    static int Main(string[] args)
    {
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
