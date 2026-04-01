# Wake Remote — launch claude interactive session with /remote-control.
param(
    [string]$Name = "Orchestrator",
    [int]$Sid = 0
)

$ErrorActionPreference = "Stop"

try {
    $root = (Resolve-Path "$PSScriptRoot\..").Path
    $logDir = Join-Path $root "tmp\wake"
    $logFile = Join-Path $logDir "remote-$Sid.log"

    New-Item -ItemType Directory -Path $logDir -Force | Out-Null

    # Write status BEFORE Start-Transcript (direct to file, guaranteed)
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') wake-remote starting sid=$Sid name=$Name" | Set-Content $logFile -Encoding utf8
    "root=$root" | Add-Content $logFile -Encoding utf8
    "claude=$(Get-Command claude -EA SilentlyContinue | Select-Object -Expand Source)" | Add-Content $logFile -Encoding utf8

    # Set git bash path
    if (-not $env:CLAUDE_CODE_GIT_BASH_PATH) {
        $gitBash = "D:\Program Files\Git\bin\bash.exe"
        if (Test-Path $gitBash) {
            $env:CLAUDE_CODE_GIT_BASH_PATH = $gitBash
        }
    }
    "gitbash=$env:CLAUDE_CODE_GIT_BASH_PATH" | Add-Content $logFile -Encoding utf8

    Write-Host "=== Wake #$Sid Remote Control ===" -ForegroundColor Cyan
    Write-Host "Project: $root"
    Write-Host ""

    Set-Location $root
    "launching claude..." | Add-Content $logFile -Encoding utf8

    # Start transcript for output capture (best-effort)
    Start-Transcript -Path (Join-Path $logDir "remote-$Sid-transcript.log") -Force | Out-Null

    # Launch claude with /remote-control as initial prompt
    claude --name $Name "/remote-control"

    Stop-Transcript -ErrorAction SilentlyContinue | Out-Null

} catch {
    $errMsg = "ERROR: $($_.Exception.Message)"
    Write-Host $errMsg -ForegroundColor Red
    if ($logFile) {
        $errMsg | Add-Content $logFile -Encoding utf8
    }
    Read-Host "Press Enter to close"
}
