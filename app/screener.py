# -*- coding: utf-8 -*-
"""
多级别筛选引擎 —— 日线/周线/月线独立扫描 + 跨级别共振确认

核心流程：
1. 加载股票池，逐级别、逐股票拉取 K 线（带缓存）
2. 每个级别独立跑形态识别，得到命中列表
3. 对命中结果套用附加过滤条件（放量倍数/价格/涨跌幅/相对位置/ST剔除）
4. 跨级别共振：同一股票在 >= RESONANCE_MIN_LEVELS 个级别出现同方向信号 → 共振
5. 信号强度 = 形态强度 × 级别权重 + 共振加成；按强度/时间排序

Author: HZQ
"""
from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

import config
from .models import Candle, PatternMatch, ScanResult
from .patterns import detect_patterns
from .indicators import change_pct, above_ma250
from .limit_analysis import count_limit_up
from .data.source import get_source, get_quote_source
from .data.cache import KlineCache
from .data.universe import load_universe, Universe


DIRECTION_ZH = {"bullish": "看涨", "bearish": "看跌", "neutral": "中性"}


def _ytd_change(bars: List[Candle]) -> float:
    """年内涨幅：今年首个交易日至最新收盘的累计涨幅(%)。"""
    if not bars:
        return 0.0
    latest = bars[-1]
    year = latest.dt[:4]
    first = None
    for b in bars:
        if b.dt.startswith(year):
            first = b
            break
    if first is None or first.close == 0:
        return 0.0
    return (latest.close - first.close) / first.close * 100


class ScanCancelled(Exception):
    """扫描被用户主动取消。"""


class Screener:
    """蜡烛图形态多级别筛选器。"""

    def __init__(self, source=None, cache=None):
        self.source = source or get_source()
        self.cache = cache or KlineCache()

    # ------------------------------------------------------------------
    def scan(self, params: dict,
             progress_cb: Optional[Callable[[int, int, str], None]] = None,
             cancel_cb: Optional[Callable[[], bool]] = None) -> Dict:
        """执行一次扫描。

        params 字段：
          timeframes:  ['daily','weekly','monthly']  选中的级别（至少一个）
          patterns:    [pattern_key,...] 或 None=全部
          directions:  ['bullish','bearish'] 或 None=全部
          volume_min:  放量倍数下限（None=不限）
          price_min / price_max: 价格区间
          change_min / change_max: 涨跌幅区间（%）
          exclude_st:  剔除 ST
          markets:     ['sh','sz','bj','kcb','cyb'] 或 None=不限（可多选）
          above_ma250: 是否要求最新价在年线（MA250）之上
          custom_codes: 导入的自定义股票代码列表（优先于本地股票池）
          sync:        是否在筛选前先同步服务器最新数据到本地（勾选「同步服务器数据」）
          limit_up_count_min: 近一年涨停次数下限（None=不限）

        cancel_cb: 取消回调，返回 True 时中断扫描并抛 ScanCancelled。

        返回 {results, total, elapsed, universe_size, scanned, stats, sync_status}
        """
        t0 = time.time()
        timeframes = params.get("timeframes") or ["daily"]
        timeframes = [t for t in timeframes if t in config.TIMEFRAMES]
        if not timeframes:
            timeframes = ["daily"]

        patterns = params.get("patterns") or None
        verify_patterns = params.get("verify_patterns") or None   # 需要验证的形态（追加1天验证日）
        directions = params.get("directions") or None
        exclude_st = params.get("exclude_st", True)
        sync = params.get("sync", False)                     # 是否筛选前同步服务器数据
        self.sync = sync                                     # 供 _get_bars 决定缓存读取策略
        limit_up_count_min = params.get("limit_up_count_min")  # 近一年涨停次数下限

        # 1. 股票池（导入的自定义代码优先，否则统一用本地全市场列表）
        #    注意：用 is not None 区分「未传」(None) 与「传入空列表」(应返回空结果)
        custom_codes = params.get("custom_codes")
        if custom_codes is not None:
            universe = Universe().from_list(custom_codes)
        else:
            universe = load_universe()
        codes = universe.codes
        names = dict(universe._names)

        # 1.1 市场过滤（上证/深证/北证/科创/创业，可多选；空 = 不限）
        markets = params.get("markets") or None
        if markets:
            codes = [c for c in codes if config.classify_market(c) in markets]

        # 统一进度：同步 + 扫描 合并为一个连续进度条（避免进度从 99% 回退到 0%）
        sync_tasks = len(codes) * len(timeframes) if sync else 0
        scan_tasks = len(codes) * len(timeframes)
        total_tasks = sync_tasks + scan_tasks

        # 1.1a 同步服务器数据：勾选后，筛选前先把最新数据增量同步到本地
        sync_status = None
        if sync:
            from .sync import sync_incremental
            def _sync_cb(d, t, msg):
                if progress_cb:
                    progress_cb(d, total_tasks, f"同步 {msg}")
            sync_status = sync_incremental(codes, timeframes,
                                           progress_cb=_sync_cb,
                                           cancel_cb=cancel_cb)
            if sync_status.get("cancelled"):
                raise ScanCancelled()

        # 1.1b 近一年涨停次数预筛（基于日线推导，可与其他条件自由组合）
        limit_1y_map: Dict[str, int] = {}
        ytd_map: Dict[str, float] = {}      # 年内涨幅缓存（命中股票才拉日线计算）
        if limit_up_count_min is not None:
            kept = []
            total = len(codes)
            for idx, c in enumerate(codes):
                bars = self._get_bars(c, "daily")
                cnt = count_limit_up(bars, c, names.get(c, ""), days=245) if bars else 0
                limit_1y_map[c] = cnt
                if cnt >= limit_up_count_min:
                    kept.append(c)
                if progress_cb:
                    progress_cb(idx + 1, total, f"预筛涨停次数 {c}")
            codes = kept

        # 1.2 批量补齐名称（demo 池 / 导入代码无名称时走腾讯批量，避免逐只请求）
        missing_names = [c for c in codes if not names.get(c)]
        if missing_names:
            try:
                quotes = get_quote_source().batch_quotes(missing_names)
                for c, q in quotes.items():
                    names[c] = q.get("name", "")
            except Exception:
                pass

        # 1.3 年线 MA250 预筛（基于日线，可与其他条件自由组合）
        check_ma250 = params.get("above_ma250", False)
        ma250_above_count = 0
        if check_ma250:
            ma250_pass: Dict[str, bool] = {}
            total = len(codes)
            for idx, code in enumerate(codes):
                bars = self._get_bars(code, "daily")
                ok = above_ma250(bars)
                ma250_pass[code] = bool(ok)
                if ok:
                    ma250_above_count += 1
                if progress_cb:
                    progress_cb(idx + 1, total, f"预筛年线 {code}")
            codes = [c for c in codes if ma250_pass.get(c, False)]

        # 市场分布统计（最终进入扫描的样本）
        market_dist: Dict[str, int] = {}
        for c in codes:
            m = config.classify_market(c)
            market_dist[m] = market_dist.get(m, 0) + 1
        total_samples = len(codes)

        results: List[ScanResult] = []
        done = sync_tasks                             # 从同步结束处继续（统一进度）
        failed = 0                                   # 单只失败计数（容错，不中断整体）
        per_code_matches: Dict[str, Dict[str, List[PatternMatch]]] = {}
        per_code_close: Dict[str, float] = {}
        per_code_bars: Dict[str, Dict[str, List[Candle]]] = {}   # 缓存已读取的 bars，供第 3 阶段复用

        def _cancelled() -> bool:
            return bool(cancel_cb and cancel_cb())

        for code in codes:
            if _cancelled():
                raise ScanCancelled()
            per_code_matches[code] = {}
            per_code_bars[code] = {}
            for tf in timeframes:
                if _cancelled():
                    raise ScanCancelled()
                try:
                    bars = self._get_bars(code, tf)
                except Exception:
                    # 单只股票数据拉取异常：跳过，不中断整批扫描
                    failed += 1
                    done += 1
                    if progress_cb:
                        progress_cb(done, total_tasks, f"扫描 {code} {tf}（拉取失败，跳过）")
                    continue
                if not bars:
                    done += 1
                    continue
                # 剔除 ST
                name = names.get(code, "")
                if exclude_st and _is_st(name):
                    done += 1
                    continue
                try:
                    matches = detect_patterns(bars, keys=patterns,
                                              lookback=config.SCAN_LOOKBACK,
                                              verify_keys=verify_patterns)
                except Exception:
                    failed += 1
                    done += 1
                    continue
                if directions:
                    matches = [m for m in matches if m.direction in directions]
                per_code_bars[code][tf] = bars          # 复用：第 3 阶段不再重复读缓存
                if matches:
                    per_code_matches[code][tf] = matches
                    per_code_close[code] = bars[-1].close
                done += 1
                if progress_cb:
                    progress_cb(done, total_tasks, f"扫描 {code} {tf}")

        # 3. 过滤 + 生成结果行（仅对有命中的股票计算涨停次数，避免全市场无谓的日线拉取）
        for code in codes:
            if _cancelled():
                raise ScanCancelled()
            name = names.get(code, "") or _resolve_name(code)
            close = per_code_close.get(code, 0.0)
            matched_tfs = [tf for tf in timeframes if per_code_matches.get(code, {}).get(tf)]
            if not matched_tfs:
                continue
            # 近一年涨停次数 + 年内涨幅（本地日线推导）—— 仅命中股票才拉日线
            limit_1y = limit_1y_map.get(code)
            ytd = ytd_map.get(code)
            if limit_1y is None or ytd is None:
                try:
                    daily_bars = self._get_bars(code, "daily")
                    if limit_1y is None:
                        limit_1y = count_limit_up(daily_bars, code, name, days=245) if daily_bars else 0
                    if ytd is None:
                        ytd = _ytd_change(daily_bars) if daily_bars else 0.0
                except Exception:
                    if limit_1y is None:
                        limit_1y = 0
                    if ytd is None:
                        ytd = 0.0
                limit_1y_map[code] = limit_1y
                ytd_map[code] = ytd
            for tf in matched_tfs:
                matches = per_code_matches[code][tf]
                # 直接复用第 2 阶段已读取的 bars，避免重复读缓存/触发过期重拉（性能关键）
                bars = per_code_bars.get(code, {}).get(tf)
                if not bars:
                    continue
                for m in matches:
                    row = self._build_row(code, name, tf, m, bars, close, params, limit_1y, ytd)
                    if row is not None:
                        results.append(row)

        # 4. 跨级别共振
        self._apply_resonance(results)

        # 5. 排序
        sort_by = params.get("sort_by", "change_pct")   # 默认按涨跌幅排序
        results = self._sort(results, sort_by)

        elapsed_ms = int((time.time() - t0) * 1000)   # 总耗时（毫秒，精确）
        matched_stocks = len({r.code for r in results})
        return {
            "results": [r.to_dict() for r in results],
            "total": len(results),
            "elapsed": round(elapsed_ms / 1000, 2),   # 兼容旧的秒级字段
            "elapsed_ms": elapsed_ms,                 # 精确到毫秒
            "universe_size": total_samples,
            "scanned": done,
            "failed": failed,
            "sync_status": sync_status,              # 本次是否同步了服务器数据
            "stats": {
                "total_samples": total_samples,       # 总样本数（进入形态扫描的股票）
                "matched_rows": len(results),         # 命中行数
                "matched_stocks": matched_stocks,     # 命中股票数（去重）
                "market_dist": market_dist,           # 市场分布 {market: count}
                "ma250_above": ma250_above_count if check_ma250 else None,
            },
        }

    # ------------------------------------------------------------------
    def _get_bars(self, code: str, tf: str) -> List[Candle]:
        """优先读缓存，否则拉取并写缓存。

        缓存读取策略（性能关键）：
        - 未同步数据（sync=False）：忽略 ttl，只要有本地缓存就直接用（"基于本地数据"），
          避免缓存超过 1 小时被判定过期而重新网络拉取，这是未同步时筛选慢的主因。
        - 同步数据（sync=True）：同步阶段已把最新数据增量写入缓存（sync_incremental），
          此处用默认 ttl 即可命中新鲜缓存。
        """
        ttl = None if not getattr(self, "sync", False) else 3600
        cached = self.cache.get(code, tf, ttl=ttl)
        if cached is not None:
            return cached
        bars = self.source.get_bars(code, tf, config.KLINE_OFFSET)
        if bars:
            # 按需裁剪到 MIN_BARS 并落盘（筛选本身即累积本地缓存）
            min_bars = config.MIN_BARS.get(tf, 120)
            bars = bars[-min_bars:]
            self.cache.set(code, tf, bars)
        return bars

    def _build_row(self, code, name, tf, m: PatternMatch, bars: List[Candle],
                   close: float, params: dict, limit_1y: int = 0, ytd: float = 0.0) -> Optional[ScanResult]:
        """套用附加过滤条件，通过则返回 ScanResult。"""
        i = m.index
        k = bars[i]

        # 放量倍数
        vr = m.volume_ratio
        volume_min = params.get("volume_min")
        if volume_min is not None and vr < volume_min:
            return None

        # 价格区间（用信号当日收盘价）
        price = k.close
        price_min = params.get("price_min")
        price_max = params.get("price_max")
        if price_min is not None and price < price_min:
            return None
        if price_max is not None and price > price_max:
            return None

        # 涨跌幅区间
        chg = change_pct(bars, i)
        change_min = params.get("change_min")
        change_max = params.get("change_max")
        if change_min is not None and chg < change_min:
            return None
        if change_max is not None and chg > change_max:
            return None

        # 相对位置字段已废弃（「相对位置」筛选条件与展示列均已移除），
        # 不再做 O(60) 的支撑阻力计算，仅保留占位，避免无谓开销拖慢全市场扫描
        pos = -1.0

        # 级别权重
        weight = config.TIMEFRAMES[tf]["weight"]
        strength = min(100.0, m.strength * weight)

        market = config.classify_market(code)
        market_zh = config.MARKETS.get(market, {}).get("zh", "")

        return ScanResult(
            code=code,
            name=name,
            market=market,
            market_zh=market_zh,
            timeframe=tf,
            timeframe_zh=config.TIMEFRAMES[tf]["zh"],
            pattern_zh=m.name_zh,
            pattern_en=m.name_en,
            direction=m.direction,
            direction_zh=DIRECTION_ZH.get(m.direction, m.direction),
            date=m.date,
            strength=round(strength, 1),
            volume_ratio=vr,
            close=price,
            change_pct=round(chg, 2),
            position=-1.0,
            position_label="",
            resonance=False,
            resonance_levels=[],
            candle_indexes=m.candle_indexes,
            limit_1y=limit_1y,
            ytd_change=ytd,
        )

    def _apply_resonance(self, results: List[ScanResult]):
        """跨级别共振：同股票同方向在 >=2 个级别出现 → 共振，强度加成。"""
        # 按 (code, direction) 分组
        groups: Dict[tuple, List[ScanResult]] = {}
        for r in results:
            if r.direction in ("bullish", "bearish"):
                groups.setdefault((r.code, r.direction), []).append(r)

        for (code, direction), rows in groups.items():
            levels = sorted({r.timeframe for r in rows})
            if len(levels) >= config.RESONANCE_MIN_LEVELS:
                for r in rows:
                    r.resonance = True
                    r.resonance_levels = levels
                    r.strength = round(min(100.0, r.strength + config.RESONANCE_BONUS), 1)

    def _sort(self, results: List[ScanResult], sort_by: str) -> List[ScanResult]:
        if sort_by == "date":
            results.sort(key=lambda r: (r.date, -r.strength), reverse=True)
        elif sort_by == "limit_1y":
            results.sort(key=lambda r: (-r.limit_1y, -r.strength))
        elif sort_by == "change_pct":
            results.sort(key=lambda r: r.change_pct, reverse=True)
        elif sort_by == "strength":
            results.sort(key=lambda r: (r.resonance, r.strength), reverse=True)
        else:
            results.sort(key=lambda r: r.strength, reverse=True)
        return results


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _is_st(name: str) -> bool:
    """名称含 ST（含 *ST、退市整理等）即视为风险警示股。"""
    n = (name or "").upper()
    return "ST" in n or "退" in n


def _resolve_name(code: str) -> str:
    """腾讯拉取股票名称兜底。"""
    try:
        q = get_quote_source().get_quote(code)
        return q.get("name", "") or code
    except Exception:
        return code


def filter_direction(matches: List[PatternMatch], directions) -> List[PatternMatch]:
    if not directions:
        return matches
    return [m for m in matches if m.direction in directions]
