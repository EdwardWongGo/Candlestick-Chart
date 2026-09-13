# -*- coding: utf-8 -*-
"""
蜡烛图形态库与识别引擎

内置形态（19 个，覆盖单根/双根/三根/多根）：
  单根：锤子线、倒锤子线、上吊线、射击之星、十字星、蜻蜓十字、墓碑十字
  双根：看涨吞没、看跌吞没、刺透形态、乌云盖顶、看涨孕线、看跌孕线
  三根：启明星、黄昏星、三个白武士、三只乌鸦
  多根（大阳线+3日确认）：单阳不破
  多根（MA5）：疑似主升

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
# 单阳不破族（大阳线 + 后续 N 根不破，N 为可配置参数 2-7）
# ---------------------------------------------------------------------------
def _is_big_yang(c: Candle, avg: float) -> bool:
    """大阳线（单阳不破专用）：阳线 + 实体达标 + 无上影线（可忽略）。

    完整判定规则（三项全部满足才算大阳线）：
    1. 阳线：收盘 > 开盘；
    2. 实体达标：实体长度 >= 1.2 倍前 10 根均实体，或涨幅 >= 3% 兜底；
    3. 无上影线（可忽略）：上影线长度 <= 实体长度的 5%。
       —— 光头阳线（最高价 == 收盘价，上影线为 0）严格满足；
          近似光头（上影线占比不超过实体 5%）视为「可忽略」通过；
          带明显上影线（占比 > 5%）不满足。
    """
    if not c.is_bullish or c.body <= 0:
        return False
    # 2. 实体达标（或涨幅兜底）
    if not (c.body >= max(avg, 0.0) * 1.2 or c.change_pct >= 3.0):
        return False
    # 3. 无上影线（可忽略）：上影线不超过实体的 5%
    if c.upper_shadow > c.body * 0.05:
        return False
    return True


def _single_yang_no_break(candles: List[Candle], i: int) -> Optional[float]:
    """单阳不破（单一固定规则，无子选项）：大阳线出现后，从第 3 天起判断是否成立。

    判定流程：
    - 完成日 i 为大阳线后第 3 根 K 线，即大阳线位于 j = i - 3；
    - 大阳线需满足 _is_big_yang（阳线 + 实体达标 + 无上影线）；
    - 大阳线后 3 根（i-2, i-1, i）的最低价均 >= 大阳线最低价 → 成立；
    - 历史不足（i < 3）不成立。
    """
    j = i - 3
    if j < 0:
        return None
    yang = candles[j]
    if not _is_big_yang(yang, base.avg_body(candles, j, 10)):
        return None
    for k in range(j + 1, i + 1):
        if candles[k].low < yang.low:
            return None
    quality = 76.0   # 固定 3 天确认
    return _score(quality, candles, i, _trend_bonus(base.prior_trend(candles, j)))


def _suspected_main_rise(candles: List[Candle], i: int) -> Optional[float]:
    """疑似主升：最近 3 根 K 线收盘价均未跌破各自的 MA5（5 周期均线）。

    主升浪特征：股价沿 MA5 强势上行，连续 3 根收盘都站在 MA5 之上。
    """
    if i < 5:   # MA5 至少需要 5 根历史
        return None
    closes = [c.close for c in candles]
    for j in range(i - 2, i + 1):   # 最近 3 根
        ma5 = base.sma(closes[:j + 1], 5)
        if ma5 is None or candles[j].close < ma5:
            return None
    # 越接近 MA5 上方持续运行，强度越高；叠加 MA5 是否上翘
    last_ma5 = base.sma(closes[:i + 1], 5)
    prev_ma5 = base.sma(closes[:i], 5)
    rising = (last_ma5 is not None and prev_ma5 is not None and last_ma5 >= prev_ma5)
    quality = 70 + (4 if rising else 0)
    return _score(min(100.0, quality), candles, i,
                  _trend_bonus(base.prior_trend(candles, i) if base.prior_trend(candles, i) == "up" else None))


# ---------------------------------------------------------------------------
# 形态注册表
# ---------------------------------------------------------------------------
@dataclass
class PatternDef:
    key: str
    name_zh: str
    name_en: str
    direction: str          # bullish / bearish / neutral
    candles: int            # 1 / 2 / 3 / ...
    matcher: Callable[..., Optional[float]]
    desc: str = ""
    sample: Optional[list] = None   # 示例 K 线（tooltip 示意图），[{o,h,l,c}, ...] 从左到右
    params: Optional[dict] = None   # 参数定义 {name: {min, max, default}}，None 表示无参数
    no_verify: bool = False         # 不提供「验证」子选项（如单阳不破）


PATTERNS: List[PatternDef] = [
    # ---- 单根 ----
    PatternDef("hammer", "锤子线", "Hammer", "bullish", 1, _hammer,
               "下跌趋势中出现：实体小、位于价格区间上半部，下影线至少为实体的两倍、上影线极短或无。卖压枯竭、买盘承接，是潜在底部反转信号，通常需次日阳线确认。",
               [{"o": 10, "h": 10.2, "l": 8.5, "c": 10.1}]),
    PatternDef("inverted_hammer", "倒锤子线", "Inverted Hammer", "bullish", 1, _inverted_hammer,
               "下跌趋势中出现：上影线至少为实体的两倍、下影线极短或无。多方试探性上攻但被空方压回，需次日阳线确认底部反转。",
               [{"o": 9.9, "h": 11.5, "l": 9.8, "c": 10.0}]),
    PatternDef("hanging_man", "上吊线", "Hanging Man", "bearish", 1, _hanging_man,
               "上涨趋势中出现：形态与锤子线相同（小实体、长下影），但位于高位。多方上攻乏力、抛压显现，警惕见顶，需次日阴线确认。",
               [{"o": 10, "h": 10.2, "l": 8.5, "c": 9.9}]),
    PatternDef("shooting_star", "射击之星", "Shooting Star", "bearish", 1, _shooting_star,
               "上涨趋势中出现：上影线至少为实体的两倍，小实体位于价格区间下端。冲高回落、上方抛压沉重，是顶部反转信号。",
               [{"o": 10, "h": 11.5, "l": 9.9, "c": 9.95}]),
    PatternDef("doji", "十字星", "Doji", "neutral", 1, _doji,
               "开盘价与收盘价几乎相等、实体极小。多空力量暂时均衡、趋势可能生变，方向取决于所处趋势位置。",
               [{"o": 10, "h": 10.4, "l": 9.6, "c": 10.0}]),
    PatternDef("dragonfly_doji", "蜻蜓十字", "Dragonfly Doji", "bullish", 1, _dragonfly_doji,
               "T 字线：开盘收盘均位于最高价附近，下影线很长、几乎无上影线。下跌趋势中探底回升、买盘强劲，看涨。",
               [{"o": 10, "h": 10.05, "l": 9.2, "c": 10.0}]),
    PatternDef("gravestone_doji", "墓碑十字", "Gravestone Doji", "bearish", 1, _gravestone_doji,
               "倒 T 字线：开盘收盘均位于最低价附近，上影线很长、几乎无下影线。上涨趋势中冲高回落、卖压沉重，看跌。",
               [{"o": 10, "h": 10.8, "l": 9.95, "c": 10.0}]),
    # ---- 双根 ----
    PatternDef("bullish_engulfing", "看涨吞没", "Bullish Engulfing", "bullish", 2, _bullish_engulfing,
               "下跌趋势中，一根阳线实体完全吞没前一根阴线实体。多方力量压倒空方，是强烈的底部反转信号。",
               [{"o": 10.5, "h": 10.6, "l": 9.8, "c": 9.9}, {"o": 9.7, "h": 10.8, "l": 9.5, "c": 10.7}]),
    PatternDef("bearish_engulfing", "看跌吞没", "Bearish Engulfing", "bearish", 2, _bearish_engulfing,
               "上涨趋势中，一根阴线实体完全吞没前一根阳线实体。空方力量压倒多方，是强烈的顶部反转信号。",
               [{"o": 9.8, "h": 10.4, "l": 9.6, "c": 10.3}, {"o": 10.5, "h": 10.7, "l": 9.7, "c": 9.8}]),
    PatternDef("piercing", "刺透形态", "Piercing Line", "bullish", 2, _piercing,
               "下跌趋势中低开高走，阳线收盘深入前一根阴线实体一半以上（但未完全吞没）。看涨反转信号。",
               [{"o": 10.5, "h": 10.6, "l": 9.8, "c": 9.9}, {"o": 9.6, "h": 10.2, "l": 9.5, "c": 10.15}]),
    PatternDef("dark_cloud_cover", "乌云盖顶", "Dark Cloud Cover", "bearish", 2, _dark_cloud_cover,
               "上涨趋势中高开低走，阴线收盘深入前一根阳线实体一半以下（但未完全吞没）。看跌反转信号。",
               [{"o": 9.8, "h": 10.4, "l": 9.6, "c": 10.3}, {"o": 10.5, "h": 10.6, "l": 9.9, "c": 10.05}]),
    PatternDef("bullish_harami", "看涨孕线", "Bullish Harami", "bullish", 2, _bullish_harami,
               "下跌趋势中大阴线后出现小阳线，且小阳线实体被大阴线实体完全包含。卖压减弱、跌势可能暂缓。",
               [{"o": 10.5, "h": 10.6, "l": 9.6, "c": 9.7}, {"o": 9.8, "h": 10.1, "l": 9.75, "c": 10.05}]),
    PatternDef("bearish_harami", "看跌孕线", "Bearish Harami", "bearish", 2, _bearish_harami,
               "上涨趋势中大阳线后出现小阴线，且小阴线实体被大阳线实体完全包含。买盘减弱、涨势可能暂缓。",
               [{"o": 9.6, "h": 10.5, "l": 9.5, "c": 10.4}, {"o": 10.2, "h": 10.3, "l": 9.9, "c": 10.0}]),
    # ---- 三根 ----
    PatternDef("morning_star", "启明星", "Morning Star", "bullish", 3, _morning_star,
               "下跌趋势中由三根组成：大阴线 + 星线（小实体）+ 大阳线，第三根阳线深入第一根阴线实体一半以上。经典底部反转形态。",
               [{"o": 10.5, "h": 10.6, "l": 9.7, "c": 9.8}, {"o": 9.75, "h": 9.9, "l": 9.6, "c": 9.8}, {"o": 9.9, "h": 10.5, "l": 9.8, "c": 10.4}]),
    PatternDef("evening_star", "黄昏星", "Evening Star", "bearish", 3, _evening_star,
               "上涨趋势中由三根组成：大阳线 + 星线 + 大阴线，第三根阴线深入第一根阳线实体一半以下。经典顶部反转形态。",
               [{"o": 9.7, "h": 10.5, "l": 9.6, "c": 10.4}, {"o": 10.35, "h": 10.5, "l": 10.2, "c": 10.4}, {"o": 10.3, "h": 10.4, "l": 9.7, "c": 9.8}]),
    PatternDef("three_white_soldiers", "三个白武士", "Three White Soldiers", "bullish", 3, _three_white_soldiers,
               "三根连续大阳线，每根收盘价都高于前一根，且都收于或接近最高价。多方强势上攻，看涨。",
               [{"o": 9.8, "h": 10.3, "l": 9.7, "c": 10.2}, {"o": 10.2, "h": 10.7, "l": 10.1, "c": 10.6}, {"o": 10.6, "h": 11.2, "l": 10.5, "c": 11.0}]),
    PatternDef("three_black_crows", "三只乌鸦", "Three Black Crows", "bearish", 3, _three_black_crows,
               "三根连续大阴线，每根收盘价都低于前一根，且都收于或接近最低价。空方强势下压，看跌。",
               [{"o": 10.5, "h": 10.6, "l": 10.0, "c": 10.1}, {"o": 10.1, "h": 10.2, "l": 9.6, "c": 9.7}, {"o": 9.7, "h": 9.8, "l": 9.2, "c": 9.3}]),
    # ---- 单阳不破（大阳线后第 3 天起判断，无子选项）----
    PatternDef("single_yang_no_break", "单阳不破", "Single Yang No Break", "bullish", 4, _single_yang_no_break,
               "一根无上影线的大阳线后，连续 3 根 K 线最低价均未跌破该阳线最低价。多方护盘有力，回踩不破确认强势。",
               [{"o": 9.5, "h": 10.5, "l": 9.4, "c": 10.4}, {"o": 10.3, "h": 10.6, "l": 10.0, "c": 10.3}, {"o": 10.4, "h": 10.5, "l": 10.05, "c": 10.4}, {"o": 10.3, "h": 10.7, "l": 10.2, "c": 10.6}],
               no_verify=True),
    PatternDef("suspected_main_rise", "疑似主升", "Suspected Main Rise", "bullish", 3, _suspected_main_rise,
               "最近 3 根 K 线收盘价均未跌破各自 MA5，沿 5 周期均线强势上行，呈主升浪特征。",
               [{"o": 9.8, "h": 10.3, "l": 9.7, "c": 10.2}, {"o": 10.2, "h": 10.6, "l": 10.1, "c": 10.5}, {"o": 10.5, "h": 10.9, "l": 10.4, "c": 10.8}],
               no_verify=True),
]

_PATTERN_MAP = {p.key: p for p in PATTERNS}


def get_pattern(key: str) -> Optional[PatternDef]:
    return _PATTERN_MAP.get(key)


def all_patterns() -> List[PatternDef]:
    return PATTERNS


def _verify(candles: List[Candle], i: int, direction: str) -> bool:
    """验证日确认：形态在 i 处完成，i+1 为验证日。

    看涨形态 → 验证日收盘高于形态完成日收盘（确认上涨）；
    看跌形态 → 验证日收盘低于形态完成日收盘（确认下跌）。
    """
    if i + 1 >= len(candles):
        return False   # 形态已是最后一根，无验证日可用
    confirm = candles[i + 1]
    prev = candles[i]
    if direction == "bullish":
        return confirm.close > prev.close
    if direction == "bearish":
        return confirm.close < prev.close
    return True   # 中性方向不做验证


def detect_patterns(candles: List[Candle], keys: Optional[List[str]] = None,
                    lookback: int = 5,
                    verify_keys: Optional[List[str]] = None,
                    pattern_params: Optional[dict] = None) -> List[PatternMatch]:
    """对「最近连续交易日窗口」做形态判断。

    与全周期扫描不同，形态必须恰好完成于最近窗口内：
    - 不验证的形态：以最后一根 K 线为完成日（i = n-1），用最近 candles 根判断
      （如启明星 = 最近 3 个连续交易日）。
    - 需要验证的形态：以倒数第二根为完成日（i = n-2），最后一根作为「验证日」，
      即形态在原所需根数基础上追加 1 天验证日（如启明星 3 天 → 4 天），
      仅当验证日确认形态方向时才命中。

    candles: 升序 K 线列表
    keys:    限定扫描的形态（None = 全部）
    verify_keys: 需要验证的形态 key 列表（勾选「验证」的形态）
    lookback: 兼容旧签名保留，不再用于往回扫描。
    pattern_params: 参数化形态的运行时参数，如 {"single_yang_no_break": {"N": 3}}；
                    未传或缺失时使用形态声明中的默认值，并 clamp 到声明范围。

    返回命中的 PatternMatch 列表（每个形态最多 1 次命中）。
    """
    if not candles:
        return []
    if keys is None:
        defs = PATTERNS
    else:
        defs = [p for p in PATTERNS if p.key in keys]
    verify_set = set(verify_keys) if verify_keys else set()

    n = len(candles)
    matches: List[PatternMatch] = []
    for pd in defs:
        need_verify = (pd.key in verify_set) and not pd.no_verify
        # 验证形态：完成日在倒数第二根，最后一根为验证日
        i = n - 2 if need_verify else n - 1
        if i < pd.candles - 1:
            continue
        # 参数化形态：解析并 clamp N（如单阳不破）
        N = None
        if pd.params and "N" in pd.params:
            spec = pd.params["N"]
            raw = (pattern_params or {}).get(pd.key, {}).get("N", spec.get("default", 3))
            try:
                N = int(raw)
            except (TypeError, ValueError):
                N = int(spec.get("default", 3))
            N = max(int(spec.get("min", 2)), min(int(spec.get("max", 7)), N))
            strength = pd.matcher(candles, i, N)
        else:
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

        # 验证日确认（勾选验证的形态）
        if need_verify and not _verify(candles, i, direction):
            continue

        k = candles[i]
        # 参数化形态（单阳不破族）：高亮覆盖大阳线 + 后续 N 根；其余按 candles 字段
        if N is not None:
            idxs = list(range(i - N, i + 1))
        else:
            idxs = list(range(i - pd.candles + 1, i + 1))
        if need_verify:
            idxs.append(n - 1)   # 追加验证日
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
            candle_indexes=idxs,
        ))

    return sorted(matches, key=lambda m: m.index, reverse=True)
