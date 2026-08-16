# -*- coding: utf-8 -*-
"""
统一数据模型 —— 蜡烛（K线）与形态匹配结果

约定：
- Candle 为单根 K 线的轻量结构，纯 Python（不依赖 pandas），
  供形态识别引擎与筛选引擎共同使用。
- candles 列表默认按时间升序排列（index 0 = 最早，index -1 = 最新）。

Author: HZQ
"""
from dataclasses import dataclass, field, asdict


@dataclass
class Candle:
    """单根 K 线（蜡烛）。"""
    dt: str = ""            # 日期/时间 "YYYY-MM-DD"
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0     # 成交量（手/股，与数据源一致）

    # ---- 派生指标 ----
    @property
    def body(self) -> float:
        """实体长度（绝对值）。"""
        return abs(self.close - self.open)

    @property
    def upper_shadow(self) -> float:
        """上影线长度。"""
        return self.high - max(self.open, self.close)

    @property
    def lower_shadow(self) -> float:
        """下影线长度。"""
        return min(self.open, self.close) - self.low

    @property
    def total_range(self) -> float:
        """全振幅（最高 - 最低）。"""
        return self.high - self.low

    @property
    def is_bullish(self) -> bool:
        """阳线（收盘 > 开盘）。"""
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        """阴线（收盘 < 开盘）。"""
        return self.close < self.open

    @property
    def change_pct(self) -> float:
        """本根涨跌幅（相对前收需外部传入，此处仅返回实体/开盘粗略值）。"""
        if self.open == 0:
            return 0.0
        return (self.close - self.open) / self.open * 100

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PatternMatch:
    """一次形态命中结果。"""
    key: str              # 形态唯一标识（如 hammer）
    name_zh: str          # 中文名
    name_en: str          # 英文名
    direction: str        # 'bullish' 看涨 / 'bearish' 看跌
    date: str             # 信号出现日期（形态最后一根 K 线日期）
    index: int            # 形态最后一根 K 线在列表中的下标（-1 为最新）
    strength: float = 0.0      # 信号强度 0-100（形态引擎给出，未含级别/共振加权）
    volume_ratio: float = 1.0  # 放量倍数（当日量 / 近 N 日均量）
    body_ratio: float = 0.0    # 实体相对振幅比例（辅助展示）
    desc: str = ""             # 命中条件简述
    candle_indexes: list = field(default_factory=list)  # 形态涉及的 K 线下标（用于图上高亮）

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name_zh": self.name_zh,
            "name_en": self.name_en,
            "direction": self.direction,
            "date": self.date,
            "index": self.index,
            "strength": round(self.strength, 1),
            "volume_ratio": round(self.volume_ratio, 2),
            "body_ratio": round(self.body_ratio, 3),
            "desc": self.desc,
            "candle_indexes": self.candle_indexes,
        }


@dataclass
class ScanResult:
    """筛选引擎输出的单条结果（列表展示用）。"""
    code: str
    name: str
    market: str = ""         # 市场板块 sh/sz/bj/kcb/cyb
    market_zh: str = ""      # 上证/深证/北证/科创/创业
    timeframe: str = ""      # daily / weekly / monthly
    timeframe_zh: str = ""   # 日线 / 周线 / 月线
    pattern_zh: str = ""
    pattern_en: str = ""
    direction: str = ""      # bullish / bearish
    direction_zh: str = ""   # 看涨 / 看跌
    date: str = ""           # 出现日期
    strength: float = 0.0    # 加权后信号强度 0-100
    volume_ratio: float = 1.0  # 放量倍数
    close: float = 0.0       # 现价/收盘价
    change_pct: float = 0.0  # 涨跌幅
    position: float = -1.0   # 相对位置 0(支撑)~1(阻力)
    position_label: str = "" # 相对位置说明
    resonance: bool = False  # 是否多级别共振
    resonance_levels: list = field(default_factory=list)  # 共振涉及的时间级别列表
    candle_indexes: list = field(default_factory=list)    # 图上高亮用的 K 线下标
    limit_1y: int = 0        # 近一年涨停次数（本地日线推导）

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "market": self.market,
            "market_zh": self.market_zh,
            "timeframe": self.timeframe,
            "timeframe_zh": self.timeframe_zh,
            "pattern_zh": self.pattern_zh,
            "pattern_en": self.pattern_en,
            "direction": self.direction,
            "direction_zh": self.direction_zh,
            "date": self.date,
            "strength": round(self.strength, 1),
            "volume_ratio": round(self.volume_ratio, 2),
            "close": self.close,
            "change_pct": round(self.change_pct, 2),
            "position": round(self.position, 3),
            "position_label": self.position_label,
            "resonance": self.resonance,
            "resonance_levels": self.resonance_levels,
            "limit_1y": self.limit_1y,
            "candle_indexes": self.candle_indexes,
        }
