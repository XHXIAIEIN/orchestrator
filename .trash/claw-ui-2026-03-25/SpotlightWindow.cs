using Microsoft.Web.WebView2.WinForms;
using Microsoft.Web.WebView2.Core;
using System.Runtime.InteropServices;

namespace Claw;

/// <summary>
/// Spotlight-style search bar: centered, appears on hotkey, disappears on Esc/blur.
/// </summary>
public class SpotlightWindow : Form
{
    private const int BAR_W = 640;
    private const int BAR_H_COLLAPSED = 64;
    private const int BAR_H_EXPANDED = 420;

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);

    private readonly WebView2 _webView;
    private bool _initialized = false;

    public SpotlightWindow()
    {
        Text = "Claw Spotlight";
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.Manual;
        ShowInTaskbar = false;
        TopMost = true;
        BackColor = Color.FromArgb(24, 24, 28);
        Size = new Size(BAR_W, BAR_H_COLLAPSED);

        CenterOnScreen();
        SetRoundedCorners();

        _webView = new WebView2
        {
            Dock = DockStyle.Fill,
            DefaultBackgroundColor = Color.FromArgb(24, 24, 28)
        };
        Controls.Add(_webView);

        Load += async (_, _) => await InitWebView();

        KeyPreview = true;
        KeyDown += (_, e) =>
        {
            if (e.KeyCode == Keys.Escape) HideSpotlight();
        };
    }

    private void CenterOnScreen()
    {
        var screen = Screen.PrimaryScreen!.WorkingArea;
        Location = new Point(
            screen.Left + (screen.Width - BAR_W) / 2,
            screen.Top + (int)(screen.Height * 0.28));
    }

    public void ShowSpotlight()
    {
        CenterOnScreen();
        Size = new Size(BAR_W, BAR_H_COLLAPSED);
        SetRoundedCorners();
        Show();
        Activate();
        Opacity = 1;

        if (_initialized)
        {
            _webView.CoreWebView2?.ExecuteScriptAsync("resetSpotlight()");
        }
    }

    public void HideSpotlight()
    {
        Hide();
    }

    /// <summary>Called from JS when results appear/disappear to resize the window.</summary>
    public void ResizeTo(int height)
    {
        var h = Math.Clamp(height, BAR_H_COLLAPSED, BAR_H_EXPANDED);
        Size = new Size(BAR_W, h);
        SetRoundedCorners();
    }

    private void SetRoundedCorners()
    {
        try
        {
            int preference = 2;
            DwmSetWindowAttribute(Handle, 33, ref preference, sizeof(int));
        }
        catch { }
    }

    private async Task InitWebView()
    {
        var userDataDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Claw", "WebView2-Spotlight");
        var env = await CoreWebView2Environment.CreateAsync(null, userDataDir);
        await _webView.EnsureCoreWebView2Async(env);

        _webView.CoreWebView2.WebMessageReceived += OnWebMessage;

        var webRoot = Path.Combine(AppContext.BaseDirectory, "web");
        _webView.CoreWebView2.SetVirtualHostNameToFolderMapping(
            "claw.local", webRoot, CoreWebView2HostResourceAccessKind.Allow);

        #if DEBUG
        _webView.CoreWebView2.Settings.AreDevToolsEnabled = true;
        #else
        _webView.CoreWebView2.Settings.AreDevToolsEnabled = false;
        #endif
        _webView.CoreWebView2.Settings.IsStatusBarEnabled = false;
        _webView.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;

        _webView.CoreWebView2.Navigate("https://claw.local/spotlight.html");
        _initialized = true;
    }

    private void OnWebMessage(object? sender, CoreWebView2WebMessageReceivedEventArgs e)
    {
        // JS sends: postMessage(JSON.stringify({action, height}))
        // TryGetWebMessageAsString gives us the raw JSON string
        var raw = e.TryGetWebMessageAsString() ?? "";
        try
        {
            if (raw.Contains("\"close\""))
            {
                HideSpotlight();
            }
            else if (raw.Contains("\"resize\""))
            {
                // Extract height value from {"action":"resize","height":300}
                var idx = raw.IndexOf("\"height\":");
                if (idx >= 0)
                {
                    var sub = raw.Substring(idx + 9).TrimStart();
                    var end = sub.IndexOfAny(new[] { ',', '}', ' ' });
                    if (end > 0 && int.TryParse(sub.Substring(0, end), out int h))
                    {
                        ResizeTo(h);
                    }
                }
            }
            else if (raw.Contains("\"dashboard\""))
            {
                System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
                {
                    FileName = "http://localhost:23714",
                    UseShellExecute = true
                });
                HideSpotlight();
            }
        }
        catch { }
    }
}
