# -*- coding: utf-8 -*-
"""
本地日线推导模块 —— 涨停/跌停/未封板/连板/涨停次数

背景：东财涨停池只保留约 10 个交易日历史，跌停池/炸板池近期返回空，
因此「历史统计」类指标（涨停次数、跌停连板、未封板）统一基于本地日线 K 线推导。

涨跌幅限制：
- 主板 10%、科创板/创业板 20%、北交所 30%、ST 股 5%
- 上市首日无限制（次新 5 日内不纳入统计，由调用方控制）

Author: HZQ
"""
from __future__ import annotations

from typing import List, Optional

import config
from .models import Candle


def limit_pct(code: str, name: str = "") -> float:
    """涨跌幅限制比例。ST 股 5%，科创/创业 20%，北交所 30%，主板 10%。"""
    n = (name or "").upper()
    if "ST" in n:
        return 0.05
    m = config.classify_market(code)
    if m in ("kcb", "cyb"):
        return 0.20
    if m == "bj":
        return 0.30
    return 0.10


def _limit_price(prev_close: float, code: str, name: str, direction: str) -> float:
    pct = limit_pct(code, name)
    if direction == "up":
        return round(prev_close * (1 + pct), 2)
    return round(prev_close * (1 - pct), 2)


def is_limit_up(c: Candle, prev_close: float, code: str, name: str = "") -> bool:
    """涨停判定：收盘价 >= 涨停价（含舍入容差）。"""
    if prev_close <= 0:
        return False
    return round(c.close, 2) >= _limit_price(prev_close, code, name, "up") - 0.005


def is_limit_down(c: Candle, prev_close: float, code: str, name: str = "") -> bool:
    """跌停判定：收盘价 <= 跌停价（含舍入容差）。"""
    if prev_close <= 0:
        return False
    return round(c.close, 2) <= _limit_price(prev_close, code, name, "down") + 0.005


def is_unsealed_up(c: Candle, prev_close: float, code: str, name: str = "") -> bool:
    """未封板涨停：当日最高触及涨停价，但收盘未封住。"""
    if prev_close <= 0:
        return False
    lp = _limit_price(prev_close, code, name, "up")
    return round(c.high, 2) >= lp - 0.005 and round(c.close, 2) < lp - 0.005


def is_unsealed_down(c: Candle, prev_close: float, code: str, name: str = "") -> bool:
    """未封板跌停：当日最低触及跌停价，但收盘未封住。"""
    if prev_close <= 0:
        return False
    lp = _limit_price(prev_close, code, name, "down")
    return round(c.low, 2) <= lp + 0.005 and round(c.close, 2) > lp + 0.005


def count_limit_up(candles: List[Candle], code: str, name: str = "", days: int = None) -> int:
    """近 days 根 K 线的涨停次数（days=None 统计全部）。"""
    n = len(candles)
    if n < 2:
        return 0
    start = max(1, n - days) if days else 1
    cnt = 0
    for i in range(start, n):
        if is_limit_up(candles[i], candles[i - 1].close, code, name):
            cnt += 1
    return cnt


def limit_up_boards(candles: List[Candle], code: str, name: str = "") -> int:
    """最近连续涨停连板数（最新一根须为涨停，往前连续计数）。"""
    n = len(candles)
    if n < 2:
        return 0
    if not is_limit_up(candles[-1], candles[-2].close, code, name):
        return 0
    boards = 1
    for i in range(n - 2, 0, -1):
        if is_limit_up(candles[i], candles[i - 1].close, code, name):
            boards += 1
        else:
            break
    return boards


def limit_down_boards(candles: List[Candle], code: str, name: str = "") -> int:
    """最近连续跌停连板数（最新一根须为跌停，往前连续计数）。"""
    n = len(candles)
    if n < 2:
        return 0
    if not is_limit_down(candles[-1], candles[-2].close, code, name):
        return 0
    boards = 1
    for i in range(n - 2, 0, -1):
        if is_limit_down(candles[i], candles[i - 1].close, code, name):
            boards += 1
        else:
            break
    return boards
