# -*- coding: utf-8 -*-
"""
K 线缓存断层体检与修复

背景：
    旧版增量同步 SYNC_LOOKBACK=5，只拉最近 5 根与缓存最后日期比较后追加。
    若两次同步之间隔着长假（2026 国庆：9/18 之后下一个交易日是 10/12，中间 10 个
    交易日），窗口只覆盖假期后的 5 根，中间 10 天被永久跳过 —— 缓存从此出现日期
    断层，且后续增量同步只往后追加，永远补不回来。

    断层会让形态识别把「跨断层的 K 线」当成连续 N 根，把过期甚至已经破位的形态
    判成新鲜命中（国脉文化 600640、国光连锁 605188 即此原因被误报为「阳上不破」）。

修复：
    扫描 data/{daily,weekly,monthly}/*.csv，发现相邻 K 线日历间隔超过阈值（日线 12 天、
    周线 21 天，排除春节自然休假）即判定断层，重拉 KLINE_OFFSET 根全量覆盖该股缓存。
    全量根数 ≥ MIN_BARS，覆盖后不复权序列也更一致。

用法：
    python -m app.repair_cache --dry-run          # 只体检，输出断层清单统计
    python -m app.repair_cache                    # 修复全部级别
    python -m app.repair_cache --tf daily -w 8    # 只修日线，8 线程

Author: HZQ
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Optional, Tuple

import config
from .data.cache import KlineCache
from .data.source import get_source
from .models import Candle

# 相邻 K 线允许的最大日历间隔（天）。超过即视为数据断层。
#   日线 12 天：春节最长休市 9/11 天（2026-02-13 → 02-24），不会被误判
#   周线 21 天：春节两周合并时可能出现 14 天间隔
GAP_LIMIT = {"daily": 12, "weekly": 21}

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _d(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def find_gaps(candles: List[Candle], timeframe: str) -> List[Tuple[str, str, int]]:
    """返回 [(前一根日期, 后一根日期, 间隔天数), ...]，只列超过阈值的断层。"""
    limit = GAP_LIMIT.get(timeframe)
    if limit is None:
        return []
    out: List[Tuple[str, str, int]] = []
    for a, b in zip(candles, candles[1:]):
        da, db = _d(a.dt), _d(b.dt)
        if da is None or db is None:
            continue
        days = (db - da).days
        if days > limit:
            out.append((a.dt, b.dt, days))
    return out


def repair(timeframes: Optional[List[str]] = None, workers: int = 8,
           dry_run: bool = False, progress=None) -> dict:
    """体检并修复缓存断层，返回统计。"""
    cache = KlineCache(os.path.join(BASE_DIR, "data"))
    src = get_source()
    tfs = timeframes or ["daily", "weekly", "monthly"]

    tasks: List[Tuple[str, str]] = []
    for tf in tfs:
        for p in glob.glob(os.path.join(BASE_DIR, "data", tf, "*.csv")):
            tasks.append((os.path.basename(p)[:-4], tf))

    state = {"ok": 0, "need": 0, "fixed": 0, "failed": 0, "empty": 0}
    lock = threading.Lock()
    gaps_found: List[Tuple[str, str, List[Tuple[str, str, int]]]] = []

    def _task(item):
        code, tf = item
        try:
            cached = cache.get(code, tf, ttl=None)
            if not cached:
                return "empty", None
            gaps = find_gaps(cached, tf)
            if not gaps:
                return "ok", None
            if dry_run:
                return "need", gaps
            full = src.get_bars(code, tf, config.KLINE_OFFSET)
            if not full or len(full) < config.MIN_BARS.get(tf, 120):
                return "failed", gaps
            cache.set(code, tf, full[-config.MIN_BARS.get(tf, 120):])
            # 修复后复查：数据源本身缺失（长期停牌）会仍有缺口，属正常
            left = find_gaps(full[-config.MIN_BARS.get(tf, 120):], tf)
            return ("fixed" if not left else "fixed_partial"), gaps
        except Exception:
            return "failed", None

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (status, gaps) in enumerate(ex.map(_task, tasks), 1):
            with lock:
                state[status if status in state else "failed"] = \
                    state.get(status if status in state else "failed", 0) + 1
                if gaps:
                    gaps_found.append((tasks[i - 1][0], tasks[i - 1][1], gaps))
                if progress and i % 200 == 0:
                    progress(i, len(tasks))

    state["total"] = len(tasks)
    state["elapsed"] = round(time.time() - t0, 1)
    state["gaps"] = gaps_found
    return state


def main():
    ap = argparse.ArgumentParser(description="K 线缓存断层体检与修复")
    ap.add_argument("--tf", default="", help="只处理指定级别，逗号分隔：daily,weekly,monthly")
    ap.add_argument("-w", "--workers", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true", help="只体检不修复")
    ap.add_argument("--list", type=int, default=0, help="打印前 N 条断层明细")
    args = ap.parse_args()

    tfs = [t.strip() for t in args.tf.split(",") if t.strip()] or None

    def _p(done, total):
        print(f"  进度 {done}/{total}", flush=True)

    r = repair(tfs, args.workers, args.dry_run, _p)
    print(f"总文件 {r['total']}  正常 {r['ok']}  断层 {r['need']}  "
          f"已修复 {r['fixed']}  部分修复 {r.get('fixed_partial', 0)}  "
          f"失败 {r['failed']}  空 {r['empty']}  耗时 {r['elapsed']}s")
    if args.list:
        for code, tf, gaps in r["gaps"][:args.list]:
            seg = "；".join(f"{a}→{b}({d}天)" for a, b, d in gaps[:3])
            print(f"  {code} {tf}: {seg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
