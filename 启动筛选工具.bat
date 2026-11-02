@echo off
chcp 936 >nul
setlocal enabledelayedexpansion
title A股蜡烛图形态筛选工具 · 启动器
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=gbk"
set "PYTHONUNBUFFERED=1"

set "LOG_FILE=%~dp0启动日志.log"
set "SVC_LOG=%~dp0服务日志.log"
set "PORT=8000"

reg add "HKCU\Console" /v QuickEdit /t REG_DWORD /d 1 /f >nul 2>&1

> "%LOG_FILE%" echo [%date% %time%] ===== 启动 A股蜡烛图形态筛选工具 =====
>> "%LOG_FILE%" echo 启动目录: %~dp0 2>nul
>> "%LOG_FILE%" echo ============================================ 2>nul

echo ==========================================
echo   A股蜡烛图形态筛选工具 · 启动器
echo ==========================================
echo.

set "PY="
set "PYW="
set "CAND1=.venv\Scripts\python.exe"
set "CAND2=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
set "CAND3=python"

if exist "%CAND1%" (
    "%CAND1%" -c "import flask,mootdx,pandas" >nul 2>&1
    if not errorlevel 1 set "PY=%CAND1%"
)
if not defined PY if exist "%CAND2%" (
    "%CAND2%" -c "import flask,mootdx,pandas" >nul 2>&1
    if not errorlevel 1 set "PY=%CAND2%"
)
if not defined PY (
    %CAND3% -c "import flask,mootdx,pandas" >nul 2>&1
    if not errorlevel 1 set "PY=%CAND3%"
)

if not defined PY goto :no_python_ready

REM 用 pythonw.exe（无控制台解释器）启动服务：关闭本窗口不会连带杀死服务
for %%i in ("!PY!") do set "PYDIR=%%~dpi"
if exist "!PYDIR!pythonw.exe" (
    set "PYW=!PYDIR!pythonw.exe"
) else (
    set "PYW=!PY!"
)

echo [1/4] Python 环境已就绪
>> "%LOG_FILE%" echo [1/4] 使用 Python: !PY! 2>nul
>> "%LOG_FILE%" echo [1/4] 服务解释器: !PYW! 2>nul

if not exist "run.py"    goto :no_files
if not exist "config.py" goto :no_files
if not exist "web\index.html" goto :no_files
echo [2/4] 项目文件完整
>> "%LOG_FILE%" echo [2/4] 项目文件完整 2>nul

REM 端口占用则自动切到 8001
set "NETFOUND="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') do set "NETFOUND=%%a"
if defined NETFOUND (
    echo [提示] 端口 %PORT% 已被占用（工具可能已在运行），改用端口 8001
    >> "%LOG_FILE%" echo [提示] 端口 %PORT% 被占用，改用 8001 2>nul
    set "PORT=8001"
)

echo [3/4] 启动服务（端口 !PORT!，后台常驻）
>> "%LOG_FILE%" echo [3/4] 启动服务（端口 !PORT!） 2>nul
>> "%LOG_FILE%" echo -------------------------------------------- 2>nul
REM 服务输出单独写「服务日志.log」：启动器日志若被服务进程持有写句柄，后续追加会失败
start "" "!PYW!" run.py --port !PORT! --no-browser > "!SVC_LOG!" 2>&1

REM 等待端口就绪（调用 check_port.py 探测，避免内联代码的括号问题）
echo [4/4] 等待服务就绪…
set "READY="
for /l %%i in (1,1,20) do (
    if not defined READY (
        "%PY%" check_port.py !PORT! >nul 2>&1
        if not errorlevel 1 set "READY=1"
        if not defined READY ping -n 2 127.0.0.1 >nul
    )
)

if not defined READY goto :timeout

:started
echo.
echo ==========================================
echo   [成功] 服务已启动：http://127.0.0.1:!PORT!
echo   服务在后台运行，关闭本窗口不会停止服务
echo   需要停止时双击「停止筛选工具.bat」
echo ==========================================
>> "%LOG_FILE%" echo [成功] 服务已启动：http://127.0.0.1:!PORT! 2>nul
start "" "http://127.0.0.1:!PORT!"
goto :done

:timeout
echo [失败] 等待超时，服务未能监听端口 !PORT!
>> "%LOG_FILE%" echo [失败] 等待超时，服务未能监听端口 !PORT! 2>nul
goto :fail

:no_python_ready
echo [失败] 未找到装好依赖（flask / mootdx / pandas）的 Python 环境
echo        请先双击 install.bat 安装依赖
>> "%LOG_FILE%" echo [失败] 未找到可用 Python 环境 2>nul
goto :fail

:no_files
echo [失败] 项目文件不完整（缺少 run.py / config.py / web\index.html）
>> "%LOG_FILE%" echo [失败] 项目文件不完整 2>nul
goto :fail

:fail
echo.
echo ==========================================
echo   [启动失败] 详见日志：!LOG_FILE!
echo ==========================================

:done
echo.
pause
endlocal
