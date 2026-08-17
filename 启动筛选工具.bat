@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
REM 优先使用一键安装脚本（install.bat）创建的虚拟环境，其次回退到系统 Python
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" run.py
pause
