# -*- coding: utf-8 -*-
"""
停止后台服务 —— 找到监听 8000/8001 的进程并结束

由「停止筛选工具.bat」调用，也可直接运行：
    python stop_service.py

Author: HZQ
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys

PORTS = (8000, 8001)


def _port_open(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False
    finally:
        s.close()


def _pids_by_netstat() -> dict:
    """{pid: [port, ...]} —— 解析 netstat 的 LISTENING 行。"""
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             encoding="gbk", errors="ignore").stdout
    except Exception:
        return {}
    found: dict = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        if parts[3].upper() != "LISTENING":
            continue
        local, pid = parts[1], parts[4]
        for p in PORTS:
            if local.endswith(f":{p}"):
                found.setdefault(pid, []).append(p)
    return found


def _pids_by_cmdline() -> dict:
    """兜底：按命令行匹配 run.py（netstat 取不到时用，如权限受限）。"""
    try:
        ps = ("Get-CimInstance Win32_Process -Filter \"name='python.exe' or name='pythonw.exe'\" "
              "| Where-Object { $_.CommandLine -like '*run.py*' } "
              "| ForEach-Object { $_.ProcessId }")
        out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                              "-Command", ps], capture_output=True, text=True,
                             encoding="utf-8", errors="ignore", timeout=20).stdout
    except Exception:
        return {}
    found: dict = {}
    for line in out.splitlines():
        pid = line.strip()
        if pid.isdigit():
            found[pid] = []
    return found


def main() -> int:
    targets = _pids_by_netstat()
    if not targets:
        targets = _pids_by_cmdline()

    if not targets:
        print("[提示] 没有发现运行中的服务（端口 8000/8001 无监听）")
        return 0

    for pid, ports in targets.items():
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=15)
            label = f"端口 {'/'.join(map(str, ports))}" if ports else "进程"
            print(f"[已停止] {label}，PID {pid}")
        except Exception as e:
            print(f"[失败] PID {pid} 结束失败：{e}")
            return 1

    # 复核
    left = [p for p in PORTS if _port_open(p)]
    if left:
        print(f"[警告] 端口 {left} 仍在监听，可能被其他程序占用")
        return 1
    print("[完成] 服务已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
