# -*- coding: utf-8 -*-
"""
数据源层 —— 统一抽象接口 + 通达信(mootdx)/腾讯 实现

设计要点：
1. DataSource 为抽象基类，屏蔽底层差异。未来扩展「实时监控」只需新增实现：
   - 盘中实时：mootdx category 7-11（1/5/15/30/60 分钟线）轮询
   - 或接入行情推送/第三方实时源，不动上层筛选引擎。
2. 主数据源 mootdx（通达信 TCP 7709）：日/周/月线，不封 IP，无需鉴权。
3. 行情快照走腾讯财经（名称/现价/涨跌幅），不封 IP。
4. 所有 K 线读取优先命中本地缓存（app/data/cache.py），减少重复拉取。

Author: HZQ
"""
from __future__ import annotations

import threading
import time
from typing import List, Optional

from ..models import Candle
import config


class DataSource:
    """K 线数据源抽象接口。"""

    name = "base"

    def get_bars(self, code: str, timeframe: str, count: int) -> List[Candle]:
        """返回按时间升序的 K 线列表（最新一根在末尾）。"""
        raise NotImplementedError

    def get_quote(self, code: str) -> dict:
        """返回实时/最新快照 {name, price, change_pct, ...}。"""
        return {}


class MootdxSource(DataSource):
    """通达信 mootdx 数据源（主）。"""

    name = "mootdx"

    def __init__(self, server: Optional[list] = None):
        self._local = threading.local()   # 线程本地 client，支持多线程并发拉取
        self._server = server             # 自定义服务器 [(host, port), ...]，None=自动选最快

    @property
    def client(self):
        # 线程本地 client：多线程并发拉取时各自持有独立连接，互不干扰
        if not hasattr(self._local, "client"):
            from mootdx.quotes import Quotes
            # 有自定义服务器则用之，否则自动选最快服务器，缓存 client
            if self._server:
                self._local.client = Quotes.factory(market="std", server=self._server)
            else:
                self._local.client = Quotes.factory(market="std")
        return self._local.client

    def _frequency(self, timeframe: str) -> int:
        return config.TIMEFRAMES[timeframe]["frequency"]

    def get_bars(self, code: str, timeframe: str, count: int) -> List[Candle]:
        freq = self._frequency(timeframe)
        # 注意：mootdx 0.11.x 的参数名为 frequency（category 会被 **kwargs 吞掉）
        df = self.client.bars(symbol=code, frequency=freq, offset=count)
        if df is None or len(df) == 0:
            return []
        # mootdx 返回的 df 中 datetime 可能同时作为索引和列，仅当缺少该列时才 reset_index
        if "datetime" not in df.columns:
            df = df.reset_index()
        candles: List[Candle] = []
        for _, row in df.iterrows():
            dt = _fmt_dt(row.get("datetime"))
            if dt is None:
                continue
            candles.append(Candle(
                dt=dt,
                open=float(row.get("open", 0) or 0),
                high=float(row.get("high", 0) or 0),
                low=float(row.get("low", 0) or 0),
                close=float(row.get("close", 0) or 0),
                volume=float(row.get("vol", 0) or row.get("volume", 0) or 0),
            ))
        # 保证升序
        candles.sort(key=lambda c: c.dt)
        return candles


class TencentQuoteSource(DataSource):
    """腾讯财经行情快照（名称/现价/涨跌幅）。"""

    name = "tencent"

    def get_quote(self, code: str) -> dict:
        import urllib.request
        prefix = _market_prefix(code)
        url = f"https://qt.gtimg.cn/q={prefix}{code}"
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0")
            resp = urllib.request.urlopen(req, timeout=8)
            data = resp.read().decode("gbk", errors="ignore")
        except Exception:
            return {}
        if '"' not in data:
            return {}
        vals = data.split('"')[1].split("~")
        if len(vals) < 50:
            return {}

        def _f(x, default=0.0):
            try:
                return float(x) if x not in ("", "-") else default
            except (ValueError, TypeError):
                return default

        return {
            "name": vals[1],
            "price": _f(vals[3]),
            "last_close": _f(vals[4]),
            "change_pct": _f(vals[32]),
            "high": _f(vals[33]),
            "low": _f(vals[34]),
        }


    def batch_quotes(self, codes: List[str]) -> dict:
        """批量拉取行情快照（每批最多 60 只），返回 {code: {name, price, change_pct}}。"""
        import urllib.request
        result = {}
        codes = [str(c).zfill(6) for c in codes]
        for start in range(0, len(codes), 60):
            chunk = codes[start:start + 60]
            prefixed = [_market_prefix(c) + c for c in chunk]
            url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
            try:
                req = urllib.request.Request(url)
                req.add_header("User-Agent", "Mozilla/5.0")
                resp = urllib.request.urlopen(req, timeout=10)
                data = resp.read().decode("gbk", errors="ignore")
            except Exception:
                continue
            for line in data.strip().split(";"):
                if not line.strip() or "=" not in line or '"' not in line:
                    continue
                key = line.split("=")[0].split("_")[-1]
                vals = line.split('"')[1].split("~")
                if len(vals) < 50:
                    continue
                code = key[2:]

                def _f(x, default=0.0):
                    try:
                        return float(x) if x not in ("", "-") else default
                    except (ValueError, TypeError):
                        return default

                result[code] = {
                    "name": vals[1],
                    "price": _f(vals[3]),
                    "change_pct": _f(vals[32]),
                }
        return result


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _market_prefix(code: str) -> str:
    """6 位代码 → 市场前缀（sh/sz/bj）。"""
    c = str(code).zfill(6)
    if c.startswith(("6", "9")):
        return "sh"
    if c.startswith("8") or c.startswith("4"):
        return "bj"
    return "sz"


def _fmt_dt(dt) -> Optional[str]:
    """把 mootdx 的 datetime / Timestamp 转成 'YYYY-MM-DD'。"""
    if dt is None:
        return None
    s = str(dt)
    # 常见形态：'2026-08-14 15:00:00' 或 Timestamp
    return s[:10]


# 单例缓存
_SOURCE = None


def get_source(kind: str = None, server: Optional[list] = None) -> DataSource:
    """获取数据源单例。server 为自定义服务器 [(host, port), ...]，None=自动选最快。"""
    global _SOURCE
    if server is not None:
        return MootdxSource(server=server)   # 自定义服务器：不缓存单例，每次新建
    if _SOURCE is None:
        kind = kind or config.DATA_SOURCE
        _SOURCE = MootdxSource() if kind == "mootdx" else MootdxSource()
    return _SOURCE


def get_quote_source() -> TencentQuoteSource:
    return TencentQuoteSource()
