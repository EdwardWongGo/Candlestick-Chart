@echo off
chcp 936 >nul
setlocal enabledelayedexpansion
title 停止 A股蜡烛图形态筛选工具
cd /d "%~dp0"

set "PY="
set "CAND1=.venv\Scripts\python.exe"
set "CAND2=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

if exist "%CAND1%" set "PY=%CAND1%"
if not defined PY if exist "%CAND2%" set "PY=%CAND2%"
if not defined PY set "PY=python"

echo ==========================================
echo   停止 A股蜡烛图形态筛选工具
echo ==========================================
echo.

"%PY%" stop_service.py

echo.
pause
endlocal
