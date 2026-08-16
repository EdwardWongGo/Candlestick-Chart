# -*- coding: utf-8 -*-
"""
K 线本地缓存 —— 减少重复拉取，支撑日终批量扫描

缓存策略：
- 每只股票 × 每个时间级别 → 一个 CSV 文件（output/cache/{tf}/{code}.csv）
- 日线：缓存当日数据，扫描时若当天已缓存则直接读（日终批量场景一天只拉一次）
- 周线/月线：缓存最新一根日期，若未变化则读缓存
- 提供 ttl 参数控制有效期

Author: HZQ
"""
from __future__ import annotations

import csv
import os
import time
from typing import List, Optional

from ..models import Candle


class KlineCache:
    # 缓存根目录：data/（结构为 data/{timeframe}/{code}.csv）
    # 说明：早期为 output/cache/{VERSION}/ 版本化目录，现统一迁移到 data/ 目录
    def __init__(self, root: str = "data"):
        self.root = root

    def _path(self, code: str, timeframe: str) -> str:
        return os.path.join(self.root, timeframe, f"{code}.csv")

    def _meta_path(self, code: str, timeframe: str) -> str:
        return os.path.join(self.root, timeframe, f"{code}.meta")

    # ------------------------------------------------------------------
    def get(self, code: str, timeframe: str, ttl: int = 3600) -> Optional[List[Candle]]:
        """读取缓存；ttl 秒内有效返回数据，否则 None。ttl=None 时忽略有效期（供同步增量读取）。"""
        p = self._path(code, timeframe)
        mp = self._meta_path(code, timeframe)
        if not os.path.exists(p):
            return None
        # ttl 校验（None = 永不判过期）
        if ttl is not None:
            try:
                mtime = os.path.getmtime(p)
                if time.time() - mtime > ttl:
                    return None
            except OSError:
                pass

        candles: List[Candle] = []
        with open(p, "r", encoding="utf-8") as f:
            for row in csv.reader(f):
                if not row or row[0] == "dt":
                    continue
                try:
                    candles.append(Candle(
                        dt=row[0],
                        open=float(row[1]), high=float(row[2]),
                        low=float(row[3]), close=float(row[4]),
                        volume=float(row[5]),
                    ))
                except (ValueError, IndexError):
                    continue
        return candles if candles else None

    def set(self, code: str, timeframe: str, candles: List[Candle]):
        """写入缓存。"""
        if not candles:
            return
        os.makedirs(os.path.dirname(self._path(code, timeframe)), exist_ok=True)
        with open(self._path(code, timeframe), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["dt", "open", "high", "low", "close", "volume"])
            for c in candles:
                w.writerow([c.dt, c.open, c.high, c.low, c.close, c.volume])

    def is_fresh(self, code: str, timeframe: str, ttl: int = 3600) -> bool:
        """是否命中有效缓存。"""
        p = self._path(code, timeframe)
        if not os.path.exists(p):
            return False
        return (time.time() - os.path.getmtime(p)) <= ttl
