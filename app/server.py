# -*- coding: utf-8 -*-
"""
Flask Web 服务 —— REST API + 静态前端托管

端点：
  GET  /api/health                     健康检查
  GET  /api/meta                       形态库 + 时间级别 + 市场板块元信息
  POST /api/scan                       提交扫描任务（返回 job_id）
  GET  /api/scan/status/<job_id>       轮询任务进度与结果
  GET  /api/kline/<code>?tf=daily      K 线 + 均线 + 命中形态（图上高亮用）
  POST /api/import                     导入股票代码（TXT/CSV 文本），校验并返回成功/失败数
  GET  /api/selftest                   形态引擎自检（测试入口）
  POST /api/export                     导出 CSV（传 job_id 或 results）
  GET  /                               前端页面

Author: HZQ
"""
from __future__ import annotations

import csv
import io
import os
import threading
from datetime import datetime

from flask import Flask, jsonify, request, send_file, send_from_directory

import config
from .patterns import all_patterns
from .indicators import compute_ma
from .data.source import get_source, get_quote_source
from .data.cache import KlineCache
from .data.universe import parse_codes
from .patterns import detect_patterns
from .jobs import JobManager
from .selftest import run_selftest
from .sync import get_sync_status, sync_incremental
from .history import list_history, load_history, delete_history
from .market_events import (
    get_limit_board, get_lan_board, get_ladder,
    get_dragon_tiger, get_dragon_tiger_seats, latest_trade_date,
    get_hotspots, get_news,
    get_dt_ladder, get_daily_news, get_dragon_tiger_history,
    get_seal_rate, get_opened,
)
from .market_overview import get_market_overview


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(BASE_DIR, "web")

app = Flask(__name__, static_folder=WEB_DIR, static_url_path="/static")
app.config["JSON_AS_ASCII"] = False

_jobs = JobManager()
_cache = KlineCache()


# ---------------------------------------------------------------------------
# 元信息
# ---------------------------------------------------------------------------
@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "data_source": config.DATA_SOURCE})


@app.route("/api/meta")
def meta():
    patterns = []
    for p in all_patterns():
        patterns.append({
            "key": p.key,
            "name_zh": p.name_zh,
            "name_en": p.name_en,
            "direction": p.direction,
            "candles": p.candles,
            "desc": p.desc,
        })
    timeframes = [
        {"key": k, "zh": v["zh"], "weight": v["weight"], "desc": v["desc"]}
        for k, v in config.TIMEFRAMES.items()
    ]
    markets = [
        {"key": k, "zh": v["zh"]} for k, v in config.MARKETS.items()
    ]
    return jsonify({
        "patterns": patterns,
        "timeframes": timeframes,
        "markets": markets,
        "ma250_period": config.MA250_PERIOD,
        "resonance_min_levels": config.RESONANCE_MIN_LEVELS,
        "server_presets": [
            {"key": p["key"], "zh": p["zh"], "source": p["source"],
             "desc": p["desc"], "kind": p["kind"]}
            for p in config.SERVER_PRESETS
        ],
        "default_server_preset": config.DEFAULT_SERVER_PRESET,
        "sync_timeframes": config.SYNC_TIMEFRAMES,
    })


# ---------------------------------------------------------------------------
# 文件导入（股票代码）
# ---------------------------------------------------------------------------
@app.route("/api/import", methods=["POST"])
def import_codes():
    body = request.get_json(silent=True) or {}
    text = body.get("text", "")
    valid, invalid = parse_codes(text)

    # 批量解析名称
    names = {}
    if valid:
        try:
            names = get_quote_source().batch_quotes(valid)
        except Exception:
            names = {}

    # 按市场分组统计
    market_dist = {}
    for c in valid:
        m = config.classify_market(c)
        market_dist[m] = market_dist.get(m, 0) + 1

    return jsonify({
        "total": len(valid) + len(invalid),
        "valid_count": len(valid),
        "invalid_count": len(invalid),
        "valid_codes": valid,
        "invalid_entries": invalid[:50],        # 失败样例最多返回 50 个
        "names": names,                         # {code: {name, price, change_pct}}
        "market_dist": market_dist,
    })


# ---------------------------------------------------------------------------
# 形态引擎自检（测试入口）
# ---------------------------------------------------------------------------
@app.route("/api/selftest")
def selftest():
    return jsonify(run_selftest())


# ---------------------------------------------------------------------------
# 市场事件：涨停板 / 跌停板 / 烂板 / 连板天梯 / 龙虎榜
# ---------------------------------------------------------------------------
@app.route("/api/board/<kind>")
def board(kind):
    date = request.args.get("date") or None
    if kind == "zt":
        return jsonify(get_limit_board("up", date))
    if kind == "dt":
        return jsonify(get_limit_board("down", date))
    if kind == "lan":
        return jsonify(get_lan_board(date))
    return jsonify({"error": "未知板块类型"}), 400


@app.route("/api/ladder")
def ladder():
    date = request.args.get("date") or None
    return jsonify(get_ladder(date))


@app.route("/api/ladder-down")
def ladder_down():
    return jsonify(get_dt_ladder())


@app.route("/api/news/daily")
def daily_news():
    return jsonify(get_daily_news())


@app.route("/api/seal-rate/<direction>")
def seal_rate(direction):
    """封板率（今日/昨日）：direction=up 涨停 / down 跌停。"""
    if direction not in ("up", "down"):
        return jsonify({"error": "未知方向"}), 400
    return jsonify(get_seal_rate(direction))


@app.route("/api/opened/<direction>")
def opened(direction):
    """涨停/跌停打开（今日/昨日）。"""
    if direction not in ("up", "down"):
        return jsonify({"error": "未知方向"}), 400
    return jsonify(get_opened(direction))


@app.route("/api/market/overview")
def market_overview():
    """市场分析：指数行情（今日/昨日成交量、成交额）+ 资金流向。"""
    return jsonify(get_market_overview())


@app.route("/api/dragon-tiger/history/<code>")
def dragon_tiger_history(code):
    days = request.args.get("days", 365, type=int)
    return jsonify(get_dragon_tiger_history(code, days))


@app.route("/api/dragon-tiger")
def dragon_tiger():
    date = request.args.get("date") or None
    return jsonify(get_dragon_tiger(date))


@app.route("/api/dragon-tiger/<code>")
def dragon_tiger_seats(code):
    date = request.args.get("date") or None
    return jsonify(get_dragon_tiger_seats(code, date))


@app.route("/api/latest-trade-date")
def latest_date():
    return jsonify({"date": latest_trade_date()})


@app.route("/api/hotspot")
def hotspot():
    date = request.args.get("date") or None
    return jsonify(get_hotspots(date))


@app.route("/api/news")
def news():
    limit = request.args.get("limit", 100, type=int)
    return jsonify(get_news(limit))


# ---------------------------------------------------------------------------
# 扫描
# ---------------------------------------------------------------------------
@app.route("/api/scan", methods=["POST"])
def scan():
    params = request.get_json(silent=True) or {}
    job_id = _jobs.submit(params)
    _jobs.cleanup()
    return jsonify({"job_id": job_id})


@app.route("/api/scan/status/<job_id>")
def scan_status(job_id):
    return jsonify(_jobs.status(job_id))


@app.route("/api/scan/cancel/<job_id>", methods=["POST"])
def scan_cancel(job_id):
    ok = _jobs.cancel(job_id)
    return jsonify({"cancelled": ok})


@app.route("/api/scan/last")
def scan_last():
    """返回最近一次成功筛选结果（供前端切换功能后快速恢复，无需重算）。"""
    last = _jobs.last()
    if last is None:
        return jsonify({"has_result": False})
    return jsonify({
        "has_result": True,
        "params": last["params"],
        "result": last["result"],
        "ts": last["ts"],
    })


# ---------------------------------------------------------------------------
# 数据同步（同步服务器数据）
# ---------------------------------------------------------------------------
@app.route("/api/sync/status")
def sync_status():
    """返回上次数据同步时间、同步统计与本地缓存状态。"""
    st = get_sync_status()
    # 本地缓存文件数（供「本地数据」来源判断是否可用/置灰）
    cache_files = 0
    try:
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
        if os.path.isdir(data_dir):
            for tf in ("daily", "weekly", "monthly"):
                d = os.path.join(data_dir, tf)
                if os.path.isdir(d):
                    cache_files += len([f for f in os.listdir(d) if f.endswith(".csv")])
    except Exception:
        pass
    st["cache_files"] = cache_files
    return jsonify(st)


# 全局同步取消事件：POST /api/cancel-sync 置位，sync_incremental 的 cancel_cb 检查后中断
_SYNC_CANCEL = threading.Event()


@app.route("/api/cancel-sync", methods=["POST"])
def cancel_sync():
    """中断当前进行中的数据同步（返回后同步接口尽快以 cancelled=true 结束）。"""
    _SYNC_CANCEL.set()
    return jsonify({"ok": True})


@app.route("/api/sync", methods=["POST"])
def sync_now():
    """手动触发一次数据同步（默认同步本地全市场股票池，可指定数据服务器）。
    时间级别默认取 config.SYNC_TIMEFRAMES（日/周/月三级别），可由请求体覆盖。

    body.server 取值：
      - 数据服务器预设键名（如 tdx_public / tencent_public / sina_public）
      - 自定义地址 "host:port"（通达信内网/专线行情源）
      - 空 → 使用 config.DEFAULT_SERVER_PRESET
    """
    _SYNC_CANCEL.clear()   # 每次同步开始前重置取消标志
    body = request.get_json(silent=True) or {}
    codes = body.get("codes") or None
    timeframes = body.get("timeframes") or config.SYNC_TIMEFRAMES
    server_sel = body.get("server")

    # 解析数据服务器：预设键名 → source_kind；"host:port" → 自定义通达信
    source_kind = None
    custom_server = None
    if server_sel:
        preset = next((p for p in config.SERVER_PRESETS if p["key"] == server_sel), None)
        if preset and preset["kind"] != "custom":
            source_kind = preset["kind"]
        elif ":" in str(server_sel):
            try:
                host, port = str(server_sel).rsplit(":", 1)
                custom_server = [(host.strip(), int(port))]
            except Exception:
                custom_server = None
        # custom 预设未带地址时回退默认源

    if codes:
        from .data.universe import Universe
        u = Universe().from_list(codes)
        codes = u.codes
    else:
        from .data.universe import load_universe
        try:
            codes = load_universe().codes
        except Exception as e:
            return jsonify({
                "error": f"获取股票池失败（请确认网络可访问行情服务器）：{e}",
                "synced": 0, "failed": 0, "empty": 0,
            }), 500
    if not codes:
        return jsonify({"error": "股票池为空，无法同步", "synced": 0, "failed": 0, "empty": 0}), 400
    try:
        result = sync_incremental(codes, timeframes,
                                  server=custom_server, source_kind=source_kind,
                                  cancel_cb=lambda: _SYNC_CANCEL.is_set())
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"同步失败：{e}", "synced": 0, "failed": 0, "empty": 0}), 500


# ---------------------------------------------------------------------------
# 历史筛选结果
# ---------------------------------------------------------------------------
@app.route("/api/history")
def history_list():
    return jsonify({"history": list_history()})


@app.route("/api/history/batch", methods=["POST"])
def history_batch_delete():
    """批量删除历史筛选结果。body: {ids: [hid, ...]}。"""
    body = request.get_json(silent=True) or {}
    ids = body.get("ids") or []
    deleted = 0
    for hid in ids:
        if delete_history(hid):
            deleted += 1
    return jsonify({"deleted": deleted, "requested": len(ids)})


@app.route("/api/history/<hid>", methods=["GET", "DELETE"])
def history_item(hid):
    if request.method == "DELETE":
        return jsonify({"deleted": delete_history(hid)})
    rec = load_history(hid)
    if rec is None:
        return jsonify({"error": "历史记录不存在"}), 404
    return jsonify(rec)


# ---------------------------------------------------------------------------
# K 线数据（图上高亮）
# ---------------------------------------------------------------------------
@app.route("/api/kline/<code>")
def kline(code):
    tf = request.args.get("tf", "daily")
    if tf not in config.TIMEFRAMES:
        return jsonify({"error": "未知级别"}), 400

    # K 线历史是追加式的，忽略 ttl 直接用本地缓存（避免缓存过期后重复拉取）
    bars = _cache.get(code, tf, ttl=None)
    if bars is None:
        try:
            bars = get_source().get_bars(code, tf, config.KLINE_OFFSET)
        except Exception:
            bars = None
        if bars:
            try:
                _cache.set(code, tf, bars)   # 写缓存失败不影响返回（文件锁等）
            except Exception:
                pass

    if not bars:
        return jsonify({"error": f"{code} 无 K 线数据"}), 404

    # 均线：5 / 10 / 15 / 20 / 120 / 250 日
    ma5 = compute_ma(bars, 5)
    ma10 = compute_ma(bars, 10)
    ma15 = compute_ma(bars, 15)
    ma20 = compute_ma(bars, 20)
    ma120 = compute_ma(bars, 120)
    ma250 = compute_ma(bars, 250)

    candles = []
    for i, c in enumerate(bars):
        candles.append({
            "dt": c.dt, "open": c.open, "high": c.high,
            "low": c.low, "close": c.close, "volume": c.volume,
            "ma5": _round(ma5[i]), "ma10": _round(ma10[i]),
            "ma15": _round(ma15[i]), "ma20": _round(ma20[i]),
            "ma120": _round(ma120[i]), "ma250": _round(ma250[i]),
        })

    matches = detect_patterns(bars)
    return jsonify({
        "code": code,
        "timeframe": tf,
        "timeframe_zh": config.TIMEFRAMES[tf]["zh"],
        "candles": candles,
        "matches": [m.to_dict() for m in matches],
    })


# ---------------------------------------------------------------------------
# CSV 导出
# ---------------------------------------------------------------------------
@app.route("/api/export", methods=["POST"])
def export_csv():
    body = request.get_json(silent=True) or {}
    job_id = body.get("job_id")
    results = body.get("results")

    if job_id:
        status = _jobs.status(job_id)
        if status.get("result"):
            results = status["result"].get("results", [])
        else:
            return jsonify({"error": "任务结果不可用"}), 400

    if not results:
        return jsonify({"error": "无结果可导出"}), 400

    fieldnames = [
        "股票代码", "股票名称", "市场板块", "所属级别", "形态名称", "形态英文",
        "信号强度", "放量倍数", "现价",
        "年内涨幅%", "近一年涨停次数", "多级别共振",
    ]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(fieldnames)
    for r in results:
        writer.writerow([
            r.get("code"), r.get("name"), r.get("market_zh"),
            r.get("timeframe_zh"),
            r.get("pattern_zh"), r.get("pattern_en"),
            r.get("strength"), r.get("volume_ratio"), r.get("close"),
            r.get("ytd_change"), r.get("limit_1y"),
            "是" if r.get("resonance") else "否",
        ])

    data = buf.getvalue()
    fname = f"A股蜡烛图形态筛选_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    mem = io.BytesIO()
    mem.write("\ufeff".encode("utf-8"))   # BOM，保证 Excel 正确识别 UTF-8
    mem.write(data.encode("utf-8"))
    mem.seek(0)
    return send_file(
        mem, mimetype="text/csv", as_attachment=True,
        download_name=fname,
    )


@app.route("/api/export/ebk", methods=["POST"])
def export_ebk():
    """导出 EBK 格式（通达信自选股板块文件，供通达信软件导入）。"""
    body = request.get_json(silent=True) or {}
    results = body.get("results") or []

    # 去重保序（一条结果对应一只股票，多形态/多级别时只保留一个代码）
    codes: List[str] = []
    seen = set()
    for r in results:
        code = r.get("code")
        if code and code not in seen:
            seen.add(code)
            codes.append(code)

    if not codes:
        return jsonify({"error": "无结果可导出"}), 400

    from .data.universe import to_ebk_code
    lines = [to_ebk_code(c) for c in codes]
    lines = [ln for ln in lines if ln]
    content = "\r\n".join(lines) + "\r\n"
    fname = f"A股筛选_{datetime.now().strftime('%Y%m%d_%H%M%S')}.EBK"
    mem = io.BytesIO()
    mem.write(content.encode("utf-8"))   # 纯数字内容，UTF-8/ASCII 兼容
    mem.seek(0)
    return send_file(
        mem, mimetype="application/octet-stream", as_attachment=True,
        download_name=fname,
    )


# ---------------------------------------------------------------------------
# 静态页面
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


def _round(x):
    return round(x, 2) if x is not None else None


def create_app():
    return app


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=False, threaded=True)
