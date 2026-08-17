# -*- coding: utf-8 -*-
"""
个股研报 —— 东财 reportapi 拉取最近一年研报列表

数据源：东方财富研报公开 JSON API（免费无 key）
字段：标题 / 发布日期 / 机构 / 评级 / EPS 预测 / PDF 链接

东财防封：串行限流（间隔 >= 1s + 随机抖动）+ 会话复用（Keep-Alive）+ 带 UA/Referer

Author: HZQ
"""
from __future__ import annotations

import random
import threading
import time
from datetime import datetime, timedelta
from typing import List, Optional

import requests

REPORT_API = "https://reportapi.eastmoney.com/report/list"
PDF_TPL = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# ---- 东财防封：串行限流 + 会话复用 ----
_session = requests.Session()
_session.headers.update({"User-Agent": UA})
_lock = threading.Lock()
_last_call = 0.0
MIN_INTERVAL = 1.0          # 两次东财请求最小间隔（秒）


def _em_get(url: str, params: dict, timeout: int = 30) -> Optional[requests.Response]:
    """东财统一请求：串行限流 + 复用会话 + 默认 UA/Referer。"""
    global _last_call
    with _lock:
        wait = MIN_INTERVAL - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait + random.uniform(0.1, 0.4))
        try:
            resp = _session.get(
                url, params=params, timeout=timeout,
                headers={"Referer": "https://data.eastmoney.com/"},
            )
        finally:
            _last_call = time.time()
        return resp


def fetch_reports(code: str, days: int = 365, max_pages: int = 5) -> List[dict]:
    """获取指定股票最近 days 天内的研报列表（按发布日期倒序）。

    code:      6 位股票代码
    days:      回溯天数（默认 365 = 最近一年）
    max_pages: 最多翻页数（pageSize=100/页，通常 1~3 页足够）
    """
    begin = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    end = datetime.now().strftime("%Y-%m-%d")

    records: List[dict] = []
    for page in range(1, max_pages + 1):
        params = {
            "industryCode": "*", "pageSize": "100", "industry": "*",
            "rating": "*", "ratingChange": "*",
            "beginTime": begin, "endTime": end,
            "pageNo": str(page), "fields": "", "qType": "0",
            "orgCode": "", "code": code, "rcode": "",
            "p": str(page), "pageNum": str(page), "pageNumber": str(page),
        }
        try:
            resp = _em_get(REPORT_API, params=params)
            data = resp.json()
        except Exception:
            break
        rows = data.get("data") or []
        if not rows:
            break
        records.extend(rows)
        total_page = data.get("TotalPage", 1) or 1
        if page >= total_page:
            break

    # 清洗为前端友好结构
    result = []
    for r in records:
        info_code = r.get("infoCode", "")
        result.append({
            "title": r.get("title", ""),
            "date": (r.get("publishDate") or "")[:10],
            "org": r.get("orgSName", "") or r.get("orgName", ""),
            "rating": r.get("emRatingName", "") or "",
            "rating_change": _rating_change_text(r),
            "author": _parse_authors(r.get("author") or r.get("researcher")),
            "industry": r.get("indvInduName", "") or "",
            "target_price": r.get("indvAimPriceT"),
            "target_low": r.get("indvAimPriceL"),
            "eps_this": r.get("predictThisYearEps"),
            "eps_next": r.get("predictNextYearEps"),
            "eps_next2": r.get("predictNextTwoYearEps"),
            "stock_name": r.get("stockName", ""),
            "pdf_url": PDF_TPL.format(info_code=info_code) if info_code else "",
        })

    result.sort(key=lambda x: x["date"], reverse=True)
    return result


def _rating_change_text(r: dict) -> str:
    """评级变化：对比 emRatingValue 与 lastEmRatingValue，上调/下调；维持返回空。"""
    cur, last = r.get("emRatingValue"), r.get("lastEmRatingValue")
    try:
        cur_f, last_f = float(cur), float(last)
    except (TypeError, ValueError):
        return ""
    if last_f is None:
        return ""
    if cur_f > last_f:
        return "上调"
    if cur_f < last_f:
        return "下调"
    return ""


def _parse_authors(raw) -> str:
    """东财 author 形如 ['11000306631.孙山山', '11000311233.张向伟']，解析为人名列表。"""
    if not raw:
        return ""
    import re
    names = re.findall(r"\.([\u4e00-\u9fa5A-Za-z]+)", str(raw))
    if names:
        return "、".join(names)
    return str(raw).strip("[]'\"").strip()


def search_stocks(keyword: str, limit: int = 10) -> List[dict]:
    """按股票名称或代码模糊搜索，返回 [{code, name}]（来自本地股票池）。"""
    kw = (keyword or "").strip().upper()
    if not kw:
        return []
    try:
        from .data.universe import load_universe
        u = load_universe()
        codes = u.codes
    except Exception:
        return []
    matched = []
    for c in codes:
        name = ""
        try:
            name = u.name_of(c) or ""
        except Exception:
            pass
        if kw in str(c) or (name and kw in name.upper().replace(" ", "")):
            matched.append({"code": c, "name": name})
            if len(matched) >= limit:
                break
    return matched
