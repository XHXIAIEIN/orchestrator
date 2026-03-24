using System.Net.WebSockets;
using System.Text;
using System.Text.Json;

namespace Claw;

/// <summary>
/// WebSocket client that maintains a persistent connection to Orchestrator.
/// Auto-reconnects on disconnect. Receives events, sends approvals.
/// </summary>
public class OrchestratorLink
{
    private const string WS_URL = "ws://localhost:23714";
    private const string API_URL = "http://localhost:23714";
    private const int RECONNECT_MS = 5000;
    private const int HEALTH_POLL_MS = 10000;

    public event Action<bool, string>? OnStatusChanged;
    public event Action<string, string, string>? OnEvent;
    public event Action<string, string, int>? OnApprovalRequest;

    private ClientWebSocket? _ws;
    private CancellationTokenSource _cts = new();
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(5) };

    public void Start()
    {
        Task.Run(ConnectionLoop);
        Task.Run(HealthPollLoop);
    }

    public void Stop()
    {
        _cts.Cancel();
        _ws?.Dispose();
    }

    /// <summary>Send an approval decision back to Orchestrator.</summary>
    public async Task SendApproval(string taskId, string decision)
    {
        try
        {
            var payload = JsonSerializer.Serialize(new
            {
                type = "approval_response",
                task_id = taskId,
                decision  // "approve" or "deny"
            });
            var content = new StringContent(payload, Encoding.UTF8, "application/json");
            await _http.PostAsync($"{API_URL}/api/tasks/{taskId}/approve", content);
        }
        catch { }
    }

    /// <summary>Send a command to Orchestrator (e.g. trigger_collection).</summary>
    public async Task SendCommand(string command)
    {
        try
        {
            switch (command)
            {
                case "trigger_collection":
                    await _http.PostAsync($"{API_URL}/api/scenarios/full_collection/run",
                        new StringContent("{}", Encoding.UTF8, "application/json"));
                    break;
            }
        }
        catch { }
    }

    private async Task ConnectionLoop()
    {
        while (!_cts.IsCancellationRequested)
        {
            try
            {
                _ws = new ClientWebSocket();
                await _ws.ConnectAsync(new Uri(WS_URL), _cts.Token);
                OnStatusChanged?.Invoke(true, "WebSocket");

                // Send identity
                var hello = JsonSerializer.Serialize(new { type = "claw", version = "2.0" });
                await _ws.SendAsync(Encoding.UTF8.GetBytes(hello), WebSocketMessageType.Text, true, _cts.Token);

                // Receive loop
                var buf = new byte[8192];
                while (_ws.State == WebSocketState.Open && !_cts.IsCancellationRequested)
                {
                    var result = await _ws.ReceiveAsync(buf, _cts.Token);
                    if (result.MessageType == WebSocketMessageType.Close)
                        break;

                    var msg = Encoding.UTF8.GetString(buf, 0, result.Count);
                    HandleMessage(msg);
                }
            }
            catch (OperationCanceledException) { break; }
            catch
            {
                OnStatusChanged?.Invoke(false, "");
            }

            if (!_cts.IsCancellationRequested)
                await Task.Delay(RECONNECT_MS, _cts.Token).ContinueWith(_ => { });
        }
    }

    private async Task HealthPollLoop()
    {
        while (!_cts.IsCancellationRequested)
        {
            try
            {
                var resp = await _http.GetStringAsync($"{API_URL}/api/health");
                using var doc = JsonDocument.Parse(resp);
                var root = doc.RootElement;
                var uptime = root.TryGetProperty("uptime", out var u) ? u.GetInt32() : 0;
                var h = uptime / 3600;
                var m = (uptime % 3600) / 60;
                var detail = h > 0 ? $"{h}h{m}m" : $"{m}m";
                OnStatusChanged?.Invoke(true, detail);
            }
            catch
            {
                OnStatusChanged?.Invoke(false, "");
            }

            await Task.Delay(HEALTH_POLL_MS, _cts.Token).ContinueWith(_ => { });
        }
    }

    private void HandleMessage(string raw)
    {
        try
        {
            using var doc = JsonDocument.Parse(raw);
            var root = doc.RootElement;
            var type = root.TryGetProperty("type", out var t) ? t.GetString() ?? "" : "";

            switch (type)
            {
                case "event":
                    var evtType = root.TryGetProperty("event_type", out var et) ? et.GetString() ?? "info" : "info";
                    var title = root.TryGetProperty("title", out var ti) ? ti.GetString() ?? "" : "";
                    var body = root.TryGetProperty("body", out var bo) ? bo.GetString() ?? "" : "";
                    OnEvent?.Invoke(evtType, title, body);
                    break;

                case "approval_request":
                    var taskId = root.TryGetProperty("task_id", out var id) ? id.GetString() ?? "" : "";
                    var desc = root.TryGetProperty("description", out var d) ? d.GetString() ?? "" : "";
                    var auth = root.TryGetProperty("authority_level", out var a) ? a.GetInt32() : 5;
                    OnApprovalRequest?.Invoke(taskId, desc, auth);
                    break;

                case "notification":
                    var nTitle = root.TryGetProperty("title", out var nt) ? nt.GetString() ?? "" : "";
                    var nBody = root.TryGetProperty("body", out var nb) ? nb.GetString() ?? "" : "";
                    OnEvent?.Invoke("notification", nTitle, nBody);
                    break;
            }
        }
        catch { }
    }
}
