using Microsoft.Web.WebView2.WinForms;
using Microsoft.Web.WebView2.Core;
using System.Runtime.InteropServices;

namespace Claw;

/// <summary>
/// Compact status widget overlay — always-on-top, bottom-right.
/// Shows live Orchestrator metrics. Click to open Spotlight or Dashboard.
/// </summary>
public class FloatingWindow : Form
{
    private const int WIDGET_W = 280;
    private const int WIDGET_H = 140;

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);

    private readonly WebView2 _webView;

    public FloatingWindow()
    {
        Text = "Claw Widget";
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.Manual;
        Size = new Size(WIDGET_W, WIDGET_H);
        ShowInTaskbar = false;
        TopMost = true;
        BackColor = Color.FromArgb(24, 24, 28);
        Opacity = 0.92;

        var workArea = Screen.PrimaryScreen!.WorkingArea;
        Location = new Point(workArea.Right - WIDGET_W - 16, workArea.Bottom - WIDGET_H - 16);

        SetRoundedCorners();

        _webView = new WebView2
        {
            Dock = DockStyle.Fill,
            DefaultBackgroundColor = Color.FromArgb(24, 24, 28)
        };
        Controls.Add(_webView);

        Load += async (_, _) => await InitWebView();
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
            "Claw", "WebView2-Widget");
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

        _webView.CoreWebView2.Navigate("https://claw.local/widget.html");
    }

    private void OnWebMessage(object? sender, CoreWebView2WebMessageReceivedEventArgs e)
    {
        var msg = e.TryGetWebMessageAsString();
        if (msg == "dashboard")
        {
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
            {
                FileName = "http://localhost:23714",
                UseShellExecute = true
            });
        }
    }

    protected override void OnVisibleChanged(EventArgs e)
    {
        base.OnVisibleChanged(e);
        if (Visible)
        {
            Opacity = 0;
            var timer = new System.Windows.Forms.Timer { Interval = 10 };
            timer.Tick += (_, _) =>
            {
                if (Opacity < 0.92)
                    Opacity = Math.Min(0.92, Opacity + 0.1);
                else
                    timer.Stop();
            };
            timer.Start();
        }
    }
}
