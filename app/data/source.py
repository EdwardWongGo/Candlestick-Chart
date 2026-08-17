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


# 通达信行情服务器兜底列表（mootdx 默认的 BESTIP 自动探测在部分环境会返回空，
# 导致 Quotes.factory(market="std") 抛 "not enough values to unpack" 崩溃，
# 这里显式提供一批可达服务器，避免依赖其自动探测）
DEFAULT_TDX_SERVERS = [
    ("119.97.185.59", 7709),    # 武汉电信主站1
    ("110.41.147.114", 7709),   # 深圳双线主站1
    ("124.70.199.56", 7709),    # 上海双线主站6
    ("121.36.225.169", 7709),   # 上海双线主站9
    ("123.60.84.66", 7709),     # 上海双线主站15
    ("116.205.163.254", 7709),  # 广州双线主站5
]


class MootdxSource(DataSource):
    """通达信 mootdx 数据源（主）。"""

    name = "mootdx"

    def __init__(self, server: Optional[list] = None):
        self._local = threading.local()   # 线程本地 client，支持多线程并发拉取
        self._server = server             # 自定义服务器，None=使用兜底列表

    def _server_candidates(self) -> list:
        """把自定义服务器归一化为 [(host, port), ...]；未指定时用兜底列表。

        兼容两种写法：("host", port) 或 [("host", port), ...]。
        """
        s = self._server
        if s:
            if isinstance(s, (list, tuple)):
                if len(s) == 2 and not isinstance(s[0], (list, tuple)):
                    return [(str(s[0]), int(s[1]))]
                if s and isinstance(s[0], (list, tuple)):
                    return [(str(x[0]), int(x[1])) for x in s]
            return []
        return list(DEFAULT_TDX_SERVERS)

    def _reachable_server(self):
        """选一个可达的服务器（快速端口探测，避免连接挂起）。"""
        import socket
        candidates = self._server_candidates()
        for host, port in candidates:
            try:
                sk = socket.socket()
                sk.settimeout(2.0)
                sk.connect((host, port))
                sk.close()
                return (host, port)
            except Exception:
                continue
        return candidates[0] if candidates else None

    @property
    def client(self):
        # 线程本地 client：多线程并发拉取时各自持有独立连接，互不干扰
        if not hasattr(self._local, "client"):
            from mootdx.quotes import Quotes
            srv = self._reachable_server()
            if srv is None:
                raise RuntimeError("通达信行情服务器不可用：无可用服务器地址")
            # 显式传入服务器，避免 mootdx 默认 BESTIP 为空时崩溃；
            # 关闭自动重试并缩短超时，避免 K 线接口异常时长时间挂起
            try:
                self._local.client = Quotes.factory(
                    market="std", server=srv,
                    auto_retry=False, raise_exception=True, timeout=8,
                )
            except Exception as e:
                raise RuntimeError(f"通达信行情服务器连接失败（{srv[0]}:{srv[1]}）：{e}") from e
        return self._local.client

    def _frequency(self, timeframe: str) -> int:
        return config.TIMEFRAMES[timeframe]["frequency"]

    def get_bars(self, code: str, timeframe: str, count: int) -> List[Candle]:
        freq = self._frequency(timeframe)
        # 注意：mootdx 0.11.x 的参数名为 frequency（category 会被 **kwargs 吞掉）
        try:
            df = self.client.bars(symbol=code, frequency=freq, offset=count)
        except Exception:
            df = None
        if df is None or len(df) == 0:
            # 通达信 K 线接口被服务端拒绝（返回空）时，兜底走腾讯 HTTP K 线
            return get_fallback_source().get_bars(code, timeframe, count)
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
# 腾讯 K 线数据源（兜底）
# ---------------------------------------------------------------------------
class TencentKlineSource(DataSource):
    """腾讯 HTTP K 线数据源（兜底）。

    通达信 K 线接口（tdxpy get_security_bars）在部分服务端会被拒绝（仅返回
    2 字节异常体），此时用腾讯公开 K 线接口兜底，保证日/周/月线可用。
    """

    name = "tencent_kline"

    # 时间级别 → 腾讯 period
    _PERIOD = {"daily": "day", "weekly": "week", "monthly": "month"}
    _UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36")

    @staticmethod
    def _symbol(code: str) -> str:
        c = str(code).zfill(6)
        prefix = "sh" if c.startswith(("6", "9")) else "sz"
        return prefix + c

    def get_bars(self, code: str, timeframe: str, count: int) -> List[Candle]:
        import requests
        period = self._PERIOD.get(timeframe, "day")
        symbol = self._symbol(code)
        param = f"{symbol},{period},,,{count},qfq"
        try:
            r = requests.get(
                "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
                params={"param": param},
                headers={"User-Agent": self._UA}, timeout=10,
            )
            data = (r.json().get("data") or {}).get(symbol) or {}
            klines = data.get("qfq" + period) or []
        except Exception:
            return []

        candles: List[Candle] = []
        for row in klines:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            try:
                dt = str(row[0])
                o = float(row[1]); c = float(row[2])
                h = float(row[3]); l = float(row[4])
                v = float(row[5])
            except (ValueError, IndexError):
                continue
            candles.append(Candle(dt=dt, open=o, high=h, low=l, close=c, volume=v))
        # klines 已按时间升序，只取最近 count 根
        return candles[-count:] if candles else []


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
_FALLBACK_SOURCE = None


def get_fallback_source() -> TencentKlineSource:
    """获取腾讯 K 线兜底数据源单例。"""
    global _FALLBACK_SOURCE
    if _FALLBACK_SOURCE is None:
        _FALLBACK_SOURCE = TencentKlineSource()
    return _FALLBACK_SOURCE


def get_source(kind: str = None, server: Optional[list] = None) -> DataSource:
    """获取数据源单例。server 为自定义服务器 [(host, port), ...]，None=自动选最快。"""
    global _SOURCE
    if server is not None:
        return MootdxSource(server=server)   # 自定义服务器：不缓存单例，每次新建
    if _SOURCE is None:
        kind = kind or config.DATA_SOURCE
        _SOURCE = MootdxSource() if kind == "mootdx" else MootdxSource()
    return _SOURCE


def get_mootdx_client():
    """获取一个显式指定服务器的 mootdx Quotes 客户端。

    mootdx 默认的 Quotes.factory(market="std") 在其 BESTIP 配置为空时会崩溃
    （not enough values to unpack），这里复用 MootdxSource 的服务器探测逻辑，
    返回一个可用的客户端（供拉取股票列表等场景使用）。
    """
    from mootdx.quotes import Quotes
    src = MootdxSource()
    srv = src._reachable_server()
    if srv is None:
        raise RuntimeError("通达信行情服务器不可用：无可用服务器地址")
    return Quotes.factory(market="std", server=srv,
                          auto_retry=False, raise_exception=True, timeout=8)


def get_quote_source() -> TencentQuoteSource:
    return TencentQuoteSource()
