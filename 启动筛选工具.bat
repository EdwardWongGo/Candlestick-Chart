@echo off
rem 编码：GBK（Windows 默认代码页）
setlocal enabledelayedexpansion
title A股蜡烛图形态筛选工具 · 启动器
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=gbk"

REM ==========================================================
REM  基础配置
REM ==========================================================
set "LOG_FILE=%~dp0启动日志.log"
set "PORT=8000"

REM 启用控制台快速编辑模式（可用鼠标选中复制窗口内文字）
reg add "HKCU\Console" /v QuickEdit /t REG_DWORD /d 1 /f >nul 2>&1

REM ==========================================================
REM  日志初始化（每次启动覆盖旧日志，保留本次完整输出）
REM ==========================================================
> "%LOG_FILE%" echo [%date% %time%] ===== 启动 A股蜡烛图形态筛选工具 =====
>> "%LOG_FILE%" echo 启动目录: %~dp0
>> "%LOG_FILE%" echo ============================================

echo ==========================================
echo   A股蜡烛图形态筛选工具 · 启动器
echo ==========================================
echo.

REM ==========================================================
REM  [1/4] Python 探测：依次测试候选，取第一个“存在且有依赖”的
REM   候选1: 项目虚拟环境（install.bat 创建）
REM   候选2: 本机工作环境（%USERPROFILE%\.workbuddy\binaries\...，存在才试）
REM   候选3: 系统 PATH 中的 python
REM ==========================================================
set "PY="
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
>> "%LOG_FILE%" echo [1/4] 使用 Python: !PY!
echo [1/4] Python 环境已就绪：!PY!

REM ==========================================================
REM  [2/4] 检查项目文件
REM ==========================================================
if not exist "run.py"    goto :no_files
if not exist "config.py" goto :no_files
if not exist "web\index.html" goto :no_files
echo [2/4] 项目文件完整
>> "%LOG_FILE%" echo [2/4] 项目文件完整

REM ==========================================================
REM  [3/4] 端口检查（占用则自动改用 8001）
REM ==========================================================
netstat -ano | findstr ":%PORT%" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [提示] 端口 %PORT% 已被占用，自动改用端口 8001
    >> "%LOG_FILE%" echo [提示] 端口 %PORT% 被占用，改用 8001
    set "PORT=8001"
)

REM ==========================================================
REM  [4/4] 启动服务（后台运行，输出写日志）
REM ==========================================================
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

:no_python_ready
echo [错误] 未找到安装了依赖（flask / mootdx / pandas）的 Python 环境
echo        请先双击 install.bat 一键安装（自动创建虚拟环境并装依赖）
echo        或安装 Python 3.10+ 后重新运行 install.bat
>> "%LOG_FILE%" echo [错误] 未找到可用 Python 或依赖未安装，请先运行 install.bat
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
