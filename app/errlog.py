# -*- coding: utf-8 -*-
"""
错误日志 —— 筛选失败时自动落盘，便于后续排查

每次失败生成一个独立文件：output/logs/errlog_YYYYMMDD_HHMMSS.log
内容含：时间戳、触发参数、完整 traceback。

Author: HZQ
"""
from __future__ import annotations

import json
import os
import traceback
from datetime import datetime
from typing import Optional

# 项目根目录（errlog.py 位于 app/ 下，上溯一级）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "output", "logs")


def write_errlog(params: Optional[dict] = None, exc: Optional[BaseException] = None,
                 extra: str = "") -> str:
    """写一份错误日志，返回文件路径。

    params: 触发失败的筛选参数（dict，会做脱敏序列化）
    exc:    异常对象（None 时取当前异常上下文）
    extra:  附加说明
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(LOG_DIR, f"errlog_{ts}.log")

    # 参数脱敏序列化（跳过不可 JSON 化的值）
    try:
        params_str = json.dumps(params, ensure_ascii=False, indent=2, default=str)
    except Exception:
        params_str = str(params)

    with open(path, "w", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat()}] 筛选任务失败\n")
        f.write("=" * 60 + "\n")
        if extra:
            f.write(f"说明：{extra}\n")
        f.write(f"参数：\n{params_str}\n")
        f.write("=" * 60 + "\n")
        f.write("异常堆栈：\n")
        if exc is not None:
            f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        else:
            f.write(traceback.format_exc())
    return path


def list_errlogs(limit: int = 50) -> list:
    """列出最近的错误日志文件（按时间倒序）。"""
    if not os.path.isdir(LOG_DIR):
        return []
    files = sorted(
        (os.path.join(LOG_DIR, f) for f in os.listdir(LOG_DIR) if f.endswith(".log")),
        key=os.path.getmtime, reverse=True,
    )
    return files[:limit]
