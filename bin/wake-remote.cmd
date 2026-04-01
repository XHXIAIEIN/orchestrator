@echo off
REM Wake Remote launcher — thin wrapper for wt.exe compatibility.
REM Usage: wake-remote.cmd <Name> <Sid>
set NAME=%~1
set SID=%~2
if "%NAME%"=="" set NAME=Orchestrator
if "%SID%"=="" set SID=0

powershell -ExecutionPolicy Bypass -File "%~dp0wake-remote.ps1" -Name %NAME% -Sid %SID%
if errorlevel 1 pause
