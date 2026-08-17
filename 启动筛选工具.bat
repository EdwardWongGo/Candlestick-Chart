@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title A股蜡烛图形态筛选工具 · 启动器
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

REM ==========================================================
REM  基础配置
REM ==========================================================
set "LOG_FILE=%~dp0启动日志.log"
set "PORT=8000"
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

REM 启用控制台快速编辑模式（可用鼠标选中复制窗口内文字）
reg add "HKCU\Console" /v QuickEdit /t REG_DWORD /d 1 /f >nul 2>&1

REM ==========================================================
REM  日志初始化（每次启动覆盖旧日志，保留本次完整输出）
REM ==========================================================
> "%LOG_FILE%" echo [%date% %time%] ===== 启动 A股蜡烛图形态筛选工具 =====
>> "%LOG_FILE%" echo 启动目录: %~dp0
>> "%LOG_FILE%" echo Python:   %PY%
>> "%LOG_FILE%" echo 端口:     %PORT%
>> "%LOG_FILE%" echo ============================================

echo ==========================================
echo   A股蜡烛图形态筛选工具 · 启动器
echo ==========================================
echo.

REM ==========================================================
REM  1. 检查 Python 环境
REM ==========================================================
"%PY%" --version >nul 2>&1
if errorlevel 1 goto :no_python
for /f "usebackq tokens=*" %%v in (`"%PY%" --version 2^>^&1`) do set "PYVER=%%v"
echo [1/4] Python 环境：!PYVER!
>> "%LOG_FILE%" echo [1/4] Python 环境：!PYVER!

REM ==========================================================
REM  2. 检查依赖包
REM ==========================================================
"%PY%" -c "import flask, mootdx, pandas" >nul 2>&1
if errorlevel 1 goto :no_deps
echo [2/4] 依赖包已就绪（flask / mootdx / pandas）
>> "%LOG_FILE%" echo [2/4] 依赖包已就绪

REM ==========================================================
REM  3. 检查项目文件
REM ==========================================================
if not exist "run.py"    goto :no_files
if not exist "config.py" goto :no_files
if not exist "web\index.html" goto :no_files
echo [3/4] 项目文件完整
>> "%LOG_FILE%" echo [3/4] 项目文件完整

REM ==========================================================
REM  4. 端口检查 + 启动服务
REM ==========================================================
netstat -ano | findstr ":%PORT%" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [提示] 端口 %PORT% 已被占用，自动改用端口 8001
    >> "%LOG_FILE%" echo [提示] 端口 %PORT% 被占用，改用 8001
    set "PORT=8001"
)
echo [4/4] 正在启动服务（端口 !PORT!），运行日志写入：!LOG_FILE!
>> "%LOG_FILE%" echo [4/4] 启动服务（端口 !PORT!）
>> "%LOG_FILE%" echo --------------------------------------------
start "A股蜡烛图服务" /b "%PY%" run.py --port !PORT! --no-browser >> "%LOG_FILE%" 2>&1

REM 等待服务就绪（最多约 15 秒）
set "READY="
for /l %%i in (1,1,15) do (
    ping -n 2 127.0.0.1 >nul
    netstat -ano | findstr ":!PORT!" | findstr "LISTENING" >nul 2>&1
    if not errorlevel 1 set "READY=1"
    if defined READY goto :started
)

REM ==========================================================
REM  启动失败提示
REM ==========================================================
echo [错误] 服务启动超时，未能监听端口 !PORT!
>> "%LOG_FILE%" echo [错误] 服务启动超时，未能监听端口 !PORT!
goto :fail

:no_python
echo [错误] 未找到可用的 Python 环境（!PY!）
echo        请先双击 install.bat 一键安装，或安装 Python 3.10 及以上
echo        下载地址：https://www.python.org/downloads/
>> "%LOG_FILE%" echo [错误] 未找到 Python 环境（!PY!）
>> "%LOG_FILE%" echo [提示] 请先运行 install.bat 一键安装
goto :fail

:no_deps
echo [错误] 依赖包未安装（flask / mootdx / pandas）
echo        请先双击 install.bat 一键安装依赖
>> "%LOG_FILE%" echo [错误] 依赖包未安装（flask / mootdx / pandas）
goto :fail

:no_files
echo [错误] 项目文件不完整（缺少 run.py / config.py / web\index.html）
echo        请确认是从 GitHub 完整下载的项目目录
>> "%LOG_FILE%" echo [错误] 项目文件不完整
goto :fail

:started
echo.
echo ==========================================
echo   [成功] 服务已启动，正在打开浏览器...
echo ==========================================
>> "%LOG_FILE%" echo [成功] 服务已启动：http://127.0.0.1:!PORT!
start "" "http://127.0.0.1:!PORT!"
echo.
echo 提示：
echo   · 浏览器未自动打开时，请手动访问 http://127.0.0.1:!PORT!
echo   · 关闭本窗口即停止服务
echo   · 完整运行日志已保存到同目录「启动日志.log」
echo     （如遇问题，把该日志文件发给开发者即可定位）
goto :done

:fail
echo.
echo ==========================================
echo   [启动失败] 请根据上方错误提示处理
echo   完整日志已保存到：!LOG_FILE!
echo   如无法解决，请将日志文件发送给开发者
echo ==========================================

:done
echo.
pause
endlocal
