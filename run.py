# -*- coding: utf-8 -*-
"""
启动入口 —— 支持两种模式：

1. Web 服务（默认）
   python run.py                 # 启动 http://127.0.0.1:8000

2. 命令行日终批量扫描（无界面，适合定时任务/CRON）
   python run.py --scan --daily --pattern hammer,bullish_engulfing
   python run.py --scan --full --tf daily,weekly --volume-min 1.5

Author: HZQ
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import webbrowser

import config


def _port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """检测端口是否已被占用（用于防止多开）。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.8)
            return s.connect_ex((host, port)) == 0
    except OSError:
        return False


def run_web(port: int, open_browser: bool = True):
    from app.server import app
    url = f"http://127.0.0.1:{port}"

    # 防止多开：端口已被占用说明工具已在运行，直接打开浏览器即可
    if _port_in_use(port):
        print(f"工具已在运行中 → {url}（无需重复启动，直接打开浏览器）")
        if open_browser:
            webbrowser.open(url)
        return

    print(f"启动 A股蜡烛图形态筛选工具 → {url}")

    if open_browser:
        def _open():
            import time
            time.sleep(1.5)          # 等服务就绪后再打开浏览器
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


def run_cli(args):
    from app.screener import Screener
    screener = Screener()

    params = {
        "timeframes": args.tf.split(",") if args.tf else ["daily"],
        "patterns": args.pattern.split(",") if args.pattern else None,
        "directions": args.direction.split(",") if args.direction else None,
        "markets": args.markets.split(",") if args.markets else None,
        "above_ma250": args.ma250,
        "volume_min": args.volume_min,
        "price_min": args.price_min,
        "price_max": args.price_max,
        "change_min": args.change_min,
        "change_max": args.change_max,
        "position": args.position,
        "exclude_st": not args.include_st,
        "full_market": args.full,
        "sort_by": args.sort_by,
    }

    print("开始扫描… 参数:", json.dumps(params, ensure_ascii=False))

    def cb(done, total, msg):
        pct = int(done / total * 100) if total else 100
        print(f"\r[{pct:3d}%] {msg}", end="", flush=True)

    result = screener.scan(params, progress_cb=cb)
    print()
    print("=" * 60)
    print(f"扫描完成：股票池 {result['universe_size']} 只，命中 {result['total']} 条，"
          f"耗时 {result['elapsed']}s")
    print("=" * 60)

    for r in result["results"]:
        resonance = " [共振]" if r["resonance"] else ""
        print(f"{r['code']} {r['name']:<8s} {r['timeframe_zh']} {r['pattern_zh']:<6s} "
              f"{r['direction_zh']} {r['date']} 强度{r['strength']:.0f} "
              f"量比{r['volume_ratio']}{resonance}")


def main():
    parser = argparse.ArgumentParser(description="A股蜡烛图形态筛选工具")
    parser.add_argument("--scan", action="store_true", help="命令行批量扫描模式")
    parser.add_argument("--port", type=int, default=8000, help="Web 端口（默认 8000）")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument("--tf", type=str, default="daily", help="时间级别，逗号分隔 daily,weekly,monthly")
    parser.add_argument("--pattern", type=str, default=None, help="形态 key，逗号分隔（默认全部）")
    parser.add_argument("--direction", type=str, default=None, help="方向 bullish,bearish")
    parser.add_argument("--markets", type=str, default=None,
                        help="市场板块，逗号分隔 sh,sz,bj,kcb,cyb（默认不限）")
    parser.add_argument("--ma250", action="store_true", help="仅保留最新价在年线(MA250)之上的股票")
    parser.add_argument("--volume-min", type=float, default=None, help="放量倍数下限")
    parser.add_argument("--price-min", type=float, default=None)
    parser.add_argument("--price-max", type=float, default=None)
    parser.add_argument("--change-min", type=float, default=None)
    parser.add_argument("--change-max", type=float, default=None)
    parser.add_argument("--position", type=str, default=None,
                        choices=["near_support", "near_resistance"])
    parser.add_argument("--include-st", action="store_true", help="包含 ST")
    parser.add_argument("--full", action="store_true", help="全市场扫描")
    parser.add_argument("--sort-by", type=str, default="strength", choices=["strength", "date"])
    args = parser.parse_args()

    if args.scan:
        run_cli(args)
    else:
        run_web(args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
