@echo off
title WeChat ClawBot Login
cd /d "%~dp0"
python -m src.channels.wechat.login
pause
