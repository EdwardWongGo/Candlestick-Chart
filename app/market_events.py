# -*- coding: utf-8 -*-
"""
市场事件数据层 —— 涨停板 / 跌停板 / 烂板 / 连板天梯 / 龙虎榜

数据源：
- 东财 push2ex 涨跌停池（getTopicZTPool）：涨停时间、连板数、炸板次数、封单额、行业
- 同花顺 getharden：涨停原因（题材归因，人工运营 tags）
- 东财 datacenter：龙虎榜（全市场 + 个股席位明细）

说明：东财系接口有风控，本模块内置串行节流（最小间隔 + 随机抖动）避免高频被封。

Author: HZQ
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timedelta
from typing import List, Optional

import requests

import config
from . import limit_analysis as la
from .data.source import get_source, get_quote_source
from .data.cache import KlineCache
from .data.universe import load_universe

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36")
EM_UT = "7eea3edcaed734bea9cbfc24409ed989"
EM_MIN_INTERVAL = 0.8          # 东财请求最小间隔（秒）
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

_cache = KlineCache()
_source = None

_session = requests.Session()
_session.headers.update({"User-Agent": UA})
_em_last = [0.0]


def _em_get(url: str, params: dict, timeout: int = 15, headers: dict = None):
    """东财统一请求入口：节流 + session 复用。"""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.4))
    try:
        return _session.get(url, params=params, headers=headers, timeout=timeout)
    finally:
        _em_last[0] = time.time()


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _fmt_time(v) -> str:
    """92500 -> '09:25:00'；93004 -> '09:30:04'。"""
    if v in (None, "", "-"):
        return "-"
    try:
        s = str(int(v)).zfill(6)
        return f"{s[:2]}:{s[2:4]}:{s[4:6]}"
    except (ValueError, TypeError):
        return "-"


def _market_zh(code: str) -> str:
    m = config.classify_market(code)
    return config.MARKETS.get(m, {}).get("zh", "")


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _to_yyyymmdd(d: str) -> str:
    """'2026-08-14' -> '20260814'"""
    return d.replace("-", "")


def _yyyymmdd_to_dashed(d: str) -> str:
    """'20260814' -> '2026-08-14'"""
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def latest_trade_date(max_back: int = 15) -> str:
    """自动探测最近一个有涨停池数据的交易日（用响应 qdate 校准，跳过周末/节假日）。"""
    d = datetime.now()
    for _ in range(max_back):
        ds = d.strftime("%Y-%m-%d")
        _, qdate = _fetch_limit_pool("wz.ztzt", _to_yyyymmdd(ds))
        if qdate:
            return _yyyymmdd_to_dashed(qdate)
        d -= timedelta(days=1)
    # 兜底：返回最近一个工作日
    return datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 东财涨跌停池
# ---------------------------------------------------------------------------
def _fetch_limit_pool(dpt: str, date_yyyymmdd: str):
    """拉取涨跌停池，返回 (pool, qdate)。

    qdate 为实际交易日（东财对非交易日会返回最近交易日的数据，用 qdate 校准）。
    """
    params = {
        "ut": EM_UT, "dpt": dpt, "Pageindex": "0", "pagesize": "500",
        "sort": "fbt:asc", "date": date_yyyymmdd,
    }
    try:
        r = _em_get("https://push2ex.eastmoney.com/getTopicZTPool", params)
        d = r.json()
        data = d.get("data") or {}
        return data.get("pool") or [], str(data.get("qdate", "") or "")
    except Exception:
        return [], ""


def _pool_to_stocks(pool: List[dict], reason_map: dict) -> List[dict]:
    """把原始 pool 转成前端友好字段，并合并涨停原因。"""
    stocks = []
    for s in pool:
        code = str(s.get("c", "")).zfill(6)
        stocks.append({
            "code": code,
            "name": s.get("n", ""),
            "price": s.get("p", 0),
            "change_pct": round(float(s.get("zdp", 0) or 0), 2),
            "first_time": _fmt_time(s.get("fbt")),        # 首次封板/上板时间
            "last_time": _fmt_time(s.get("lbt")),         # 最后封板时间
            "boards": int(s.get("lbc", 0) or 0),          # 连板数
            "break_count": int(s.get("zbc", 0) or 0),     # 炸板/开板次数
            "fund": round(float(s.get("fund", 0) or 0) / 10000, 1),   # 封单额(万)
            "amount": round(float(s.get("amount", 0) or 0) / 10000, 1),  # 成交额(万)
            "turnover": round(float(s.get("hs", 0) or 0), 2),  # 换手率
            "float_mcap": round(float(s.get("ltsz", 0) or 0) / 100000000, 1),  # 流通市值(亿)
            "industry": s.get("hybk", ""),
            "reason": reason_map.get(code, ""),
            "market_zh": _market_zh(code),
        })
    return stocks


def fetch_reasons(date_dashed: str) -> dict:
    """同花顺涨停原因 → {code: reason}。"""
    url = (f"http://zx.10jqka.com.cn/event/api/getharden/"
           f"date/{date_dashed}/orderby/date/orderway/desc/charset/GBK/")
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        d = r.json()
        if d.get("errocode", 0) != 0:
            return {}
        result = {}
        for row in (d.get("data") or []):
            code = str(row.get("code", "")).zfill(6)
            result[code] = row.get("reason", "")
        return result
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# 各功能接口
# ---------------------------------------------------------------------------
def get_limit_board(direction: str, date_dashed: str = None) -> dict:
    """涨停板(direction='up') / 跌停板(direction='down')。"""
    date_dashed = date_dashed or latest_trade_date()
    ymd = _to_yyyymmdd(date_dashed)
    dpt = "wz.ztzt" if direction == "up" else "wz.dtzt"
    pool, qdate = _fetch_limit_pool(dpt, ymd)
    actual = _yyyymmdd_to_dashed(qdate) if qdate else date_dashed
    reason_map = fetch_reasons(actual) if direction == "up" else {}
    stocks = _pool_to_stocks(pool, reason_map)
    # 涨停板附加 一年/半年/一月涨停次数（本地日线推导）
    if direction == "up":
        stocks = _add_limit_stats(stocks)
    return {
        "date": actual,
        "direction": direction,
        "count": len(stocks),
        "stocks": stocks,
    }


def get_lan_board(date_dashed: str = None) -> dict:
    """烂板：涨停池中炸板(开板)过的股票（zbc>0），含首次上板时间与炸板次数。"""
    date_dashed = date_dashed or latest_trade_date()
    ymd = _to_yyyymmdd(date_dashed)
    pool, qdate = _fetch_limit_pool("wz.ztzt", ymd)
    actual = _yyyymmdd_to_dashed(qdate) if qdate else date_dashed
    reason_map = fetch_reasons(actual)
    # 烂板 = 炸板次数 > 0（最终仍封板）
    broken = [s for s in pool if (s.get("zbc") or 0) > 0]
    stocks = _pool_to_stocks(broken, reason_map)
    for s in stocks:
        s["sealed"] = True          # 涨停池里的都是最终封板的
    return {
        "date": actual,
        "count": len(stocks),
        "stocks": stocks,
    }


def get_ladder(date_dashed: str = None) -> dict:
    """连板天梯：按连板数分组（首板/2板/3板/…N板），每组仅保留核心字段。"""
    date_dashed = date_dashed or latest_trade_date()
    ymd = _to_yyyymmdd(date_dashed)
    pool, qdate = _fetch_limit_pool("wz.ztzt", ymd)
    actual = _yyyymmdd_to_dashed(qdate) if qdate else date_dashed
    reason_map = fetch_reasons(actual)
    stocks = _pool_to_stocks(pool, reason_map)

    # 按连板数分组，每组仅保留 代码/名称/连板数/所属题材
    groups = {}
    for s in stocks:
        b = s["boards"] if s["boards"] >= 2 else 1
        key = b if b >= 2 else 1
        label = f"{b}连板" if b >= 2 else "首板"
        groups.setdefault(key, {"boards": b, "label": label, "stocks": []})
        groups[key]["stocks"].append({
            "code": s["code"], "name": s["name"], "boards": s["boards"],
            "theme": _first_theme(s.get("reason", "")),
        })

    ladder = sorted(groups.values(), key=lambda g: -g["boards"])
    return {
        "date": actual,
        "total": len(stocks),
        "ladder": ladder,
        "height": max((g["boards"] for g in ladder), default=1),
    }


def _first_theme(reason: str) -> str:
    """从涨停原因取第一个题材 tag 作为「所属题材」。"""
    if not reason:
        return ""
    tags = [t.strip() for t in reason.split("+") if t.strip()]
    return tags[0] if tags else ""


# ---------------------------------------------------------------------------
# 龙虎榜
# ---------------------------------------------------------------------------
def _em_datacenter(report_name: str, filter_str: str, page_size: int = 500,
                   sort_columns: str = "", sort_types: str = "-1") -> List[dict]:
    params = {
        "reportName": report_name, "columns": "ALL",
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    r = _em_get(DATACENTER_URL, params)
    try:
        d = r.json()
    except Exception:
        return []
    return (d.get("result") or {}).get("data") or []


def get_dragon_tiger(date_dashed: str = None) -> dict:
    """全市场龙虎榜（当日上榜股票 + 上榜原因 + 买卖净额 + 换手）。"""
    date_dashed = date_dashed or latest_trade_date()
    data = _em_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{date_dashed}')(TRADE_DATE<='{date_dashed}')",
        page_size=500,
        sort_columns="BILLBOARD_NET_AMT", sort_types="-1",
    )
    if not data:
        return {"date": date_dashed, "count": 0, "stocks": [],
                "note": "无数据（非交易日或盘后未更新）"}

    actual_date = str(data[0].get("TRADE_DATE", ""))[:10] if data else date_dashed
    stocks = []
    for row in data:
        code = str(row.get("SECURITY_CODE", "")).zfill(6)
        stocks.append({
            "code": code,
            "name": row.get("SECURITY_NAME_ABBR", ""),
            "reason": row.get("EXPLANATION", ""),
            "close": row.get("CLOSE_PRICE") or 0,
            "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
            "net_buy_wan": round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
            "buy_wan": round((row.get("BILLBOARD_BUY_AMT") or 0) / 10000, 1),
            "sell_wan": round((row.get("BILLBOARD_SELL_AMT") or 0) / 10000, 1),
            "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
            "market_zh": _market_zh(code),
        })
    return {"date": actual_date, "count": len(stocks), "stocks": stocks}


def get_dragon_tiger_seats(code: str, date_dashed: str = None) -> dict:
    """个股龙虎榜席位明细（买卖 TOP5 + 机构动向）。"""
    date_dashed = date_dashed or _today_str()
    code = str(code).zfill(6)

    buy_data = _em_datacenter(
        "RPT_BILLBOARD_DAILYDETAILSBUY",
        filter_str=f"(TRADE_DATE='{date_dashed}')(SECURITY_CODE=\"{code}\")",
        page_size=10, sort_columns="BUY", sort_types="-1",
    )
    sell_data = _em_datacenter(
        "RPT_BILLBOARD_DAILYDETAILSSELL",
        filter_str=f"(TRADE_DATE='{date_dashed}')(SECURITY_CODE=\"{code}\")",
        page_size=10, sort_columns="SELL", sort_types="-1",
    )

    def _seat(row):
        return {
            "name": row.get("OPERATEDEPT_NAME", ""),
            "buy_wan": round((row.get("BUY") or 0) / 10000, 1),
            "sell_wan": round((row.get("SELL") or 0) / 10000, 1),
            "net_wan": round((row.get("NET") or 0) / 10000, 1),
        }

    institution = {"buy_wan": 0.0, "sell_wan": 0.0, "net_wan": 0.0}
    for row in buy_data + sell_data:
        if str(row.get("OPERATEDEPT_CODE", "")) == "0":   # 机构专用席位
            institution["buy_wan"] += (row.get("BUY") or 0) / 10000
            institution["sell_wan"] += (row.get("SELL") or 0) / 10000
    institution = {k: round(v, 1) for k, v in institution.items()}
    institution["net_wan"] = round(institution["buy_wan"] - institution["sell_wan"], 1)

    return {
        "code": code,
        "date": date_dashed,
        "buy_seats": [_seat(r) for r in buy_data[:5]],
        "sell_seats": [_seat(r) for r in sell_data[:5]],
        "institution": institution,
    }


def get_dragon_tiger_history(code: str, days: int = 365) -> dict:
    """个股近 N 天龙虎榜上榜明细（按日期倒序）。"""
    from datetime import date as _date
    code = str(code).zfill(6)
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    data = _em_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{start}')(TRADE_DATE<='{end}')(SECURITY_CODE=\"{code}\")",
        page_size=100, sort_columns="TRADE_DATE", sort_types="-1",
    )
    records = []
    for row in data:
        records.append({
            "date": str(row.get("TRADE_DATE", ""))[:10],
            "reason": row.get("EXPLANATION", ""),
            "net_buy_wan": round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
            "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
            "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
        })
    return {"code": code, "count": len(records), "records": records}


# ---------------------------------------------------------------------------
# 题材热点（新闻催化 + 热门股票）
# ---------------------------------------------------------------------------
def get_hotspots(date_dashed: str = None) -> dict:
    """每日题材热点：聚合涨停原因，统计题材词频，输出题材热度榜 + 各题材热门股票。"""
    from collections import Counter, defaultdict

    zt = get_limit_board("up", date_dashed)
    tag_count = Counter()
    tag_stocks = defaultdict(list)
    for s in zt["stocks"]:
        reason = s.get("reason") or ""
        tags = [t.strip() for t in reason.split("+") if t.strip()]
        for t in tags:
            tag_count[t] += 1
            tag_stocks[t].append({
                "code": s["code"], "name": s["name"],
                "change_pct": s["change_pct"], "boards": s["boards"],
                "first_time": s["first_time"], "market_zh": s["market_zh"],
            })

    themes = []
    for tag, n in tag_count.most_common():
        if n < 2:          # 入选门槛：单题材当日 >= 2 只涨停股
            break
        themes.append({"name": tag, "count": n, "stocks": tag_stocks[tag][:12]})
    return {"date": zt["date"], "total": zt["count"], "themes": themes}


# ---------------------------------------------------------------------------
# 热点新闻（7x24 全球资讯）
# ---------------------------------------------------------------------------
def get_news(limit: int = 100) -> dict:
    """东财全球资讯（7x24 快讯），返回 {news: [{title, summary, time, stocks}]}。"""
    import uuid
    url = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
    params = {
        "client": "web", "biz": "web_724", "fastColumn": "102",
        "sortEnd": "", "pageSize": str(limit),
        "req_trace": str(uuid.uuid4()),
    }
    headers = {"Referer": "https://kuaixun.eastmoney.com/"}
    try:
        r = _em_get(url, params, headers=headers, timeout=10)
        d = r.json()
    except Exception:
        return {"news": []}

    news = []
    for item in (d.get("data") or {}).get("fastNewsList", []):
        # 解析关联股票 stockList，如 ["0.300750"(深), "1.600519"(沪)]；其他市场前缀跳过
        stocks = []
        for s in (item.get("stockList") or []):
            parts = str(s).split(".")
            if len(parts) == 2 and parts[0] in ("0", "1"):
                code = parts[1].zfill(6)
                if code[:6].isdigit() and config.classify_market(code) != "other":
                    stocks.append(code)
        news.append({
            "title": item.get("title", ""),
            "summary": (item.get("summary", "") or "")[:300],
            "time": item.get("showTime", ""),
            "stocks": stocks,
        })
    return {"news": news}


# ---------------------------------------------------------------------------
# 本地日线推导：跌停连板 / 未封板 / 涨停次数 / 周末新闻
# ---------------------------------------------------------------------------
def _get_source():
    global _source
    if _source is None:
        _source = get_source()
    return _source


def _get_daily_bars(code: str):
    """获取某股票日线（优先缓存），返回升序 Candle 列表。"""
    bars = _cache.get(code, "daily")
    if bars is None:
        bars = _get_source().get_bars(code, "daily", config.KLINE_OFFSET)
        if bars:
            bars = bars[-config.MIN_BARS["daily"]:]
            _cache.set(code, "daily", bars)
    return bars


def _universe_names(codes: List[str]) -> dict:
    """批量补齐名称（用于 ST 识别与展示）。"""
    try:
        quotes = get_quote_source().batch_quotes(codes)
        return {c: q.get("name", "") for c, q in quotes.items()}
    except Exception:
        return {}


def _add_limit_stats(stocks: List[dict]) -> List[dict]:
    """给涨停板股票附加 一年/半年/一月涨停次数（本地日线推导）。"""
    for s in stocks:
        bars = _get_daily_bars(s["code"])
        name = s.get("name", "")
        if bars and len(bars) >= 2:
            s["limit_1y"] = la.count_limit_up(bars, s["code"], name, days=245)
            s["limit_6m"] = la.count_limit_up(bars, s["code"], name, days=122)
            s["limit_1m"] = la.count_limit_up(bars, s["code"], name, days=21)
        else:
            s["limit_1y"] = s["limit_6m"] = s["limit_1m"] = None
    return stocks


def get_dt_ladder(full_market: bool = False, date_dashed: str = None) -> dict:
    """跌停连板：扫描股票池，推导连续跌停连板数，按高度分组。"""
    universe = load_universe(full_market)
    codes = universe.codes
    names = dict(universe._names)
    if not names:
        names = _universe_names(codes)

    results = []
    for code in codes:
        bars = _get_daily_bars(code)
        if not bars or len(bars) < 2:
            continue
        name = names.get(code, "") or code
        boards = la.limit_down_boards(bars, code, name)
        if boards >= 1:
            results.append({"code": code, "name": name, "boards": boards})

    groups = {}
    for r in results:
        b = r["boards"]
        key = b if b >= 2 else 1
        label = f"{b}连跌" if b >= 2 else "首跌"
        groups.setdefault(key, {"boards": b, "label": label, "stocks": []})
        groups[key]["stocks"].append(r)
    ladder = sorted(groups.values(), key=lambda g: -g["boards"])
    return {
        "date": date_dashed or latest_trade_date(),
        "total": len(results),
        "ladder": ladder,
        "height": max((g["boards"] for g in ladder), default=0),
    }


def get_unsealed(direction: str = "up", full_market: bool = False,
                 date_dashed: str = None) -> dict:
    """未封板：扫描股票池，推导当日触板未封（涨停/跌停）的股票。"""
    universe = load_universe(full_market)
    codes = universe.codes
    names = dict(universe._names)
    if not names:
        names = _universe_names(codes)

    results = []
    for code in codes:
        bars = _get_daily_bars(code)
        if not bars or len(bars) < 2:
            continue
        name = names.get(code, "") or code
        last, prev = bars[-1], bars[-2]
        hit = (la.is_unsealed_up(last, prev.close, code, name) if direction == "up"
               else la.is_unsealed_down(last, prev.close, code, name))
        if hit:
            results.append({
                "code": code, "name": name,
                "close": round(last.close, 2),
                "change_pct": round((last.close - prev.close) / prev.close * 100, 2)
                if prev.close else 0.0,
                "market_zh": _market_zh(code),
            })
    results.sort(key=lambda r: -r["change_pct"])
    return {
        "date": date_dashed or latest_trade_date(),
        "direction": direction,
        "count": len(results),
        "stocks": results,
    }


def get_weekend_news(limit: int = 200) -> dict:
    """周末热点新闻：筛选最近交易日收盘后到当前的新闻（含节假日边界）。"""
    last_trade = latest_trade_date()
    window_start = datetime.strptime(last_trade + " 15:00:00", "%Y-%m-%d %H:%M:%S")
    now = datetime.now()
    all_news = get_news(limit).get("news", [])
    filtered = []
    for n in all_news:
        try:
            t = datetime.strptime(n["time"], "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            continue
        if window_start <= t <= now:
            n["important"] = bool(n.get("stocks"))   # 带关联股票 = 重点
            filtered.append(n)
    # 重点新闻优先（稳定排序，组内保持最新在前）
    filtered.sort(key=lambda n: not n["important"])
    return {
        "window_start": window_start.strftime("%Y-%m-%d %H:%M"),
        "window_end": now.strftime("%Y-%m-%d %H:%M"),
        "last_trade_date": last_trade,
        "count": len(filtered),
        "news": filtered,
    }
