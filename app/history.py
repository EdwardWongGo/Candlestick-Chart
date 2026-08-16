# -*- coding: utf-8 -*-
"""
历史筛选结果 —— 每次筛选完成后把结果缓存到本地文件，供回顾与再次加载

存储：output/history/scan_YYYYMMDD_HHMMSS_<id>.json
每份记录含 {id, ts, params, stats, results}，支持列表/加载/删除。

Author: HZQ
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from typing import List, Optional

# 项目根目录（history.py 位于 app/ 下，上溯一级）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_DIR = os.path.join(BASE_DIR, "output", "history")


def _ensure_dir():
    os.makedirs(HISTORY_DIR, exist_ok=True)


def save_history(params: dict, result: dict) -> Optional[dict]:
    """把一次筛选结果保存为本地历史记录，返回记录摘要。失败返回 None。"""
    try:
        _ensure_dir()
        hid = uuid.uuid4().hex[:8]
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fname = f"scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hid}.json"
        path = os.path.join(HISTORY_DIR, fname)
        record = {
            "id": hid,
            "ts": ts,
            "params": params,
            "stats": result.get("stats") or {},
            "results": result.get("results") or [],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False)
        return _summary(record)
    except Exception:
        return None


def list_history(limit: int = 100) -> List[dict]:
    """列出所有历史记录摘要（按时间倒序）。"""
    if not os.path.isdir(HISTORY_DIR):
        return []
    files = sorted(
        (os.path.join(HISTORY_DIR, f) for f in os.listdir(HISTORY_DIR) if f.endswith(".json")),
        key=os.path.getmtime, reverse=True,
    )
    out = []
    for p in files[:limit]:
        try:
            with open(p, "r", encoding="utf-8") as f:
                rec = json.load(f)
            out.append(_summary(rec))
        except Exception:
            continue
    return out


def load_history(hid: str) -> Optional[dict]:
    """按 id 加载一份完整历史记录。"""
    if not os.path.isdir(HISTORY_DIR):
        return None
    for f in os.listdir(HISTORY_DIR):
        if f.endswith(".json") and hid in f:
            try:
                with open(os.path.join(HISTORY_DIR, f), "r", encoding="utf-8") as fp:
                    rec = json.load(fp)
                return rec
            except Exception:
                return None
    return None


def delete_history(hid: str) -> bool:
    """按 id 删除一份历史记录。"""
    if not os.path.isdir(HISTORY_DIR):
        return False
    for f in os.listdir(HISTORY_DIR):
        if f.endswith(".json") and hid in f:
            try:
                os.remove(os.path.join(HISTORY_DIR, f))
                return True
            except OSError:
                return False
    return False


def _summary(rec: dict) -> dict:
    """生成历史记录摘要（不含完整 results，避免列表过重）。"""
    params = rec.get("params") or {}
    stats = rec.get("stats") or {}
    return {
        "id": rec.get("id"),
        "ts": rec.get("ts"),
        "timeframes": params.get("timeframes") or [],
        "markets": params.get("markets") or [],
        "matched_rows": stats.get("matched_rows", 0),
        "matched_stocks": stats.get("matched_stocks", 0),
        "total_samples": stats.get("total_samples", 0),
    }
