# -*- coding: utf-8 -*-
"""
数据同步 —— 把服务器最新 K 线增量同步到本地缓存，并记录同步时间

同步策略（增量）：
- 本地已有缓存 → 仅拉取最近 N 根（SYNC_LOOKBACK），与本地最新日期对比后追加新 bar
- 本地无缓存 → 全量拉取 KLINE_OFFSET 根并落盘
- 同步完成后记录时间到 output/cache/sync_meta.json，供界面展示「上次同步时间」

边界处理：
- 停牌股：增量拉取无新 bar，属正常，跳过不报错
- 单只失败：try/except 容错，不影响整体同步

Author: HZQ
"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Callable, List, Optional

import config
from .data.source import get_source
from .data.cache import KlineCache

# 项目根目录（sync.py 位于 app/ 下，上溯一级）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYNC_META_PATH = os.path.join(BASE_DIR, "output", "cache", "sync_meta.json")

# 并发同步线程数（mootdx 为 TCP 短请求，8 并发约提速 2 倍）
_SYNC_WORKERS = 8

# 增量同步时拉取的最近 K 线根数（用于对比本地最新日期，追加新 bar）
SYNC_LOOKBACK = 5


# ---------------------------------------------------------------------------
# 同步时间元数据
# ---------------------------------------------------------------------------
def _load_meta() -> dict:
    if not os.path.exists(SYNC_META_PATH):
        return {}
    try:
        with open(SYNC_META_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_meta(meta: dict):
    os.makedirs(os.path.dirname(SYNC_META_PATH), exist_ok=True)
    with open(SYNC_META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def get_sync_status() -> dict:
    """返回上次同步状态 {last_sync, synced_count, failed}。"""
    meta = _load_meta()
    return {
        "last_sync": meta.get("last_sync"),          # 上次同步时间字符串，无则为 None
        "synced_count": meta.get("synced_count", 0),
        "failed": meta.get("failed", 0),
    }


# ---------------------------------------------------------------------------
# 增量同步
# ---------------------------------------------------------------------------
def sync_incremental(codes: List[str], timeframes: List[str],
                     progress_cb: Optional[Callable[[int, int, str], None]] = None,
                     cancel_cb: Optional[Callable[[], bool]] = None,
                     server: Optional[list] = None) -> dict:
    """把给定股票池的最新 K 线增量同步到本地缓存（多线程并发拉取）。

    codes:      股票代码列表
    timeframes: 需要同步的级别（daily/weekly/monthly）
    progress_cb: 进度回调 (done, total, msg)
    cancel_cb:  取消回调，返回 True 时中断（返回 cancelled=True，不抛异常）
    server:     自定义服务器 [(host, port), ...]，None=自动选最快

    返回 {synced, failed, elapsed, last_sync, cancelled}
    """
    source = get_source(server=server) if server else get_source()
    cache = KlineCache()
    t0 = time.time()

    total = len(codes) * len(timeframes)
    lock = threading.Lock()
    state = {"done": 0, "synced": 0, "failed": 0, "cancelled": False}

    def _task(item):
        """单个 (code, tf) 的同步任务。返回 synced/skip/failed。"""
        if state["cancelled"] or (cancel_cb and cancel_cb()):
            state["cancelled"] = True
            return None
        code, tf = item
        try:
            cached = cache.get(code, tf, ttl=None)   # 忽略 ttl 读原始缓存
            if cached:
                last_dt = cached[-1].dt
                latest = source.get_bars(code, tf, SYNC_LOOKBACK)
                new_bars = [b for b in latest if b.dt > last_dt]
                if new_bars:
                    merged = cached + new_bars
                    cache.set(code, tf, merged[-config.MIN_BARS.get(tf, 120):])
                    return "synced"
            else:
                bars = source.get_bars(code, tf, config.KLINE_OFFSET)
                if bars:
                    cache.set(code, tf, bars[-config.MIN_BARS.get(tf, 120):])
                    return "synced"
            return "skip"
        except Exception:
            return "failed"

    tasks = [(c, tf) for c in codes for tf in timeframes]
    with ThreadPoolExecutor(max_workers=_SYNC_WORKERS) as ex:
        for item, result in zip(tasks, ex.map(_task, tasks)):
            with lock:
                state["done"] += 1
                if result == "synced":
                    state["synced"] += 1
                elif result == "failed":
                    state["failed"] += 1
                done = state["done"]
            if progress_cb:
                progress_cb(done, total, f"同步 {item[0]} {item[1]}")
            if state["cancelled"]:
                break

    last_sync = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not state["cancelled"]:
        _save_meta({"last_sync": last_sync, "synced_count": state["synced"],
                    "failed": state["failed"]})

    return {
        "synced": state["synced"],
        "failed": state["failed"],
        "elapsed": round(time.time() - t0, 2),
        "last_sync": last_sync,
        "cancelled": state["cancelled"],
    }
