# Wake Watcher — 监听 tmp/wake/ 目录，自动启动 Claude Code 会话
# 用法：在宿主机后台运行
#   powershell -File bin/wake-watcher.ps1
#   或加入 Windows 启动项 / 计划任务

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$wakeDir = Join-Path $repoRoot "tmp\wake"
$pollInterval = 5  # 秒

Write-Host "[wake-watcher] Monitoring $wakeDir (every ${pollInterval}s)"
Write-Host "[wake-watcher] Press Ctrl+C to stop"

# 确保目录存在
if (-not (Test-Path $wakeDir)) {
    New-Item -ItemType Directory -Path $wakeDir -Force | Out-Null
}

while ($true) {
    $files = Get-ChildItem -Path $wakeDir -Filter "*.json" -File |
        Where-Object { $_.Name -notmatch "\.response\.json$" }

    foreach ($file in $files) {
        try {
            $content = Get-Content -Path $file.FullName -Raw | ConvertFrom-Json

            if ($content.status -ne "pending") {
                continue
            }

            $task = $content.task
            $context = $content.context
            $chatId = $content.chat_id
            $timestamp = Get-Date -Format "HH:mm:ss"

            Write-Host "[$timestamp] Wake request: $task"

            # 标记为 processing
            $content.status = "processing"
            $content | ConvertTo-Json -Depth 10 | Set-Content -Path $file.FullName -Encoding UTF8

            # 构建 Claude Code 提示词
            $prompt = @"
[Wake from Telegram] chat_id=$chatId

Task: $task

Context: $context

Instructions:
- You were woken up by the Telegram bot because it needs help with something it can't do alone.
- Complete the task, commit if needed, then write a brief summary.
- The summary will be sent back to the user on Telegram.
- Work in the orchestrator repo: $repoRoot
"@

            # 在新终端窗口启动 Claude Code
            $promptFile = Join-Path $wakeDir ($file.BaseName + ".prompt.txt")
            $prompt | Set-Content -Path $promptFile -Encoding UTF8

            # 启动 Claude Code（新窗口，非阻塞）
            $claudeCmd = "cd `"$repoRoot`" && type `"$promptFile`" | claude --print 2>`$null && echo DONE || echo FAILED"
            Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "title Claude Wake: $($task.Substring(0, [Math]::Min(40, $task.Length))) && $claudeCmd > `"$($file.FullName -replace '\.json$', '.output.txt')`" && pause"

            Write-Host "[$timestamp] Claude Code session started"

            # 标记为 dispatched（实际完成状态由 Claude Code 写回）
            $content.status = "dispatched"
            $content | ConvertTo-Json -Depth 10 | Set-Content -Path $file.FullName -Encoding UTF8

        } catch {
            Write-Host "[ERROR] Failed to process $($file.Name): $_"
        }
    }

    Start-Sleep -Seconds $pollInterval
}
