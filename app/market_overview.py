# -*- coding: utf-8 -*-
"""
市场分析 —— 指数行情（今日/昨日成交量、成交额）+ 指数 K 线（日/周/月）

数据来源：
- 指数实时行情：腾讯财经实时行情接口（qt.gtimg.cn）
- 指数历史 K 线：腾讯财经 K 线接口（proxy.finance.qq.com）；北证50 走东财（push2his.eastmoney.com）

Author: HZQ
"""
from __future__ import annotations

from datetime import datetime

import requests

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36")

# 统一会话：绕过系统环境代理（避免失效代理导致 ProxyError），直连公网行情接口
_session = requests.Session()
_session.trust_env = False
_session.headers.update({"User-Agent": _UA})

# 关注的指数（symbol=腾讯行情代码, secid=东财代码, name=展示名）
_INDICES = [
    {"symbol": "sh000001", "secid": "1.000001", "name": "上证指数"},
    {"symbol": "sz399001", "secid": "0.399001", "name": "深证成指"},
    {"symbol": "sz399006", "secid": "0.399006", "name": "创业板指"},
    {"symbol": "sh000688", "secid": "1.000688", "name": "科创50"},
    {"symbol": "bj899050", "secid": "0.899050", "name": "北证50"},
    {"symbol": "sh000300", "secid": "1.000300", "name": "沪深300"},
    {"symbol": "sh000016", "secid": "1.000016", "name": "上证50"},
    {"symbol": "sh000852", "secid": "1.000852", "name": "中证1000"},
]

_INDEX_NAME = {i["symbol"]: i["name"] for i in _INDICES}

# 腾讯 K 线时间级别 → (接口参数, 返回字段标签)
_KLINE_TF = {
    "day": ("day", "qfqday"),
    "week": ("week", "qfqweek"),
    "month": ("month", "qfqmonth"),
}


def _get_tencent_quotes() -> dict:
    """腾讯实时行情，返回 {symbol: 字段列表}（GBK 编码文本，~ 分隔）。"""
    syms = ",".join(i["symbol"] for i in _INDICES)
    try:
        r = _session.get("https://qt.gtimg.cn/q=" + syms, timeout=8)
        r.encoding = "gbk"
    except Exception:
        return {}
    out = {}
    for line in r.text.split(";"):
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip().replace("v_", "")
        out[key] = val.strip().strip('"').split("~")
    return out


def _get_index_kline(symbol: str, tf: str = "day", count: int = 120) -> list:
    """指数 K 线，返回升序 [[date, open, close, high, low, volume], ...]。

    北证50 走东财接口（腾讯 fqkline 对 bj899050 仅返回最新 1 根），其余走腾讯。
    """
    if tf not in _KLINE_TF:
        tf = "day"
    if symbol == "bj899050":
        return _get_em_index_kline(symbol, tf, count)
    param_tf, tag = _KLINE_TF[tf]
    try:
        r = _session.get(
            "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get",
            params={"param": f"{symbol},{param_tf},,,{count},qfq"},
            headers={"User-Agent": _UA, "Referer": "https://gu.qq.com/"}, timeout=8,
        )
        data = (r.json().get("data") or {}).get(symbol) or {}
        rows = data.get(tag) or data.get(param_tf) or []
        return rows
    except Exception:
        return []


def _get_em_index_kline(symbol: str, tf: str, count: int) -> list:
    """北证50 指数 K 线（新浪源，腾讯对 bj899050 仅返回 1 根、东财易限流）。

    返回 [[date,open,close,high,low,volume],...] 升序。scale: 240=日 1200=周 7200=月。
    """
    import json as _json
    import urllib.parse as _up
    import urllib.request as _ur
    scale = {"day": 240, "week": 1200, "month": 7200}.get(tf, 240)
    qs = _up.urlencode({"symbol": "bj899050", "scale": scale, "ma": "no", "datalen": count})
    url = ("https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_=/"
           "CN_MarketDataService.getKLineData?" + qs)
    try:
        opener = _ur.build_opener(_ur.ProxyHandler({}))   # 不走系统代理
        req = _ur.Request(url, headers={
            "User-Agent": _UA, "Referer": "https://finance.sina.com.cn/",
        })
        with opener.open(req, timeout=8) as resp:
            txt = resp.read().decode("utf-8", errors="replace")
        data = _json.loads(txt[txt.index("(") + 1: txt.rindex(")")])
        rows = []
        for r in data or []:
            try:
                rows.append([r["day"], r["open"], r["close"], r["high"], r["low"], r["volume"]])
            except (KeyError, TypeError):
                continue
        return rows
    except Exception:
        return []


def get_index_kline(symbol: str, tf: str = "day", count: int = 120) -> dict:
    """指数 K 线数据（含成交量），供前端 ECharts 渲染。"""
    rows = _get_index_kline(symbol, tf, count)
    kline = []
    volume = []
    for r in rows:
        if len(r) < 6:
            continue
        try:
            kline.append([r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4])])
            volume.append([r[0], float(r[5]), float(r[2])])   # [date, vol, close]（close 用于着色）
        except (ValueError, IndexError):
            continue
    return {
        "symbol": symbol,
        "name": _INDEX_NAME.get(symbol, symbol),
        "tf": tf,
        "count": len(kline),
        "kline": kline,
        "volume": volume,
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _get_fund_flow() -> list:
    """东财资金流（上证指数，最近 2 个交易日）。多域名容错 + 重试。"""
    hosts = ("push2delay.eastmoney.com", "push2.eastmoney.com")
    q = {
        "secid": "1.000001",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "klt": "101", "lmt": "5",
    }
    headers = {"User-Agent": _UA, "Referer": "https://finance.eastmoney.com/"}
    for host in hosts:
        for _attempt in range(2):
            try:
                r = _session.get(f"https://{host}/api/qt/stock/fflow/daykline/get",
                                 params=q, headers=headers, timeout=8)
                klines = (r.json().get("data") or {}).get("klines") or []
                if klines:
                    out = []
                    for k in klines[-2:]:   # 今日 + 昨日
                        p = k.split(",")
                        if len(p) < 13:
                            continue
                        out.append({
                            "date": p[0],
                            "main_net": float(p[1]),        # 主力净流入（元）
                            "small_net": float(p[2]),       # 小单净流入
                            "medium_net": float(p[3]),      # 中单净流入
                            "big_net": float(p[4]),         # 大单净流入
                            "super_net": float(p[5]),       # 超大单净流入
                            "main_net_pct": float(p[6]),    # 主力净占比 %
                            "close": float(p[11]),
                            "change_pct": float(p[12]),
                        })
                    return out
            except Exception:
                pass
    return []


def get_market_overview() -> dict:
    """市场分析总览：指数行情 + 资金流向。"""
    quotes = _get_tencent_quotes()
    indices = []
    for idx in _INDICES:
        f = quotes.get(idx["symbol"]) or []
        if len(f) < 38:
            continue
        try:
            price = float(f[3] or 0)
            pre_close = float(f[4] or 0)
            change = float(f[31] or 0)
            change_pct = float(f[32] or 0)
            volume_today = float(f[36] or 0)        # 手
            amount_today_wan = float(f[37] or 0)    # 万元
        except (ValueError, IndexError):
            continue
        # 昨日成交量（取指数日 K 倒数第 2 根，单位：手）
        volume_yesterday = None
        try:
            kline = _get_index_kline(idx["symbol"], "day", 5)
            if len(kline) >= 2:
                volume_yesterday = float(kline[-2][5])
        except Exception:
            pass
        indices.append({
            "name": idx["name"],
            "code": str(f[2]) if len(f) > 2 else idx["symbol"],
            "price": price,
            "pre_close": pre_close,
            "open": float(f[5] or 0),
            "high": float(f[33] or 0) if len(f) > 33 else 0.0,
            "low": float(f[34] or 0) if len(f) > 34 else 0.0,
            "change": change,
            "change_pct": change_pct,
            "volume_today": volume_today,
            "amount_today_wan": amount_today_wan,
            "volume_yesterday": volume_yesterday,
        })
    return {
        "indices": indices,
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
