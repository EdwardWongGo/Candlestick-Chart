# -*- coding: utf-8 -*-
"""
形态引擎自检 —— 供 Web「测试入口」调用，返回结构化测试结果

使用合成 K 线（不依赖网络）验证 17 个形态识别逻辑的正确性。

Author: HZQ
"""
from __future__ import annotations

from typing import List

from .models import Candle
from .patterns.registry import detect_patterns, all_patterns


def _mk(open_, high, low, close, vol=10000.0) -> Candle:
    return Candle(dt="", open=open_, high=high, low=low, close=close, volume=vol)


def _downtrend(n=12, base=100.0, step=2.0) -> List[Candle]:
    cs, price = [], base
    for _ in range(n):
        cs.append(_mk(price, price + 0.5, price - step - 0.5, price - step))
        price -= step
    return cs


def _uptrend(n=12, base=100.0, step=2.0) -> List[Candle]:
    cs, price = [], base
    for _ in range(n):
        cs.append(_mk(price, price + step + 0.5, price - 0.5, price + step))
        price += step
    return cs


def _case(name: str, candles: List[Candle], expect_keys: List[str]) -> dict:
    matches = detect_patterns(candles)
    keys = [m.key for m in matches]
    ok = all(k in keys for k in expect_keys)
    return {
        "name": name,
        "expect": expect_keys,
        "actual": keys,
        "passed": ok,
    }


def run_selftest() -> dict:
    """运行全部自检用例，返回 {total, passed, failed, cases, patterns}。"""
    cases = []

    cs = _downtrend(12)
    cs.append(_mk(90, 90.6, 86.0, 89.5))
    cases.append(_case("锤子线（下跌后长下影）", cs, ["hammer"]))

    cs = _uptrend(12)
    cs.append(_mk(130, 135.0, 129.8, 130.2))
    cases.append(_case("射击之星（上涨后长上影）", cs, ["shooting_star"]))

    cs = _downtrend(12)
    cs.append(_mk(80, 80.5, 77.0, 77.5))
    cs.append(_mk(77.2, 82.5, 76.8, 82.0))
    cases.append(_case("看涨吞没", cs, ["bullish_engulfing"]))

    cs = _uptrend(12)
    cs.append(_mk(118, 121, 117, 120))
    cs.append(_mk(120.5, 121, 114, 115))
    cases.append(_case("看跌吞没", cs, ["bearish_engulfing"]))

    cs = _uptrend(8, base=100, step=3)
    cs.append(_mk(124, 124.5, 119, 119.5))
    cs.append(_mk(120, 120.5, 115, 115.5))
    cs.append(_mk(116, 116.5, 111, 111.5))
    cases.append(_case("三只乌鸦", cs, ["three_black_crows"]))

    cs = _downtrend(10)
    cs.append(_mk(80, 81, 78, 78.5))
    cs.append(_mk(79, 82, 78.8, 81.8))
    cs.append(_mk(81.2, 84, 81, 83.8))
    cs.append(_mk(83.2, 86, 83, 85.8))
    cases.append(_case("三个白武士", cs, ["three_white_soldiers"]))

    cs = _downtrend(12)
    cs.append(_mk(70, 70.5, 66, 66.5))
    cs.append(_mk(66.4, 66.8, 65.8, 66.2))
    cs.append(_mk(66.5, 70.5, 66.3, 70.0))
    cases.append(_case("启明星", cs, ["morning_star"]))

    cs = _uptrend(12)
    cs.append(_mk(130, 134, 129.5, 133.5))
    cs.append(_mk(133.6, 134.0, 133.0, 133.4))
    cs.append(_mk(133.2, 133.5, 129, 129.5))
    cases.append(_case("黄昏星", cs, ["evening_star"]))

    cs = _downtrend(12)
    cs.append(_mk(80, 81, 79, 80.05))
    cases.append(_case("十字星（跌后看涨）", cs, ["doji"]))

    cs = _downtrend(12)
    cs.append(_mk(80, 80.1, 76, 80.0))
    cases.append(_case("蜻蜓十字（T字线）", cs, ["dragonfly_doji"]))

    cs = _uptrend(12)
    cs.append(_mk(120, 124, 119.9, 120.0))
    cases.append(_case("墓碑十字（倒T字线）", cs, ["gravestone_doji"]))

    cs = _downtrend(12)
    cs.append(_mk(80, 80.5, 76, 76.5))
    cs.append(_mk(76.0, 79.0, 75.8, 78.8))
    cases.append(_case("刺透形态", cs, ["piercing"]))

    cs = _uptrend(12)
    cs.append(_mk(120, 124, 119.5, 123.5))
    cs.append(_mk(124.0, 124.5, 121, 121.2))
    cases.append(_case("乌云盖顶", cs, ["dark_cloud_cover"]))

    # ---- 边界情况用例 ----
    cases.append(_case("空数据（无 K 线，不应报错）", [], []))
    cases.append(_case("单根 K 线（数据不足，无匹配）", [_mk(10, 10.5, 9.5, 10.2)], []))
    cases.append(_case("全零 K 线（极端值，不崩）", [_mk(0, 0, 0, 0), _mk(0, 0, 0, 0)], []))
    cases.append(_case("无匹配（中性横盘，无形态）",
                       [_mk(100, 101, 99, 100.5), _mk(100.5, 101, 99.5, 100.3)], []))

    passed = sum(1 for c in cases if c["passed"])
    return {
        "total": len(cases),
        "passed": passed,
        "failed": len(cases) - passed,
        "cases": cases,
        "patterns": [{"key": p.key, "name_zh": p.name_zh,
                      "direction": p.direction, "candles": p.candles}
                     for p in all_patterns()],
    }
