# -*- coding: utf-8 -*-
"""
个股所属概念（题材板块）映射 —— 东财概念板块成分股反向索引

用途：筛选报告里的「概念占比」。行业是单一归属，概念是多标签（一只股票常属 5~10 个概念），
所以报告里占比合计会超过 100%，属于正常现象。

数据源：
- 概念板块列表：push2 clist  `fs=m:90+t:3`（约 531 个板块）
- 每个板块的成分股：push2 clist `fs=b:BKxxxx`

成本：首次全量构建约 531 次请求（走 source._throttle 全局限流，约 15 秒），
结果落盘 data/concepts.json，7 天有效；期间再次生成报告 0 请求。

Author: HZQ
"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE_PATH = os.path.join(_BASE, "data", "concepts.json")
_CUSTOM_PATH = os.path.join(_BASE, "data", "themes.json")
_CACHE_TTL = 7 * 24 * 3600
_WORKERS = 8
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_EM = "https://push2.eastmoney.com/api/qt/clist/get"

_lock = threading.Lock()
_mem: Dict[str, List[str]] = {}      # {code: [概念名, ...]}
_loaded = False


def _get(url: str) -> dict:
    import urllib.request
    from .data.source import _throttle
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA, "Referer": "https://quote.eastmoney.com/"})
    _throttle()
    resp = urllib.request.urlopen(req, timeout=12)
    return json.loads(resp.read().decode("utf-8", "ignore"))


def _save_cache(em: Dict[str, List[str]], tdx: Dict[str, List[str]]):
    """两个源分开存：东财变动慢、通达信可单独刷新，合并结果由读取时计算。"""
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"_ts": time.time(), "em": em, "tdx": tdx}, f, ensure_ascii=False)
    except Exception:
        pass


def _load_sources() -> tuple:
    """读缓存 → (东财map, 通达信map)。兼容只存 map 的旧缓存。"""
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict) or time.time() - float(d.get("_ts", 0)) >= _CACHE_TTL:
            return {}, {}
        em = d.get("em") or d.get("map") or {}
        tdx = d.get("tdx") or {}
        clean = lambda m: {k: v for k, v in (m or {}).items() if isinstance(v, list)}
        return clean(em), clean(tdx)
    except Exception:
        return {}, {}


# ---------------------------------------------------------------------------
# 题材过滤：东财「概念板块」里混了大量非题材标签，必须剔除，否则报告里
# 会出现「机构重仓 100 条」「小盘股 80 条」这种没有信息量的条目。
# 按关键词黑名单排除：财报业绩 / 资金持仓 / 市值估值风格 / 交易技术属性 /
# 指数成分 / 股权治理。剩下的才是真题材（光伏、机器人、华为、低空经济…）。
# ---------------------------------------------------------------------------
_EXCLUDE_KEYWORDS = (
    # 财报与业绩
    '预增', '预减', '首亏', '扭亏', '亏损', '微利', '中报', '季报', '年报', '业绩',
    # 资金与持仓
    '重仓', '新进', '增仓', '减仓', '持股', '增持', '举牌', '调研', '金股', '大基金',
    '社保', '养老金', 'QFII', '外资', '北向', '证金', '险资', '信托', '私募', '基金', '机构',
    # 市值、估值与风格
    '大盘', '中盘', '小盘', '微盘', '百元股', '低价股', '高价股', '破净', '破发', '破增发',
    '红利', '超跌', '价值股', '成长股', '周期股', '趋势股', '反转股', '风格',
    '市净率', '市盈率', '权重股', '行业龙头', '超级品牌', '中字头', '题材股',
    # 交易与技术属性
    '融资融券', '沪股通', '深股通', '转债', '次新', 'ST股', '摘帽',
    '昨日', '最近多板', '连板', '涨停', '炸板', '触板', '首板', '打二板',
    '新高', '新低', '高换手', '高振幅', '做市',
    # 指数与成分股
    '指数', '成份', '成分股', '上证', '深证', '深成', '创业板综', '科创50', '中证', '央视',
    '标普', '标准普尔', '富时', '罗素', 'MSCI', '茅指数', '宁组合', 'HS300', 'GDR', 'AH股', 'AB股', 'B股',
    'H股', '通达信', '中特估',
    '热股', '人气榜', '排名',
    # 股权与治理
    '股权', '参股', '回购', '激励', '借壳', 'IPO受益',
)


def is_topic(name: str) -> bool:
    """判断一个东财板块名是否属于「真题材」（可解释的产业/政策/事件主题）。"""
    if not name:
        return False
    return not any(k in name for k in _EXCLUDE_KEYWORDS)


def _list_boards() -> Dict[str, str]:
    """概念板块 {BK代码: 名称}，翻页取全（每页上限 100）。"""
    out: Dict[str, str] = {}
    for pn in range(1, 10):
        url = (f"{_EM}?pn={pn}&pz=100&po=1&np=1&fltt=2&invt=2&fid=f3"
               f"&fs=m:90+t:3&fields=f12,f14")
        try:
            diff = (_get(url).get("data") or {}).get("diff") or []
        except Exception:
            break
        if not diff:
            break
        for x in diff:
            bk, name = x.get("f12"), x.get("f14")
            if bk and name:
                out[bk] = name
    return out


def _board_members(bk: str) -> List[str]:
    url = (f"{_EM}?pn=1&pz=1000&po=1&np=1&fltt=2&invt=2&fid=f3"
           f"&fs=b:{bk}&fields=f12")
    try:
        diff = (_get(url).get("data") or {}).get("diff") or []
    except Exception:
        return []
    return [str(x.get("f12")).zfill(6) for x in diff if x.get("f12")]


def _build_em() -> Dict[str, List[str]]:
    """东财概念板块：531 个板块逐个拉成分股（8 线程，约 15 秒）。"""
    boards = _list_boards()
    mapping: Dict[str, List[str]] = {}
    if not boards:
        return mapping

    def _one(item):
        bk, name = item
        return name, _board_members(bk)

    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        for name, codes in ex.map(_one, boards.items()):
            if not is_topic(name):
                continue          # 跳过财报/资金/风格/指数等非题材标签
            for c in codes:
                mapping.setdefault(c, []).append(name)
    return mapping


_TDX_BLOCK_FILE = "block_gn.dat"
_CHUNK = 0x7530                # 通达信板块文件单次下载块大小（30000 字节）


def _build_tdx() -> Dict[str, List[str]]:
    """通达信概念板块（block_gn.dat）。

    东财概念偏规范但更新慢、命名保守；通达信的题材更贴盘面（华为算力、智谱AI、
    DeepSeek、短剧游戏、PEEK材料、飞行汽车…），两者合并能明显补齐新题材。
    成本：757KB 分 26 块下载，约 1 秒；失败静默返回空，不影响东财部分。
    """
    try:
        from mootdx.quotes import Quotes
        from tdxpy.reader.block_reader import BlockReader, BlockReader_TYPE_GROUP
        from .data.source import _throttle, DEFAULT_TDX_SERVERS
    except Exception:
        return {}

    buf = None
    client = None
    for host, port in DEFAULT_TDX_SERVERS[:3]:
        try:
            _throttle()
            c = Quotes.factory(market="std", server=(host, port), auto_retry=False,
                               raise_exception=False, timeout=8)
            meta = c.client.get_block_info_meta(_TDX_BLOCK_FILE) or {}
            size = int(meta.get("size") or 0)
            if size <= 0:
                raise RuntimeError("empty meta")
            data = bytearray()
            for start in range(0, size, _CHUNK):
                _throttle()
                part = c.client.get_block_info(_TDX_BLOCK_FILE, start, _CHUNK)
                if not part:
                    break
                data.extend(part)
            if len(data) < size // 2:
                raise RuntimeError("incomplete")
            buf, client = data, c
            break
        except Exception:
            continue

    if buf is None:
        return {}
    try:
        rows = BlockReader().get_data(bytearray(buf), BlockReader_TYPE_GROUP)
    except Exception:
        return {}
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    mapping: Dict[str, List[str]] = {}
    for r in rows:
        name = str(r.get("blockname") or "").strip()
        if not name or not is_topic(name):
            continue
        for c in str(r.get("code_list") or "").split(","):
            c = c.strip()[-6:]
            if len(c) == 6 and c.isdigit():
                mapping.setdefault(c, []).append(name)
    return mapping


def _load_custom() -> tuple:
    """自定义题材 data/themes.json。

    返回 (直接名单 map, 别名映射 dict)：
    - 直接名单：{"太空算力": ["600118", "600879"]} —— 精确指定成分股
    - 别名映射：{"_alias": {"AI短剧": ["短剧游戏"]}} —— 把一个已有板块整体改名，
      用于数据源没有的市场新词（成分股跟着来源板块走，不编造）

    两个源都抓不到的概念只能手工补，这是唯一的补充通道。
    """
    try:
        with open(_CUSTOM_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return {}, {}
    if not isinstance(d, dict):
        return {}, {}

    direct: Dict[str, List[str]] = {}
    for name, codes in d.items():
        if not name or str(name).startswith("_") or not isinstance(codes, list):
            continue
        for c in codes:
            c = str(c).strip()[-6:]
            if len(c) == 6 and c.isdigit():
                direct.setdefault(c, []).append(str(name))

    alias: Dict[str, List[str]] = {}
    for new_name, srcs in (d.get("_alias") or {}).items():
        if not new_name or str(new_name).startswith("_"):
            continue
        if isinstance(srcs, str):
            srcs = [srcs]
        if isinstance(srcs, list) and srcs:
            alias[str(new_name)] = [str(x) for x in srcs]
    return direct, alias


def _apply_alias(mapping: Dict[str, List[str]], alias: Dict[str, List[str]]) -> None:
    """给命中来源板块的股票追加别名标签（原地修改）。"""
    if not alias:
        return
    for names in mapping.values():
        have = set(names)
        for new_name, srcs in alias.items():
            if new_name in have:
                continue
            if any(s in have for s in srcs):
                names.append(new_name)
                have.add(new_name)


def _merge(*sources) -> Dict[str, List[str]]:
    """多源合并：同一股票的概念按来源顺序拼接并去重。"""
    out: Dict[str, List[str]] = {}
    for src in sources:
        for code, names in (src or {}).items():
            cur = out.setdefault(code, [])
            seen = set(cur)
            for n in names:
                if n not in seen:
                    cur.append(n)
                    seen.add(n)
    return out


_src = {"em": {}, "tdx": {}}
_merged_custom_ts = [-1.0]      # 上次合并时 themes.json 的修改时间


def _custom_ts() -> float:
    try:
        return os.path.getmtime(_CUSTOM_PATH)
    except Exception:
        return 0.0


def get_concept_map(force: bool = False) -> Dict[str, List[str]]:
    """全市场 {股票代码: [概念名]}，合并 自定义 + 东财 + 通达信。

    首次构建：东财约 15 秒 + 通达信约 1 秒；之后走 7 天缓存。
    force=True 时两个源都重新抓（用于「重建索引」按钮）。
    themes.json 改动后会自动重新合并（无需重启服务）。
    """
    global _mem, _loaded
    ts = _custom_ts()
    with _lock:
        if not _loaded:
            if force:
                _src["em"], _src["tdx"] = {}, {}
                _mem = {}
            else:
                _src["em"], _src["tdx"] = _load_sources()
            _loaded = True
        if _mem and not force and ts == _merged_custom_ts[0]:
            return _mem

    rebuilt = False
    if force or not _src["em"]:
        _src["em"] = _build_em()
        rebuilt = True
    if force or not _src["tdx"]:
        _src["tdx"] = _build_tdx()
        rebuilt = True

    # 再过一遍黑名单：缓存里的旧标签也要按最新规则清理（避免"含H股/通达信88"这类）
    for k in ("em", "tdx"):
        _src[k] = {c: [n for n in ns if is_topic(n)] for c, ns in _src[k].items()}
        _src[k] = {c: ns for c, ns in _src[k].items() if ns}

    direct, alias = _load_custom()
    merged = _merge(direct, _src["em"], _src["tdx"])
    _apply_alias(merged, alias)

    with _lock:
        _mem = merged
        _merged_custom_ts[0] = ts
        if rebuilt:
            _save_cache(_src["em"], _src["tdx"])
    return _mem


def concepts_of(codes: List[str]) -> Dict[str, List[str]]:
    """取指定股票的概念（只返回查到的）。"""
    m = get_concept_map()
    out = {}
    for c in codes:
        cc = str(c).zfill(6)
        if m.get(cc):
            out[cc] = m[cc]
    return out


def cache_info() -> dict:
    """缓存状态（供前端提示首次构建耗时）。"""
    m = get_concept_map()
    tags = len({n for v in m.values() for n in v})
    info = {"stocks": len(m), "tags": tags,
            "from_em": len(_src["em"]), "from_tdx": len(_src["tdx"])}
    try:
        st = os.path.getmtime(_CACHE_PATH)
        info.update({"cached": True,
                     "built_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(st))})
    except Exception:
        info["cached"] = False
    return info
