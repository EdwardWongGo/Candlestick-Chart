# -*- coding: utf-8 -*-
"""无黑窗口的一键启动器（headless）。

由「一键启动.vbs」用 pythonw 调用，全程不弹出命令行窗口。
所有过程记录到 launcher_debug.log；出错时用系统原生消息框提示用户
（通过 ctypes 调用 MessageBoxW，无需 tkinter）。
最终效果与「启动筛选工具.bat」一致：在本机 8000 端口启动同一个 Web 服务，
并自动打开浏览器，只是整个过程没有黑窗口、异常会被清楚地弹窗告知。
"""

import os
import socket
import subprocess
import sys
import time
import traceback
import webbrowser

try:
    import ctypes
    _HAS_CTYPES = True
except Exception:
    _HAS_CTYPES = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REQ_FILE = os.path.join(BASE_DIR, "requirements.txt")
RUN_FILE = os.path.join(BASE_DIR, "run.py")
APP_URL = "http://127.0.0.1:8000"
DEBUG_LOG = os.path.join(BASE_DIR, "launcher_debug.log")
SERVER_LOG = os.path.join(BASE_DIR, "server.log")

REQUIRED_MODULES = ["flask", "pandas", "numpy", "mootdx", "requests"]

TITLE = "A股蜡烛图形态筛选工具"

# Windows 子进程标志：不分配控制台窗口
CREATE_NO_WINDOW = 0x08000000


# ---------------------------------------------------------------------------
# 日志与提示
# ---------------------------------------------------------------------------
def _log(msg: str):
    """把信息追加写入调试日志文件（任何失败都不会影响主流程）。"""
    try:
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _msgbox(text: str, kind: str = "error"):
    """用系统原生消息框提示用户（不依赖任何第三方库）。"""
    if not _HAS_CTYPES:
        _log("【提示】" + text)
        return
    flags = 0x40 if kind == "info" else 0x10  # 0x40=信息, 0x10=错误
    try:
        ctypes.windll.user32.MessageBoxW(0, text, TITLE, flags)
    except Exception:
        _log("【提示】" + text)


def _log_head():
    try:
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 60 + "\n")
            f.write("启动时间: " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
            f.write("Python: " + sys.executable + "\n")
            f.write("版本: " + sys.version.replace("\n", " ") + "\n")
            f.write("工作目录: " + BASE_DIR + "\n")
            f.write("=" * 60 + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _check_modules():
    """返回缺失的必需组件名（内部用）。"""
    missing = []
    for m in REQUIRED_MODULES:
        try:
            __import__(m)
        except Exception:
            missing.append(m)
    return missing


def _port_in_use(port: int = 8000, host: str = "127.0.0.1") -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.6)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def _check_network() -> bool:
    try:
        import urllib.request
        urllib.request.urlopen("https://www.baidu.com", timeout=5)
        return True
    except Exception:
        return False


def _open_browser(url: str):
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _run_pip_install() -> bool:
    """静默安装依赖，过程写入调试日志。返回是否成功。"""
    py = sys.executable
    try:
        with open(DEBUG_LOG, "a", encoding="utf-8") as logf:
            logf.write("开始安装依赖（pip install -r requirements.txt）...\n")
            proc = subprocess.run(
                [py, "-m", "pip", "install", "-r", REQ_FILE],
                cwd=BASE_DIR,
                stdout=logf,
                stderr=subprocess.STDOUT,
            )
        return proc.returncode == 0
    except Exception as e:
        _log("      pip 安装过程异常: " + str(e))
        return False


def _start_server():
    """以后台、无窗口方式启动 run.py，输出重定向到 server.log。"""
    py = sys.executable  # 自身即 pythonw，无控制台
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # 把项目目录加入模块搜索路径，避免嵌入版 Python 找不到 config / app
    env["PYTHONPATH"] = BASE_DIR + (";" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    try:
        with open(SERVER_LOG, "w", encoding="utf-8") as out:
            proc = subprocess.Popen(
                [py, RUN_FILE],
                cwd=BASE_DIR,
                env=env,
                stdout=out,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW,
            )
        return proc
    except Exception as e:
        _log("      启动子进程失败: " + str(e))
        _log(traceback.format_exc())
        return None


def _server_log_tail(n: int = 30) -> str:
    try:
        with open(SERVER_LOG, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return "".join(lines[-n:])
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    # 已经运行：直接打开浏览器（与启动筛选工具.bat 行为一致）
    if _port_in_use():
        _log("检测到 8000 端口已被占用，视为已在运行，直接打开浏览器。")
        _open_browser(APP_URL)
        return

    # 第 1 步：检查并补齐依赖
    missing = _check_modules()
    if missing:
        _log("缺少依赖: " + ", ".join(missing))
        if not _check_network():
            _msgbox("电脑目前好像连不上网，无法自动补齐运行所需的文件。\n\n"
                    "请确认能正常打开网页后，重新双击「一键启动」。")
            return
        _log("开始联网安装缺失的依赖...")
        if not _run_pip_install() or _check_modules():
            _msgbox("运行所需的文件没有安装成功。\n\n"
                    "请检查网络（或暂时关闭代理 / 防火墙）后，重新双击「一键启动」。\n\n"
                    "详细原因见程序目录里的：\n" + DEBUG_LOG)
            return
        _log("依赖安装完成。")

    # 第 2 步：初始化数据目录
    try:
        os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    except Exception as e:
        _log("数据目录创建失败: " + str(e))

    # 第 3 步：后台启动服务（无窗口）
    _log("正在后台启动服务（无命令行窗口）...")
    proc = _start_server()
    if proc is None:
        _msgbox("启动服务时遇到问题，请查看日志：\n" + DEBUG_LOG)
        return

    # 第 4 步：等待端口就绪
    ok = False
    for _ in range(120):  # 最多等待约 60 秒
        if _port_in_use():
            ok = True
            break
        if proc.poll() is not None:
            break
        time.sleep(0.5)

    if not ok:
        tail = _server_log_tail()
        _msgbox("服务未能正常启动。\n\n"
                "可能是网络 / 数据源暂时不可用。详细错误见：\n" + DEBUG_LOG +
                "\n\n最近日志：\n" + tail)
        return

    # 第 5 步：打开浏览器（与启动筛选工具.bat 一致）
    _open_browser(APP_URL)
    _log("服务已启动，浏览器已打开：" + APP_URL)


if __name__ == "__main__":
    _log_head()
    try:
        main()
    except Exception:
        # 任何未预料的错误都原样记录，并用弹窗清楚告知，绝不让窗口一闪而过
        _log("【未预料的错误】")
        _log(traceback.format_exc())
        _msgbox("启动过程中出现了意外问题。\n\n"
                "请把程序目录里的「launcher_debug.log」发给开发人员，"
                "就能帮你准确定位并解决。\n\n" + DEBUG_LOG)
