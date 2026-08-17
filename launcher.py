# -*- coding: utf-8 -*-
"""
傻瓜式一键启动器

你不需要懂任何专业知识。双击「一键启动.bat」后，本程序会自动：
  1. 检查运行环境是否完整
  2. 不完整就自动下载补齐（全程中文提示，无需你动手）
  3. 检查网络、初始化数据目录
  4. 启动股票筛选工具，并自动打开浏览器

整个过程中出现任何问题，都会用大白话告诉你该怎么做。
（若仍失败，本程序会把详细原因写进「launcher_debug.log」，方便排查。）
"""

import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser

# 当前程序所在目录（即项目根目录）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REQ_FILE = os.path.join(BASE_DIR, "requirements.txt")
RUN_FILE = os.path.join(BASE_DIR, "run.py")
APP_URL = "http://127.0.0.1:8000"

# 运行所需的组件（内部用，不会展示给用户）
REQUIRED_MODULES = ["flask", "pandas", "numpy", "mootdx", "requests"]

# 调试日志文件（任何失败都会写到这里，方便用户反馈）
DEBUG_LOG = os.path.join(BASE_DIR, "launcher_debug.log")


# ---------------------------------------------------------------------------
# 调试日志
# ---------------------------------------------------------------------------
def _log(msg: str):
    """同时打印到屏幕，并追加写入调试日志文件。"""
    print(msg)
    try:
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


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
# 小工具
# ---------------------------------------------------------------------------
def _line(ch="=", n=52):
    print(ch * n)


def _section(num, title):
    print()
    _line()
    print(f"  第 {num} 步  {title}")
    _line()


def _spinner_run(cmd, cwd=None):
    """在后台运行一个命令，期间只显示转圈动画，不显示任何专业输出。"""
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        _log(f"      （后台命令启动失败：{e}）")
        return 1
    frames = ["|", "/", "-", "\\"]
    i = 0
    while proc.poll() is None:
        print(f"\r      正在处理，请稍候 {frames[i % 4]}", end="", flush=True)
        time.sleep(0.15)
        i += 1
    print("\r" + " " * 30 + "\r", end="", flush=True)
    return proc.returncode


def _check_modules():
    """检查运行所需组件是否齐全，返回缺失的组件名（内部用）。"""
    missing = []
    for m in REQUIRED_MODULES:
        try:
            __import__(m)
        except Exception:
            missing.append(m)
    return missing


def _port_in_use(port=8000):
    try:
        with socket.socket(socket.AF_INET, socket.STREAM) as s:
            s.settimeout(0.6)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False


def _check_network():
    try:
        import urllib.request
        urllib.request.urlopen("https://www.baidu.com", timeout=5)
        return True
    except Exception:
        return False


def _open_browser(url):
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _press_enter_to_exit():
    try:
        input("\n      按回车键关闭本窗口...")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    os.system("cls" if os.name == "nt" else "clear")

    # 标题
    print()
    _line("★")
    print("           A股蜡烛图形态筛选工具")
    print("        本程序会自动完成所有准备工作")
    print("            你只需要耐心等待即可")
    _line("★")

    # 第 1 步：检查运行环境
    _section(1, "检查运行环境")
    missing = _check_modules()
    if missing:
        print("      检测到运行所需的文件还不完整。")
        print("      不用担心，接下来会自动补齐。")

        # 第 2 步：自动下载补齐
        _section(2, "自动补齐运行文件")
        if not _check_network():
            print("      ⚠️  电脑目前好像连不上网。")
            print()
            print("      补齐运行文件需要联网，请按下面提示检查：")
            print("        1. 确认电脑能正常打开网页")
            print("        2. 连上网络后，重新双击「一键启动.bat」")
            _press_enter_to_exit()
            return

        print("      正在下载运行所需的文件（首次约需几分钟）。")
        print("      请保持网络畅通，期间不要关闭本窗口。")
        code = _spinner_run(
            [sys.executable, "-m", "pip", "install", "-r", REQ_FILE],
            cwd=BASE_DIR,
        )
        if code != 0 or _check_modules():
            print()
            print("      ⚠️  文件下载好像没有成功。")
            print()
            print("      请按下面提示排查：")
            print("        1. 检查电脑能否正常上网")
            print("        2. 关闭代理或防火墙软件后重试")
            print("        3. 重新双击「一键启动.bat」再试一次")
            _press_enter_to_exit()
            return
        print("      ✅ 运行文件已准备完毕。")
    else:
        print("      ✅ 运行环境完整，无需额外操作。")

    # 第 3 步：初始化数据目录
    _section(3, "初始化数据目录")
    try:
        os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
        print("      ✅ 数据目录已就绪。")
    except Exception as e:
        print("      ⚠️  数据目录创建失败，请检查是否有写入权限。")
        _log(f"      （数据目录错误：{e}）")

    # 第 4 步：启动程序
    _section(4, "启动程序")

    # 如果已经在运行，直接打开浏览器
    if _port_in_use():
        print("      ✅ 程序已经在运行了，直接为你打开浏览器。")
        _open_browser(APP_URL)
        _press_enter_to_exit()
        return

    print("      正在启动，稍后会自动打开浏览器...")
    print("      （浏览器打开后即可使用；关闭本窗口即可停止程序）")
    print()
    print("      提示：详细使用说明见「使用说明.html」，双击即可打开。")
    print()

    # 用当前 Python 运行 run.py（阻塞；关闭窗口即停止）
    try:
        proc = subprocess.Popen([sys.executable, RUN_FILE], cwd=BASE_DIR)
        # 等服务真正起来后，再确保浏览器被打开（双保险）
        for _ in range(40):
            if _port_in_use():
                break
            if proc.poll() is not None:
                break
            time.sleep(0.5)
        else:
            pass
        _open_browser(APP_URL)
        proc.wait()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        _log(f"      ⚠️  启动时遇到问题：{e}")
        _log(traceback.format_exc())
        print("      请关闭本窗口后，重新双击「一键启动.bat」再试。")
        print("      若仍不行，请把本程序目录里的「launcher_debug.log」发来。")
        _press_enter_to_exit()
        return

    print("\n      程序已停止，感谢使用！")
    _press_enter_to_exit()


if __name__ == "__main__":
    _log_head()
    try:
        main()
    except Exception:
        # 任何未预料到的错误，都原样记录并友好提示，绝不让窗口一闪而过
        _log("【未预料的错误】")
        _log(traceback.format_exc())
        print()
        print("      ⚠️  启动过程中出现了意外问题。")
        print("      请把本程序目录里的「launcher_debug.log」文件发来，")
        print("      我就能帮你准确定位并解决。")
        _press_enter_to_exit()
