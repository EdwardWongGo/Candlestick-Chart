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

import os
import threading
import time
from datetime import datetime, timedelta
from typing import List, Optional

from ..models import Candle
from .cache import KlineCache, _period_key
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
        if len(vals) < 54:
            return {}

        def _f(x, default=0.0):
            try:
                return float(x) if x not in ("", "-") else default
            except (ValueError, TypeError):
                return default

        # 腾讯行情快照字段（~ 分隔，索引见下）：
        #  1名称 3现价 4昨收 5今开 7外盘 8内盘 32涨跌% 33最高 34最低
        #  36成交量(手) 37成交额(万) 38换手% 43振幅% 44流通市值(亿) 45总市值(亿) 51均价 52动态PE
        return {
            "name": vals[1],
            "price": _f(vals[3]),          # 现价 / 收盘价
            "last_close": _f(vals[4]),     # 昨收
            "open": _f(vals[5]),           # 开盘价
            "high": _f(vals[33]),          # 最高价
            "low": _f(vals[34]),           # 最低价
            "change_pct": _f(vals[32]),    # 涨跌幅 %
            "volume": _f(vals[36]),        # 成交量（手）
            "amount": _f(vals[37]),        # 成交额（万）
            "turnover": _f(vals[38]),      # 换手率 %
            "amplitude": _f(vals[43]),     # 振幅 %
            "float_mcap": _f(vals[44]),    # 流通市值（亿）
            "market_cap": _f(vals[45]),    # 总市值（亿）
            "avg_price": _f(vals[51]),     # 均价
            "dynamic_pe": _f(vals[52]),    # 动态市盈
            "outer_disc": _f(vals[7]),     # 外盘（手）
            "inner_disc": _f(vals[8]),     # 内盘（手）
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
                    "market_cap": _f(vals[45]),    # 总市值（亿）
                    "float_mcap": _f(vals[44]),    # 流通市值（亿）
                }
        return result


# ---------------------------------------------------------------------------
# 腾讯 K 线数据源（兜底）
# ---------------------------------------------------------------------------
class TencentKlineSource(DataSource):
    """腾讯财经 HTTP K 线数据源（统一兜底源）。

    通达信 K 线接口（tdxpy get_security_bars）在部分服务端会被拒绝（仅返回
    2 字节异常体），此时用腾讯公开 K 线接口兜底，保证日/周/月线可用。

    多域名容错：主域名 web.ifzq.gtimg.cn 对部分出口 IP（如机房/数据中心）
    会被 WAF 拦截，故先尝试备用域名 proxy.finance.qq.com（同接口）。
    """

    name = "tencent_kline"

    # 时间级别 → 腾讯 period
    _PERIOD = {"daily": "day", "weekly": "week", "monthly": "month"}
    # (域名, 路径)：备用域名 proxy.finance.qq.com 需带 /ifzqgtimg 前缀；
    # 主域名 web.ifzq.gtimg.cn 路径不同，作为第二候选。
    _HOSTS = (
        ("proxy.finance.qq.com", "/ifzqgtimg/appstock/app/fqkline/get"),
        ("web.ifzq.gtimg.cn", "/appstock/app/fqkline/get"),
    )
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
        candles: List[Candle] = []
        for host, path in self._HOSTS:
            try:
                r = requests.get(
                    f"https://{host}{path}",
                    params={"param": param},
                    headers={"User-Agent": self._UA,
                             "Referer": "https://gu.qq.com/"},
                    timeout=10,
                )
                data = (r.json().get("data") or {}).get(symbol) or {}
                klines = data.get("qfq" + period) or data.get(period) or []
            except Exception:
                continue  # 该域名失败，尝试下一个

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
            if candles:
                break
        # klines 已按时间升序，只取最近 count 根
        return candles[-count:] if candles else []


class SinaKlineSource(DataSource):
    """新浪财经 HTTP K 线数据源（备用节点，日线/周线）。

    月线新浪无公开周期接口，返回空并由上层回退到腾讯财经源。
    """

    name = "sina_kline"

    # 时间级别 → 新浪 scale（240=日线, 1200=周线）
    _SCALE = {"daily": "240", "weekly": "1200"}
    _UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36")

    @staticmethod
    def _symbol(code: str) -> str:
        c = str(code).zfill(6)
        prefix = "sh" if c.startswith(("6", "9")) else "sz"
        return prefix + c

    def get_bars(self, code: str, timeframe: str, count: int) -> List[Candle]:
        import re
        import requests
        scale = self._SCALE.get(timeframe)
        if not scale:
            return []  # 月线不支持，交给上层回退
        symbol = self._symbol(code)
        url = ("https://quotes.sina.cn/cn/api/jsonp_v2.php/"
               f"var%20_{symbol}=/CN_MarketDataService.getKLineData"
               f"?symbol={symbol}&scale={scale}&ma=no&datalen={count}")
        try:
            r = requests.get(url, headers={"User-Agent": self._UA},
                             timeout=10)
            m = re.search(r"\[(.*)\]", r.text, re.S)
            rows = json.loads("[" + m.group(1) + "]") if m else []
        except Exception:
            return []
        candles: List[Candle] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                candles.append(Candle(
                    dt=str(row["day"])[:10],
                    open=float(row["open"]), high=float(row["high"]),
                    low=float(row["low"]), close=float(row["close"]),
                    volume=float(row.get("volume", 0) or 0),
                ))
            except (ValueError, KeyError, TypeError):
                continue
        # 新浪按时间升序返回，只取最近 count 根
        if not candles:
            # 备用节点无数据（或月线不支持）→ 回退腾讯财经兜底源
            return get_fallback_source().get_bars(code, timeframe, count)
        return candles[-count:] if candles else []


# ---------------------------------------------------------------------------
# 全量历史 K 线（日线全量 + 周/月聚合；独立缓存，不影响筛选缓存性能）
# ---------------------------------------------------------------------------
_FULL_CACHE = KlineCache("data/full")
_FULL_PAGE = 800          # 腾讯接口单次最多 800 根日线
_FULL_MAX_PAGES = 40      # 最多拉 32000 根，覆盖 A 股全部历史
_FQ_DIR = os.path.join("data", "full", "daily")   # 复权方式标记（{code}.fq）
_FULL_BLOCK_UNTIL = 0     # 腾讯全量接口失败后的冷却截止（避免 WAF 拦截时持续请求）


def get_full_fq(code: str) -> str:
    """读取全量 K 线的复权方式（qfq/hfq），默认 qfq。"""
    try:
        with open(os.path.join(_FQ_DIR, f"{str(code).zfill(6)}.fq"), "r", encoding="utf-8") as f:
            v = f.read().strip()
            return v if v in ("qfq", "hfq") else "qfq"
    except Exception:
        return "qfq"


def _write_fq(code: str, fq: str):
    try:
        os.makedirs(_FQ_DIR, exist_ok=True)
        with open(os.path.join(_FQ_DIR, f"{str(code).zfill(6)}.fq"), "w", encoding="utf-8") as f:
            f.write(fq)
    except Exception:
        pass


def _tencent_symbol(code: str) -> str:
    c = str(code).zfill(6)
    if c.startswith(("6", "9")):
        return "sh" + c
    if c.startswith(("4", "8")):
        return "bj" + c
    return "sz" + c


def _fetch_tencent_daily(code: str, end: Optional[str] = None,
                        count: int = _FULL_PAGE, fq: str = "qfq") -> List[Candle]:
    """腾讯日线：拉取 end 之前（含）最近 count 根，升序返回。

    fq: "qfq" 前复权 / "hfq" 后复权 / "" 不复权。
    """
    import requests
    symbol = _tencent_symbol(code)
    param = f"{symbol},day,,{end or ''},{count},{fq}"
    day_key = (fq + "day") if fq else "day"
    for host, path in TencentKlineSource._HOSTS:
        try:
            r = requests.get(
                f"https://{host}{path}",
                params={"param": param},
                headers={"User-Agent": TencentKlineSource._UA,
                         "Referer": "https://gu.qq.com/"},
                timeout=15,
            )
            if r.status_code != 200:
                continue   # 403/501（WAF 拦截）等，换域名
            data = (r.json().get("data") or {}).get(symbol) or {}
            klines = data.get(day_key) or data.get("day") or []
        except Exception:
            continue
        candles: List[Candle] = []
        for row in klines:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            try:
                candles.append(Candle(
                    dt=str(row[0])[:10],
                    open=float(row[1]), close=float(row[2]),
                    high=float(row[3]), low=float(row[4]),
                    volume=float(row[5]),
                ))
            except (ValueError, IndexError, TypeError):
                continue
        if candles:
            candles.sort(key=lambda c: c.dt)
            return candles
    return []


def _fetch_full_daily(code: str, fq: str = "qfq",
                      max_pages: int = _FULL_MAX_PAGES) -> List[Candle]:
    """从最近往前按日期区间分段拉取，直到上市首日或达到页数上限。"""
    global _FULL_BLOCK_UNTIL
    if time.time() < _FULL_BLOCK_UNTIL:
        return []   # 冷却中（数据源刚失败），直接让上层回退缓存
    by_dt = {}
    end = None
    for _ in range(max_pages):
        batch = _fetch_tencent_daily(code, end=end, fq=fq)
        if not batch:
            _FULL_BLOCK_UNTIL = time.time() + 60   # 失败后冷却 60 秒
            break
        for c in batch:
            by_dt[c.dt] = c
        # 不足一页 → 该日期之前已无更多数据（到上市首日）
        if len(batch) < _FULL_PAGE:
            break
        earliest = batch[0].dt
        if earliest <= "1991-01-01":
            break
        try:
            prev = (datetime.strptime(earliest, "%Y-%m-%d")
                    - timedelta(days=1)).strftime("%Y-%m-%d")
        except ValueError:
            break
        if end == prev:
            break
        end = prev
    return [by_dt[k] for k in sorted(by_dt)]


def _aggregate_daily(candles: List[Candle], timeframe: str) -> List[Candle]:
    """日线聚合为周线/月线：开取首日、高取最大、低取最小、收取末日、量求和。"""
    if timeframe == "daily" or not candles:
        return candles
    groups = {}
    order = []
    for c in candles:
        key = _period_key(c.dt, timeframe)
        g = groups.get(key)
        if g is None:
            groups[key] = Candle(dt=c.dt, open=c.open, high=c.high,
                                 low=c.low, close=c.close, volume=c.volume)
            order.append(key)
        else:
            groups[key] = Candle(
                dt=c.dt, open=g.open,
                high=max(g.high, c.high), low=min(g.low, c.low),
                close=c.close, volume=g.volume + c.volume,
            )
    return [groups[k] for k in order]


def get_full_bars(code: str, timeframe: str = "daily") -> List[Candle]:
    """获取股票全量历史 K 线（日线全量；周/月线由日线聚合）。

    - 全量缓存：data/full/daily/{code}.csv（与筛选缓存 data/daily 隔离，
      避免把全量塞进筛选缓存后拖慢全市场扫描）
    - 首次：腾讯日线按日期区间分段拉取（每段 800 根，直到上市首日）；
      复权方式优先前复权，出现负价则整只改用后复权
    - 缓存 6 小时内直接使用，过期后整只重新拉取（约 1s）
    """
    if timeframe not in ("daily", "weekly", "monthly"):
        return []
    bars = _FULL_CACHE.get(code, "daily", ttl=6 * 3600)
    # 防御：旧缓存若含前复权负价（累计分红超过股价），丢弃重拉
    if bars and min(c.low for c in bars) <= 0:
        bars = None
    if not bars:
        # 优先前复权；若全量中出现 <=0 的早期价格（累计分红超过股价），
        # 整只改用后复权（连续、无负价、无除权缺口）
        fq = "qfq"
        bars = _fetch_full_daily(code, fq=fq)
        if bars and min(c.low for c in bars) <= 0:
            fq = "hfq"
            bars = _fetch_full_daily(code, fq=fq)
        if bars:
            try:
                _FULL_CACHE.set(code, "daily", bars)
                _write_fq(code, fq)
            except Exception:
                pass
    return _aggregate_daily(bars, timeframe) if bars else []


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


# 单例缓存（按数据源 kind 分别缓存，便于切换数据服务器预设）
_SOURCES: dict = {}
_FALLBACK_SOURCE = None


def get_fallback_source() -> TencentKlineSource:
    """获取腾讯 K 线兜底数据源单例（统一最终兜底源）。"""
    global _FALLBACK_SOURCE
    if _FALLBACK_SOURCE is None:
        _FALLBACK_SOURCE = TencentKlineSource()
    return _FALLBACK_SOURCE


def _resolve_source(kind: Optional[str]) -> DataSource:
    """按预设 kind 构造数据源。kind 未知名时回退通达信。"""
    k = (kind or config.DEFAULT_SERVER_PRESET).lower()
    if k in ("tencent", "tencent_public", "tencent_kline"):
        return TencentKlineSource()
    if k in ("sina", "sina_public", "sina_kline"):
        return SinaKlineSource()
    # tdx / tdx_public / mootdx / 其它未知 → 通达信（内部空时自动回退腾讯）
    return MootdxSource()


def get_source(kind: str = None, server: Optional[list] = None) -> DataSource:
    """获取数据源。server 为自定义通达信服务器 [(host, port), ...]；kind 为预设键名。

    自定义服务器不缓存（每次新建）；预设源按 kind 缓存单例，切换预设后生效。
    """
    if server is not None:
        return MootdxSource(server=server)
    kind = (kind or config.DEFAULT_SERVER_PRESET).lower()
    if kind not in _SOURCES:
        _SOURCES[kind] = _resolve_source(kind)
    return _SOURCES[kind]


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


def _fetch_history_minute(symbol: str, date: str) -> Optional[list]:
    """腾讯历史分时：day/query 返回最近 5 个交易日的分时，按日期取指定日。

    返回条目列表（"HHMM 价格 累计量 累计额"）；该日期不在最近 5 日则返回 None。
    """
    import json
    import urllib.request
    url = f"https://web.ifzq.gtimg.cn/appstock/app/day/query?code={symbol}"
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        r = json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "ignore"))
    except Exception:
        return None
    d = (r.get("data") or {}).get(symbol) or {}
    arr = d.get("data") or []
    key = str(date).replace("-", "")[:8]
    for item in arr:
        if isinstance(item, dict) and str(item.get("date")) == key:
            return item.get("data") or []
    return None


def get_minute_data(code: str, date: Optional[str] = None) -> dict:
    """腾讯财经分时数据（1 分钟），返回 {"minutes": [...], "error": ...}。

    - date 为空：当日分时（minute/query）
    - date 指定：该日历史分时（day/query，仅最近 5 个交易日可用）

    条目格式：[HHMM, 价格, 累计成交量(手), 累计成交额(元)]；
    逐分钟均价 = 累计成交额 / (累计成交量 * 100 股)。
    """
    import json
    import urllib.request
    symbol = _market_prefix(code) + str(code).zfill(6)

    if date:
        rows = _fetch_history_minute(symbol, date)
        if rows is None:
            return {"minutes": [],
                    "error": f"分时数据仅保留最近 5 个交易日，{date} 的分时不可用"}
    else:
        url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={symbol}"
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0")
            resp = urllib.request.urlopen(req, timeout=10)
            r = json.loads(resp.read().decode("utf-8", "ignore"))
        except Exception:
            return {"minutes": [], "error": "分时数据获取失败"}
        d = (r.get("data") or {}).get(symbol) or {}
        rows = d.get("data", {}).get("data", []) or []

    minutes = []
    prev_vol = 0.0
    for row in rows:
        # 腾讯分时每条是空格分隔字符串 "HHMM 价格 累计成交量(手) 累计成交额(元)"
        if isinstance(row, str):
            row = row.split()
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        try:
            t = str(row[0])
            price = float(row[1])
            cum_vol = float(row[2])                    # 累计成交量（手）
            cum_amt = float(row[3]) if len(row) > 3 else 0.0  # 累计成交额（元）
        except (ValueError, IndexError, TypeError):
            continue
        avg = (cum_amt / (cum_vol * 100)) if cum_vol > 0 else price
        per_vol = max(0.0, cum_vol - prev_vol)
        prev_vol = cum_vol
        minutes.append({
            "t": (t[:2] + ":" + t[2:4]) if len(t) >= 4 else t,
            "price": round(price, 2),
            "avg": round(avg, 2),
            "volume": per_vol,       # 该分钟成交量（手）
        })
    return {"minutes": minutes}
