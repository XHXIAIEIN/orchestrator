using Microsoft.Toolkit.Uwp.Notifications;

namespace Claw;

/// <summary>
/// Windows Toast notifications with action buttons for approvals.
/// </summary>
public static class ToastManager
{
    private static readonly Dictionary<string, Action<string>> _pendingApprovals = new();

    static ToastManager()
    {
        ToastNotificationManagerCompat.OnActivated += OnToastActivated;
    }

    /// <summary>Show an informational event notification.</summary>
    public static void ShowEvent(string type, string title, string body)
    {
        new ToastContentBuilder()
            .AddText(title)
            .AddText(body)
            .AddAttributionText($"Orchestrator · {type}")
            .Show();
    }

    /// <summary>Show an approval request with Approve/Deny buttons.</summary>
    public static void ShowApproval(string taskId, string description, int authLevel, Action<string> callback)
    {
        _pendingApprovals[taskId] = callback;

        var risk = authLevel switch
        {
            <= 3 => "Low risk",
            <= 6 => "Medium risk",
            _ => "HIGH RISK"
        };

        new ToastContentBuilder()
            .AddText($"Approval Required ({risk})")
            .AddText(description)
            .AddAttributionText($"Task {taskId} · Authority level {authLevel}")
            .AddButton(new ToastButton()
                .SetContent("Approve")
                .AddArgument("action", "approve")
                .AddArgument("taskId", taskId))
            .AddButton(new ToastButton()
                .SetContent("Deny")
                .AddArgument("action", "deny")
                .AddArgument("taskId", taskId))
            .Show();
    }

    private static void OnToastActivated(ToastNotificationActivatedEventArgsCompat e)
    {
        var args = ToastArguments.Parse(e.Argument);

        if (args.TryGetValue("action", out string? action) &&
            args.TryGetValue("taskId", out string? taskId))
        {
            if (_pendingApprovals.TryGetValue(taskId!, out var callback))
            {
                callback(action!);
                _pendingApprovals.Remove(taskId!);
            }
        }
    }

    public static void Cleanup()
    {
        ToastNotificationManagerCompat.Uninstall();
    }
}
