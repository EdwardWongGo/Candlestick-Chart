# -*- coding: utf-8 -*-
"""形态识别引擎的基础工具函数。

约定：candles 为按时间升序的列表（index -1 为最新一根）。
所有 matcher 以「形态最后一根 K 线的下标 i」为入参。

Author: HZQ
"""
from __future__ import annotations

from typing import List, Optional

from ..models import Candle


# ---------------------------------------------------------------------------
# 趋势判断
# ---------------------------------------------------------------------------
def sma(closes: List[float], period: int) -> Optional[float]:
    """简单移动平均（对收盘价序列求最近 period 根均值）。"""
    if period <= 0 or len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def prior_trend(candles: List[Candle], i: int, lookback: int = 20) -> Optional[str]:
    """判断 candles[i] 之前的趋势（不含 candles[i]）。

    采用「线性回归斜率」衡量窗口内收盘价的趋势方向：
    - 斜率（归一化后）> 阈值  → 'up'
    - 斜率 < -阈值            → 'down'
    - 否则 / 数据不足          → None
    """
    start = max(0, i - lookback)
    window = candles[start:i]
    if len(window) < 8:
        return None

    closes = [c.close for c in window]
    n = len(closes)
    xm = (n - 1) / 2.0
    ym = sum(closes) / n
    num = sum((k - xm) * (closes[k] - ym) for k in range(n))
    den = sum((k - xm) ** 2 for k in range(n))
    if den == 0 or ym == 0:
        return None
    # 归一化斜率：整段窗口的相对涨跌幅量纲
    slope_pct = (num / den) * (n - 1) / ym

    if slope_pct > 0.01:
        return "up"
    if slope_pct < -0.01:
        return "down"
    return None


def sma_trend(candles: List[Candle], i: int, short: int = 5, long: int = 10) -> Optional[str]:
    """备用趋势判断：短期均线 vs 长期均线。"""
    if i < long:
        return None
    closes = [c.close for c in candles[:i]]
    s = sma(closes, short)
    l = sma(closes, long)
    if s is None or l is None or l == 0:
        return None
    if s > l:
        return "up"
    if s < l:
        return "down"
    return None


# ---------------------------------------------------------------------------
# 量能
# ---------------------------------------------------------------------------
def volume_ratio(candles: List[Candle], i: int, period: int = 20) -> float:
    """放量倍数 = candles[i].volume / 前 period 根均量。"""
    if candles[i].volume <= 0:
        return 1.0
    base = [c.volume for c in candles[max(0, i - period):i]]
    if not base:
        return 1.0
    avg = sum(base) / len(base)
    if avg <= 0:
        return 1.0
    return candles[i].volume / avg


# ---------------------------------------------------------------------------
# 实体
# ---------------------------------------------------------------------------
def avg_body(candles: List[Candle], i: int, n: int = 10) -> float:
    """前 n 根 K 线的平均实体长度。"""
    window = candles[max(0, i - n):i]
    if not window:
        return 0.0
    return sum(c.body for c in window) / len(window)


# ---------------------------------------------------------------------------
# 支撑 / 阻力 & 相对位置
# ---------------------------------------------------------------------------
def support_resistance(candles: List[Candle], i: int, lookback: int = 60):
    """计算 candles[i] 之前的支撑（近 lookback 低点）与阻力（近 lookback 高点）。

    返回 (support, resistance)；数据不足时返回 (None, None)。
    """
    start = max(0, i - lookback)
    window = candles[start:i]
    if len(window) < 20:
        return None, None
    support = min(c.low for c in window)
    resistance = max(c.high for c in window)
    if resistance <= support:
        return None, None
    return support, resistance


def relative_position(candles: List[Candle], i: int, lookback: int = 60) -> Optional[float]:
    """相对位置 0~1（0 = 贴近支撑，1 = 贴近阻力）。"""
    support, resistance = support_resistance(candles, i, lookback)
    if support is None:
        return None
    pos = (candles[i].close - support) / (resistance - support)
    return max(0.0, min(1.0, pos))


def position_label(pos: Optional[float]) -> str:
    if pos is None:
        return "数据不足"
    if pos <= 0.20:
        return "接近支撑"
    if pos >= 0.80:
        return "接近阻力"
    if pos < 0.5:
        return "偏低"
    return "偏高"


def safe_div(a: float, b: float, default: float = 0.0) -> float:
    return a / b if b != 0 else default
