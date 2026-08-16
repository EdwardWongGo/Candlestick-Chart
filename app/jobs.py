# -*- coding: utf-8 -*-
"""
后台扫描任务管理 —— 支持长时全市场扫描 + 进度轮询 + 取消 + 结果缓存 + 错误日志

因全市场扫描（约 5000 只 × 3 级别）耗时较长，Web 端通过
「提交任务 → 轮询状态」的方式异步执行，避免 HTTP 请求超时。

新增能力：
- cancel(job_id)：随时中断扫描
- last()：返回最近一次成功结果（供前端切换功能后快速恢复，无需重算）
- 失败自动写 errlog 到 output/logs/

Author: HZQ
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Dict, Optional

from .screener import Screener, ScanCancelled
from .errlog import write_errlog


class JobManager:
    """内存态任务管理（单进程）。"""

    def __init__(self):
        self._jobs: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._screener = Screener()
        self._last_result: Optional[dict] = None   # 最近一次成功结果缓存

    # ------------------------------------------------------------------
    def submit(self, params: dict) -> str:
        job_id = uuid.uuid4().hex[:12]
        job = {
            "id": job_id,
            "status": "running",   # running / done / error / cancelled
            "progress": 0,          # 0-100
            "message": "任务已提交",
            "params": params,
            "result": None,
            "error": None,
            "cancelled": False,
            "started_at": time.time(),
        }
        with self._lock:
            self._jobs[job_id] = job

        t = threading.Thread(target=self._run, args=(job_id, params), daemon=True)
        t.start()
        return job_id

    # ------------------------------------------------------------------
    def cancel(self, job_id: str) -> bool:
        """请求取消任务。返回是否成功标记。"""
        job = self._jobs.get(job_id)
        if job is None or job["status"] != "running":
            return False
        job["cancelled"] = True
        job["message"] = "正在停止…"
        return True

    # ------------------------------------------------------------------
    def _run(self, job_id: str, params: dict):
        job = self._jobs[job_id]

        def cb(done, total, msg):
            pct = int(done / total * 100) if total else 100
            job["progress"] = min(99, pct)
            job["message"] = msg

        def should_cancel():
            return bool(job.get("cancelled"))

        try:
            result = self._screener.scan(params, progress_cb=cb,
                                         cancel_cb=should_cancel)
            job["progress"] = 100
            job["status"] = "done"
            job["message"] = f"扫描完成，命中 {result['total']} 条"
            job["result"] = result
            # 零命中处理：命中 0 条时不写结果缓存、不写历史记录，也不更新 last_result
            if result["total"] > 0:
                # 结果缓存：保存最近一次成功结果 + 参数 + 时间戳
                self._last_result = {
                    "params": params,
                    "result": result,
                    "ts": time.time(),
                }
                # 历史筛选结果：每次有效筛选（命中>0）完成后缓存到本地文件
                try:
                    from .history import save_history
                    save_history(params, result)
                except Exception:
                    pass
        except ScanCancelled:
            job["status"] = "cancelled"
            job["message"] = "已停止筛选"
            job["error"] = "cancelled"
        except Exception as e:  # noqa: BLE001
            job["status"] = "error"
            job["error"] = str(e)
            job["message"] = f"扫描出错：{e}"
            # 失败自动落盘 errlog
            try:
                path = write_errlog(params=params, exc=e, extra="形态筛选任务执行失败")
                job["errlog"] = path
            except Exception:
                job["errlog"] = None

    # ------------------------------------------------------------------
    def status(self, job_id: str) -> dict:
        job = self._jobs.get(job_id)
        if job is None:
            return {"id": job_id, "status": "not_found"}
        return {
            "id": job["id"],
            "status": job["status"],
            "progress": job["progress"],
            "message": job["message"],
            "error": job["error"],
            "errlog": job.get("errlog"),
            "result": job["result"] if job["status"] == "done" else None,
        }

    # ------------------------------------------------------------------
    def last(self) -> Optional[dict]:
        """返回最近一次成功结果（含参数与结果）。"""
        if not self._last_result:
            return None
        return {
            "params": self._last_result["params"],
            "result": self._last_result["result"],
            "ts": self._last_result["ts"],
        }

    # ------------------------------------------------------------------
    def cleanup(self, max_jobs: int = 20):
        """保留最近 max_jobs 个任务。"""
        with self._lock:
            if len(self._jobs) > max_jobs:
                for jid in list(self._jobs.keys())[:-max_jobs]:
                    self._jobs.pop(jid, None)
