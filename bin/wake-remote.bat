@echo off
REM Wake Remote launcher — called by wt.exe, delegates to PS1.
REM Usage: wake-remote.bat <session_id>
set SID=%1
if "%SID%"=="" set SID=0
set ROOT=%~dp0..
cd /d "%ROOT%"
powershell -ExecutionPolicy Bypass -File "%~dp0wake-remote.ps1" -Name "Orchestrator-%SID%" -Sid %SID%
if errorlevel 1 (
    echo.
    echo [wake-remote] Script exited with error. Press any key to close.
    pause >nul
)
