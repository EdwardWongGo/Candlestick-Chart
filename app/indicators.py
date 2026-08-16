# -*- coding: utf-8 -*-
"""
技术指标模块 —— 均线 / 支撑阻力 / 相对位置 / 放量倍数 / 涨跌幅

说明：形态引擎所需的基础计算已内聚在 app/patterns/base.py，
本模块面向「筛选条件」与「前端图表」提供更高层的指标接口。

Author: HZQ
"""
from __future__ import annotations

from typing import List, Optional

from .models import Candle
from .patterns.base import (
    support_resistance, relative_position, position_label, volume_ratio,
)
import config


def compute_ma(candles: List[Candle], period: int) -> List[Optional[float]]:
    """计算收盘价 MA 序列（与 candles 对齐，前 period-1 项为 None）。"""
    result: List[Optional[float]] = [None] * len(candles)
    running = 0.0
    for i in range(len(candles)):
        running += candles[i].close
        if i >= period:
            running -= candles[i - period].close
        if i >= period - 1:
            result[i] = running / period
    return result


def ma_value(candles: List[Candle], period: int) -> Optional[float]:
    """最新一根收盘价的 MA(period) 值。"""
    if len(candles) < period:
        return None
    return sum(c.close for c in candles[-period:]) / period


def above_ma250(candles: List[Candle]) -> Optional[bool]:
    """最新收盘价是否在年线（MA250）之上；数据不足返回 None。"""
    if len(candles) < config.MA250_PERIOD:
        return None
    ma = ma_value(candles, config.MA250_PERIOD)
    if ma is None or ma == 0:
        return None
    return candles[-1].close > ma


def change_pct(candles: List[Candle], i: int) -> float:
    """第 i 根相对前一根的涨跌幅（%）。"""
    if i <= 0 or candles[i - 1].close == 0:
        return 0.0
    return (candles[i].close - candles[i - 1].close) / candles[i - 1].close * 100


def calc_metrics(candles: List[Candle], i: int) -> dict:
    """计算某根 K 线的综合指标，供筛选条件使用。

    返回: {volume_ratio, change_pct, position, position_label, support, resistance}
    """
    pos = relative_position(candles, i)
    support, resistance = support_resistance(candles, i)
    return {
        "volume_ratio": volume_ratio(candles, i),
        "change_pct": change_pct(candles, i),
        "position": pos,
        "position_label": position_label(pos),
        "support": support,
        "resistance": resistance,
    }
