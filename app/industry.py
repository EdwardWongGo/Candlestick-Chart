# -*- coding: utf-8 -*-
"""
个股所属行业映射 —— 东财批量查询 + 本地缓存

用途：筛选报告的「行业/概念占比」需要每只股票归属哪个行业。
数据源：东财 push2 ulist 批量接口（f100 字段 = 所属行业，如「白酒Ⅱ」「光伏设备」）。

设计：
- 只对「命中并进入结果」的股票查询，不全市场预拉
- 本地缓存 data/industry.json，7 天有效（行业分类变动很慢）
- 每批 50 只、4 线程并发，仍走 source._throttle() 全局限速

Author: HZQ
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Dict, List

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_PATH = os.path.join(_BASE, "data", "industry.json")
_CACHE_TTL = 7 * 24 * 3600        # 7 天
_BATCH = 50
_WORKERS = 4
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

_lock = threading.Lock()
_mem: Dict[str, str] = {}


def _load_cache() -> Dict[str, str]:
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and time.time() - float(d.get("_ts", 0)) < _CACHE_TTL:
            return {k: v for k, v in d.items() if k != "_ts" and isinstance(v, str)}
    except Exception:
        pass
    return {}


def _save_cache(data: Dict[str, str]):
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        payload = dict(data)
        payload["_ts"] = time.time()
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception:
        pass


def _market_prefix(code: str) -> str:
    c = str(code).zfill(6)
    if c.startswith(("6", "9")):
        return "1."          # 沪市
    if c.startswith(("4", "8")):
        return "0."          # 北交所走 0 前缀可查
    return "0."              # 深市


def _fetch_batch(codes: List[str]) -> Dict[str, str]:
    import urllib.request
    from .data.source import _throttle

    secids = ",".join(_market_prefix(c) + str(c).zfill(6) for c in codes)
    url = ("https://push2.eastmoney.com/api/qt/ulist.np/get"
           "?fltt=2&invt=2&fields=f12,f14,f100&secids=" + secids)
    out: Dict[str, str] = {}
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA, "Referer": "https://quote.eastmoney.com/"})
        _throttle()
        resp = urllib.request.urlopen(req, timeout=10)
        d = json.loads(resp.read().decode("utf-8", "ignore"))
    except Exception:
        return out
    for row in (d.get("data") or {}).get("diff") or []:
        code = str(row.get("f12") or "").zfill(6)
        ind = row.get("f100")
        if code and ind and ind not in ("-", ""):
            out[code] = ind
    return out


def get_industries(codes: List[str]) -> Dict[str, str]:
    """批量取行业名，返回 {code: 行业}；查不到的 code 不出现在结果里。"""
    global _mem
    codes = [str(c).zfill(6) for c in codes if c]
    with _lock:
        if not _mem:
            _mem = _load_cache()
        cached = dict(_mem)

    miss = [c for c in codes if c not in cached]
    if miss:
        from concurrent.futures import ThreadPoolExecutor
        chunks = [miss[i:i + _BATCH] for i in range(0, len(miss), _BATCH)]
        with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
            for part in ex.map(_fetch_batch, chunks):
                cached.update(part)
        with _lock:
            _mem.update(cached)
            _save_cache(_mem)
    return {c: cached[c] for c in codes if c in cached}
