@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title A股蜡烛图形态筛选工具 - 一键安装
cd /d "%~dp0"

echo ==========================================
echo    A股蜡烛图形态筛选工具 · 一键安装
echo ==========================================
echo.

REM ==========================================================
REM 1. 前置检查：Python
REM ==========================================================
echo [1/5] 检查 Python 环境...
set "PY=python"
%PY% --version >nul 2>nul
if errorlevel 1 (
    echo.
    echo   [错误] 未检测到 Python 命令。
    echo   请先安装 Python 3.10 或更高版本：
    echo     下载地址: https://www.python.org/downloads/
    echo     安装时务必勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)
for /f "usebackq tokens=*" %%v in (`%PY% --version 2^>^&1`) do set "PYVER=%%v"
echo   已检测到 %PYVER%

REM ==========================================================
REM 2. 创建虚拟环境（隔离依赖，避免污染系统 Python）
REM ==========================================================
echo.
echo [2/5] 创建虚拟环境（.venv）...
if exist ".venv\Scripts\python.exe" (
    echo   虚拟环境已存在，跳过创建
) else (
    %PY% -m venv .venv
    if errorlevel 1 (
        echo   [错误] 虚拟环境创建失败，请检查 Python 安装是否完整
        pause
        exit /b 1
    )
    echo   虚拟环境创建成功
)
set "VPY=.venv\Scripts\python.exe"
set "VPIP=.venv\Scripts\pip.exe"

REM ==========================================================
REM 3. 安装依赖（优先国内镜像，失败自动回退官方源）
REM ==========================================================
echo.
echo [3/5] 安装依赖（首次约需 1~3 分钟，请耐心等待）...
echo   使用清华 PyPI 镜像加速下载...
"%VPIP%" install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple >nul 2>nul
"%VPIP%" install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo   [提示] 清华镜像安装失败，尝试官方源...
    "%VPIP%" install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo   [错误] 依赖安装失败，请检查网络连接后重新运行本脚本
        pause
        exit /b 1
    )
)
echo   依赖安装完成

REM ==========================================================
REM 4. 生成数据目录与必要文件
REM ==========================================================
echo.
echo [4/5] 生成数据目录（data\daily weekly monthly）...
if not exist "data" mkdir "data"
for %%d in (daily weekly monthly) do (
    if not exist "data\%%d" mkdir "data\%%d"
)
if not exist "data\README.md" (
    echo # data 目录 - 本地数据存放> "data\README.md"
    echo 本目录存放筛选工具的本地数据（K 线缓存 / 股票池 / 同步记录）。>> "data\README.md"
    echo 由一键安装脚本自动创建。>> "data\README.md"
)
echo   数据目录就绪
echo.
echo   检查项目文件完整性...
set "MISSING="
if not exist "run.py"            set "MISSING=%MISSING% run.py"
if not exist "config.py"         set "MISSING=%MISSING% config.py"
if not exist "requirements.txt"  set "MISSING=%MISSING% requirements.txt"
if not exist "web\index.html"    set "MISSING=%MISSING% web\index.html"
if not exist "app\server.py"     set "MISSING=%MISSING% app\server.py"
if defined MISSING (
    echo   [警告] 以下必要文件缺失，程序可能无法运行：%MISSING%
    echo   请确认是从 GitHub 完整下载/克隆的项目目录。
) else (
    echo   项目文件完整
)

REM ==========================================================
REM 5. 验证安装（形态引擎自检）
REM ==========================================================
echo.
echo [5/5] 运行形态引擎自检，验证安装...
"%VPY%" -c "import sys; sys.path.insert(0,'.'); from app.selftest import run_selftest; r=run_selftest(); print('   自检结果: ' + str(r['passed']) + '/' + str(r['total']) + ' 通过')"
if errorlevel 1 (
    echo   [警告] 自检运行异常，请查看上方错误信息
) else (
    echo   自检通过，安装正常
)

echo.
echo ==========================================
echo    安装完成！
echo.
echo    下一步：双击「启动筛选工具.bat」启动工具
echo    或命令行运行: .venv\Scripts\python run.py
echo ==========================================
echo.
pause
endlocal
