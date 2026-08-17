@echo off
rem ============================================================
rem  一键启动 —— 双击即可使用，无需任何专业知识
rem  本脚本会自动找到或准备好运行环境，然后启动程序
rem ============================================================
chcp 65001 >nul
title A股蜡烛图形态筛选工具 - 启动中
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PY="

rem 1) 程序自带的运行环境（测试机无需安装任何东西）
if exist "%~dp0runtime\python.exe" (
    set "PY=%~dp0runtime\python.exe"
    goto :found
)

rem 2) 本机已有的运行环境
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    goto :found
)
if exist "C:\Users\Edwar\.workbuddy\binaries\python\envs\default\Scripts\python.exe" (
    set "PY=C:\Users\Edwar\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
    goto :found
)

rem 3) 系统里已安装的 Python
where python >nul 2>nul
if %errorlevel%==0 (
    set "PY=python"
    goto :found
)

rem ---- 都没有：自动下载一个便携运行环境 ----
echo.
echo  正在准备运行环境（首次需要联网下载，约 1~3 分钟）...
echo  请保持网络畅通，不要关闭本窗口。
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\下载运行环境.ps1"
if exist "%~dp0runtime\python.exe" (
    set "PY=%~dp0runtime\python.exe"
    goto :found
)

echo.
echo  ⚠️ 运行环境准备失败，请检查网络后重新双击本文件。
echo  （若反复失败，可右键本文件 → 属性 → 勾选“解除锁定” → 确定，再双击。）
pause
exit /b 1

:found
echo.
echo   即将使用的运行环境：
echo     %PY%
echo.
"%PY%" "%~dp0launcher.py"
set "RC=%errorlevel%"
if not "%RC%"=="0" (
    echo.
    echo  ⚠️ 启动时遇到问题（错误码 %RC%），请把本程序目录里的 launcher_debug.log 发来，或截图本窗口。
    pause
)
endlocal
