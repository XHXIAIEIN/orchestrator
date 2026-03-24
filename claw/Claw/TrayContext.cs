namespace Claw;

/// <summary>
/// System tray daemon. No windows, no UI — just tray icon + notifications.
/// Connects to Orchestrator via WebSocket, shows Toast for events & approvals.
/// </summary>
public class TrayContext : ApplicationContext
{
    private readonly NotifyIcon _tray;
    private readonly OrchestratorLink _link;
    private bool _online = false;

    public TrayContext()
    {
        _tray = new NotifyIcon
        {
            Text = "Claw — Connecting...",
            Icon = SystemIcons.Application,
            Visible = true,
            ContextMenuStrip = BuildMenu()
        };

        _link = new OrchestratorLink();
        _link.OnStatusChanged += OnStatusChanged;
        _link.OnEvent += OnEvent;
        _link.OnApprovalRequest += OnApprovalRequest;
        _link.Start();
    }

    private ContextMenuStrip BuildMenu()
    {
        var menu = new ContextMenuStrip();
        menu.Items.Add("Open Dashboard", null, (_, _) => OpenUrl("http://localhost:23714"));
        menu.Items.Add("Trigger Collection", null, async (_, _) => await _link.SendCommand("trigger_collection"));
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("Exit", null, (_, _) => ExitApp());
        return menu;
    }

    private void OnStatusChanged(bool online, string detail)
    {
        _online = online;
        _tray.Text = online ? $"Claw — Online ({detail})" : "Claw — Offline";
    }

    private void OnEvent(string type, string title, string body)
    {
        ToastManager.ShowEvent(type, title, body);
    }

    private void OnApprovalRequest(string taskId, string description, int authLevel)
    {
        ToastManager.ShowApproval(taskId, description, authLevel, decision =>
        {
            _ = _link.SendApproval(taskId, decision);
        });
    }

    private static void OpenUrl(string url)
    {
        System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
        {
            FileName = url,
            UseShellExecute = true
        });
    }

    private void ExitApp()
    {
        _link.Stop();
        _tray.Visible = false;
        _tray.Dispose();
        ToastManager.Cleanup();
        Application.Exit();
    }
}
