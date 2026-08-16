# -*- coding: utf-8 -*-
"""
蜡烛图形态库与识别引擎

内置形态（17 个，覆盖单根/双根/三根）：
  单根：锤子线、倒锤子线、上吊线、射击之星、十字星、蜻蜓十字、墓碑十字
  双根：看涨吞没、看跌吞没、刺透形态、乌云盖顶、看涨孕线、看跌孕线
  三根：启明星、黄昏星、三个白武士、三只乌鸦

每个形态区分看涨(bullish)/看跌(bearish)方向，并输出 0-100 的信号强度。
强度构成 = 基础可靠性 + 量能确认(放量倍数) + 趋势确认(反向趋势越深反转信号越强)。

Author: HZQ
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from ..models import Candle, PatternMatch
from . import base


# ---------------------------------------------------------------------------
# 强度评分辅助
# ---------------------------------------------------------------------------
def _score(base_score: float, candles: List[Candle], i: int,
           trend_bonus: float = 0.0, confirm_volume: bool = True) -> float:
    """基础分 + 放量确认 + 趋势加成，封顶 100。"""
    score = base_score
    if confirm_volume:
        vr = base.volume_ratio(candles, i)
        if vr >= 2.0:
            score += 12
        elif vr >= 1.5:
            score += 8
        elif vr >= 1.2:
            score += 4
    score += trend_bonus
    return min(100.0, max(0.0, score))


def _trend_bonus(trend: Optional[str]) -> float:
    """趋势越明确，反转信号越有意义的加成。"""
    return 4.0 if trend else 0.0


# ---------------------------------------------------------------------------
# 单根形态
# ---------------------------------------------------------------------------
def _hammer(candles: List[Candle], i: int) -> Optional[float]:
    """锤子线（看涨反转）：下跌后，长下影线，小实体在上部。"""
    if i < 0 or i >= len(candles):
        return None
    if base.prior_trend(candles, i) != "down":
        return None
    k = candles[i]
    if k.body == 0 or k.total_range == 0:
        return None
    if k.lower_shadow >= 2 * k.body and k.upper_shadow <= 0.3 * k.total_range:
        quality = min(100.0, 60 + (k.lower_shadow / k.body - 2) * 6)
        return _score(quality, candles, i, _trend_bonus("down"))
    return None


def _inverted_hammer(candles: List[Candle], i: int) -> Optional[float]:
    """倒锤子线（看涨反转）：下跌后，长上影线，小实体在下部。"""
    if base.prior_trend(candles, i) != "down":
        return None
    k = candles[i]
    if k.body == 0 or k.total_range == 0:
        return None
    if k.upper_shadow >= 2 * k.body and k.lower_shadow <= 0.3 * k.total_range:
        quality = min(100.0, 55 + (k.upper_shadow / k.body - 2) * 6)
        return _score(quality, candles, i, _trend_bonus("down"))
    return None


def _hanging_man(candles: List[Candle], i: int) -> Optional[float]:
    """上吊线（看跌反转）：上涨后，长下影线，小实体在上部。"""
    if base.prior_trend(candles, i) != "up":
        return None
    k = candles[i]
    if k.body == 0 or k.total_range == 0:
        return None
    if k.lower_shadow >= 2 * k.body and k.upper_shadow <= 0.3 * k.total_range:
        quality = min(100.0, 58 + (k.lower_shadow / k.body - 2) * 6)
        return _score(quality, candles, i, _trend_bonus("up"))
    return None


def _shooting_star(candles: List[Candle], i: int) -> Optional[float]:
    """射击之星（看跌反转）：上涨后，长上影线，小实体在下部。"""
    if base.prior_trend(candles, i) != "up":
        return None
    k = candles[i]
    if k.body == 0 or k.total_range == 0:
        return None
    if k.upper_shadow >= 2 * k.body and k.lower_shadow <= 0.3 * k.total_range:
        quality = min(100.0, 62 + (k.upper_shadow / k.body - 2) * 6)
        return _score(quality, candles, i, _trend_bonus("up"))
    return None


def _doji(candles: List[Candle], i: int) -> Optional[float]:
    """十字星（趋势反转方向）：实体极小，多空平衡，方向取决于前期趋势。"""
    k = candles[i]
    if k.total_range == 0:
        return None
    if k.body > 0.1 * k.total_range:
        return None
    trend = base.prior_trend(candles, i)
    # 下跌后十字星→看涨，上涨后→看跌，无趋势→中性（强度低）
    if trend == "down":
        return _score(50, candles, i, _trend_bonus("down"))
    if trend == "up":
        return _score(50, candles, i, _trend_bonus("up"))
    return None


def _dragonfly_doji(candles: List[Candle], i: int) -> Optional[float]:
    """蜻蜓十字 / T 字线（看涨）：开盘≈收盘≈最高，长下影线。"""
    k = candles[i]
    if k.total_range == 0:
        return None
    if k.body <= 0.1 * k.total_range and k.lower_shadow >= 2 * k.total_range / 3:
        return _score(66, candles, i, _trend_bonus(base.prior_trend(candles, i)))
    return None


def _gravestone_doji(candles: List[Candle], i: int) -> Optional[float]:
    """墓碑十字 / 倒 T 字线（看跌）：开盘≈收盘≈最低，长上影线。"""
    k = candles[i]
    if k.total_range == 0:
        return None
    if k.body <= 0.1 * k.total_range and k.upper_shadow >= 2 * k.total_range / 3:
        return _score(64, candles, i, _trend_bonus(base.prior_trend(candles, i)))
    return None


# ---------------------------------------------------------------------------
# 双根形态
# ---------------------------------------------------------------------------
def _bullish_engulfing(candles: List[Candle], i: int) -> Optional[float]:
    """看涨吞没：前阴后阳，阳线实体完全吞没阴线实体。"""
    if i < 1:
        return None
    prev, cur = candles[i - 1], candles[i]
    if prev.is_bearish and cur.is_bullish:
        if cur.open <= prev.close and cur.close >= prev.open and cur.body > prev.body:
            quality = min(100.0, 68 + (cur.body / prev.body - 1) * 8)
            trend = base.prior_trend(candles, i - 1)
            return _score(quality, candles, i, _trend_bonus(trend if trend == "down" else None))
    return None


def _bearish_engulfing(candles: List[Candle], i: int) -> Optional[float]:
    """看跌吞没：前阳后阴，阴线实体完全吞没阳线实体。"""
    if i < 1:
        return None
    prev, cur = candles[i - 1], candles[i]
    if prev.is_bullish and cur.is_bearish:
        if cur.open >= prev.close and cur.close <= prev.open and cur.body > prev.body:
            quality = min(100.0, 68 + (cur.body / prev.body - 1) * 8)
            trend = base.prior_trend(candles, i - 1)
            return _score(quality, candles, i, _trend_bonus(trend if trend == "up" else None))
    return None


def _piercing(candles: List[Candle], i: int) -> Optional[float]:
    """刺透形态（看涨）：下跌后，大阴线后接阳线，阳线收盘深入阴线实体上半部。"""
    if i < 1:
        return None
    prev, cur = candles[i - 1], candles[i]
    if base.prior_trend(candles, i - 1) != "down":
        return None
    if not (prev.is_bearish and cur.is_bullish):
        return None
    if prev.body == 0:
        return None
    # 阳线开盘低于前阴线收盘（跳空低开），收盘高于前阴线实体中点
    mid = (prev.open + prev.close) / 2
    if cur.open < prev.close and cur.close > mid and cur.close < prev.open:
        penetration = (cur.close - mid) / prev.body
        quality = min(100.0, 70 + penetration * 40)
        return _score(quality, candles, i, _trend_bonus("down"))
    return None


def _dark_cloud_cover(candles: List[Candle], i: int) -> Optional[float]:
    """乌云盖顶（看跌）：上涨后，大阳线后接阴线，阴线收盘深入阳线实体下半部。"""
    if i < 1:
        return None
    prev, cur = candles[i - 1], candles[i]
    if base.prior_trend(candles, i - 1) != "up":
        return None
    if not (prev.is_bullish and cur.is_bearish):
        return None
    if prev.body == 0:
        return None
    mid = (prev.open + prev.close) / 2
    if cur.open > prev.close and cur.close < mid and cur.close > prev.open:
        penetration = (mid - cur.close) / prev.body
        quality = min(100.0, 68 + penetration * 40)
        return _score(quality, candles, i, _trend_bonus("up"))
    return None


def _bullish_harami(candles: List[Candle], i: int) -> Optional[float]:
    """看涨孕线：下跌后，大阴线后接小阳线，被完全包含在前阴线实体内。"""
    if i < 1:
        return None
    prev, cur = candles[i - 1], candles[i]
    if base.prior_trend(candles, i - 1) != "down":
        return None
    if not (prev.is_bearish and cur.is_bullish):
        return None
    if prev.body == 0:
        return None
    if cur.open >= prev.close and cur.close <= prev.open and cur.body < prev.body:
        return _score(52, candles, i, _trend_bonus("down"))
    return None


def _bearish_harami(candles: List[Candle], i: int) -> Optional[float]:
    """看跌孕线：上涨后，大阳线后接小阴线，被完全包含在前阳线实体内。"""
    if i < 1:
        return None
    prev, cur = candles[i - 1], candles[i]
    if base.prior_trend(candles, i - 1) != "up":
        return None
    if not (prev.is_bullish and cur.is_bearish):
        return None
    if prev.body == 0:
        return None
    if cur.open <= prev.close and cur.close >= prev.open and cur.body < prev.body:
        return _score(52, candles, i, _trend_bonus("up"))
    return None


# ---------------------------------------------------------------------------
# 三根形态
# ---------------------------------------------------------------------------
def _morning_star(candles: List[Candle], i: int) -> Optional[float]:
    """启明星（看涨反转）：下跌后 大阴线 + 星线 + 大阳线，第三根收回第一根实体一半以上。"""
    if i < 2:
        return None
    first, second, third = candles[i - 2], candles[i - 1], candles[i]
    if base.prior_trend(candles, i - 2) != "down":
        return None
    if not (first.is_bearish and third.is_bullish):
        return None
    if first.body == 0:
        return None
    avg = base.avg_body(candles, i - 2, 10)
    # 第一根为大阴线
    if first.body < max(avg, 0.0) * 0.8:
        return None
    # 第二根为小实体星线（可阴可阳）
    if second.body > 0.5 * first.body:
        return None
    # 第三根大阳线收回第一根实体一半以上
    mid = (first.open + first.close) / 2
    if third.close > mid:
        quality = min(100.0, 78 + (third.close - mid) / first.body * 30)
        return _score(quality, candles, i, _trend_bonus("down"))
    return None


def _evening_star(candles: List[Candle], i: int) -> Optional[float]:
    """黄昏星（看跌反转）：上涨后 大阳线 + 星线 + 大阴线，第三根跌破第一根实体一半。"""
    if i < 2:
        return None
    first, second, third = candles[i - 2], candles[i - 1], candles[i]
    if base.prior_trend(candles, i - 2) != "up":
        return None
    if not (first.is_bullish and third.is_bearish):
        return None
    if first.body == 0:
        return None
    avg = base.avg_body(candles, i - 2, 10)
    if first.body < max(avg, 0.0) * 0.8:
        return None
    if second.body > 0.5 * first.body:
        return None
    mid = (first.open + first.close) / 2
    if third.close < mid:
        quality = min(100.0, 78 + (mid - third.close) / first.body * 30)
        return _score(quality, candles, i, _trend_bonus("up"))
    return None


def _three_white_soldiers(candles: List[Candle], i: int) -> Optional[float]:
    """三个白武士（看涨）：三根连续大阳线，逐根高开于前一根实体内，收于最高附近。"""
    if i < 2:
        return None
    c1, c2, c3 = candles[i - 2], candles[i - 1], candles[i]
    if not (c1.is_bullish and c2.is_bullish and c3.is_bullish):
        return None
    # 实体较大
    avg = base.avg_body(candles, i - 2, 10)
    if min(c1.body, c2.body, c3.body) < max(avg, 0.0) * 0.8:
        return None
    # 每根开盘在前一根实体内
    if not (c2.open > c1.open and c2.open < c1.close):
        return None
    if not (c3.open > c2.open and c3.open < c2.close):
        return None
    # 收盘接近最高（上影线小）
    if any(c.upper_shadow > 0.3 * c.body for c in (c1, c2, c3)):
        return None
    return _score(76, candles, i, 0.0)


def _three_black_crows(candles: List[Candle], i: int) -> Optional[float]:
    """三只乌鸦（看跌）：三根连续大阴线，逐根低开于前一根实体内，收于最低附近。"""
    if i < 2:
        return None
    c1, c2, c3 = candles[i - 2], candles[i - 1], candles[i]
    if not (c1.is_bearish and c2.is_bearish and c3.is_bearish):
        return None
    avg = base.avg_body(candles, i - 2, 10)
    if min(c1.body, c2.body, c3.body) < max(avg, 0.0) * 0.8:
        return None
    if not (c2.open < c1.open and c2.open > c1.close):
        return None
    if not (c3.open < c2.open and c3.open > c2.close):
        return None
    if any(c.lower_shadow > 0.3 * c.body for c in (c1, c2, c3)):
        return None
    return _score(76, candles, i, 0.0)


# ---------------------------------------------------------------------------
# 形态注册表
# ---------------------------------------------------------------------------
@dataclass
class PatternDef:
    key: str
    name_zh: str
    name_en: str
    direction: str          # bullish / bearish
    candles: int            # 1 / 2 / 3
    matcher: Callable[[List[Candle], int], Optional[float]]
    desc: str = ""


PATTERNS: List[PatternDef] = [
    # ---- 单根 ----
    PatternDef("hammer", "锤子线", "Hammer", "bullish", 1, _hammer,
               "下跌趋势后出现长下影小实体，预示见底回升"),
    PatternDef("inverted_hammer", "倒锤子线", "Inverted Hammer", "bullish", 1, _inverted_hammer,
               "下跌趋势后出现长上影小实体，多头尝试反攻"),
    PatternDef("hanging_man", "上吊线", "Hanging Man", "bearish", 1, _hanging_man,
               "上涨趋势后出现长下影小实体，警惕见顶"),
    PatternDef("shooting_star", "射击之星", "Shooting Star", "bearish", 1, _shooting_star,
               "上涨趋势后冲高回落，长上影预示见顶"),
    PatternDef("doji", "十字星", "Doji", "neutral", 1, _doji,
               "开盘收盘几乎相等，多空平衡，方向视趋势而定"),
    PatternDef("dragonfly_doji", "蜻蜓十字", "Dragonfly Doji", "bullish", 1, _dragonfly_doji,
               "T 字线，下影长探底回升，看涨"),
    PatternDef("gravestone_doji", "墓碑十字", "Gravestone Doji", "bearish", 1, _gravestone_doji,
               "倒 T 字线，上影长冲高回落，看跌"),
    # ---- 双根 ----
    PatternDef("bullish_engulfing", "看涨吞没", "Bullish Engulfing", "bullish", 2, _bullish_engulfing,
               "阳线实体完全吞没前一根阴线，多方主导"),
    PatternDef("bearish_engulfing", "看跌吞没", "Bearish Engulfing", "bearish", 2, _bearish_engulfing,
               "阴线实体完全吞没前一根阳线，空方主导"),
    PatternDef("piercing", "刺透形态", "Piercing Line", "bullish", 2, _piercing,
               "低开高走阳线深入前阴线实体，看涨反转"),
    PatternDef("dark_cloud_cover", "乌云盖顶", "Dark Cloud Cover", "bearish", 2, _dark_cloud_cover,
               "高开低走阴线深入前阳线实体，看跌反转"),
    PatternDef("bullish_harami", "看涨孕线", "Bullish Harami", "bullish", 2, _bullish_harami,
               "大阴线后小阳线被包含，跌势暂缓"),
    PatternDef("bearish_harami", "看跌孕线", "Bearish Harami", "bearish", 2, _bearish_harami,
               "大阳线后小阴线被包含，涨势暂缓"),
    # ---- 三根 ----
    PatternDef("morning_star", "启明星", "Morning Star", "bullish", 3, _morning_star,
               "大阴线+星线+大阳线，经典底部反转"),
    PatternDef("evening_star", "黄昏星", "Evening Star", "bearish", 3, _evening_star,
               "大阳线+星线+大阴线，经典顶部反转"),
    PatternDef("three_white_soldiers", "三个白武士", "Three White Soldiers", "bullish", 3, _three_white_soldiers,
               "三根连续大阳线，强势上攻"),
    PatternDef("three_black_crows", "三只乌鸦", "Three Black Crows", "bearish", 3, _three_black_crows,
               "三根连续大阴线，弱势下跌"),
]

_PATTERN_MAP = {p.key: p for p in PATTERNS}


def get_pattern(key: str) -> Optional[PatternDef]:
    return _PATTERN_MAP.get(key)


def all_patterns() -> List[PatternDef]:
    return PATTERNS


def detect_patterns(candles: List[Candle], keys: Optional[List[str]] = None,
                    lookback: int = 5) -> List[PatternMatch]:
    """对单只股票某级别的 K 线做形态扫描。

    candles: 升序 K 线列表
    keys:    限定扫描的形态（None = 全部）
    lookback: 往回扫描最近 N 根 K 线（形态以最后一根下标计）

    返回命中的 PatternMatch 列表（每形态最多取最近一次命中）。
    """
    if not candles:
        return []
    if keys is None:
        defs = PATTERNS
    else:
        defs = [p for p in PATTERNS if p.key in keys]

    matches: List[PatternMatch] = []
    n = len(candles)
    # 从最新一根往回扫
    for start in range(n - 1, max(-1, n - 1 - lookback), -1):
        i = start
        for pd in defs:
            # 需要前 pd.candles-1 根
            if i < pd.candles - 1:
                continue
            strength = pd.matcher(candles, i)
            if strength is None:
                continue
            direction = pd.direction
            # 十字星方向依趋势而定
            if pd.key == "doji":
                trend = base.prior_trend(candles, i)
                if trend == "down":
                    direction = "bullish"
                elif trend == "up":
                    direction = "bearish"
                else:
                    direction = "neutral"
            k = candles[i]
            matches.append(PatternMatch(
                key=pd.key,
                name_zh=pd.name_zh,
                name_en=pd.name_en,
                direction=direction,
                date=k.dt,
                index=i,
                strength=round(strength, 1),
                volume_ratio=round(base.volume_ratio(candles, i), 2),
                body_ratio=round(base.safe_div(k.body, k.total_range), 3),
                desc=pd.desc,
                candle_indexes=list(range(i - pd.candles + 1, i + 1)),
            ))
    # 去重：每个形态仅保留最新（index 最大）一次命中
    best: dict = {}
    for m in matches:
        if m.key not in best or m.index > best[m.key].index:
            best[m.key] = m
    result = sorted(best.values(), key=lambda m: m.index, reverse=True)
    return result
