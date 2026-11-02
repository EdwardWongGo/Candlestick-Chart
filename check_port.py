# -*- coding: utf-8 -*-
"""
端口探测 —— 供启动脚本轮询服务是否就绪

用法：
    python check_port.py 8000
退出码 0 = 端口已监听，1 = 未监听

单独成文件的原因：bat 的 for /l 循环体内写内联 -c 代码，其中的 ")"
会提前闭合循环括号，导致脚本卡死。

Author: HZQ
"""
import socket
import sys


def main() -> int:
    try:
        port = int(sys.argv[1])
    except (IndexError, ValueError):
        return 1
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return 0 if s.connect_ex(("127.0.0.1", port)) == 0 else 1
    except OSError:
        return 1
    finally:
        s.close()


if __name__ == "__main__":
    sys.exit(main())
