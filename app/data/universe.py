# -*- coding: utf-8 -*-
"""
股票池管理 —— 全市场列表获取 / 过滤 / 本地缓存

A 股市场前缀规则（需结合市场维度，因为上证 000xxx 是指数而非股票）：
- 深市（mootdx market=0）：A 股 = 000/001/002/003/300/301
- 沪市（mootdx market=1）：A 股 = 600/601/603/605/688/689（000xxx 为指数，需剔除）
- 北交所（可选）：43/83/87/92 开头

Author: HZQ
"""
from __future__ import annotations

import csv
import os
import re
from typing import List, Optional

import config

# 项目根目录（universe.py 位于 app/data/ 下，上溯三级）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# 深市 A 股前缀
_SZ_A_PREFIX = ("000", "001", "002", "003", "300", "301")
# 沪市 A 股前缀
_SH_A_PREFIX = ("600", "601", "603", "605", "688", "689")
# 北交所前缀（可选启用）
_BJ_A_PREFIX = ("43", "83", "87", "88", "92")


def _clean_name(name) -> str:
    """清洗名称中的空字节 / 空格。"""
    if not name:
        return ""
    return str(name).replace("\x00", "").strip()


def _is_sz_a(code: str) -> bool:
    return code.startswith(_SZ_A_PREFIX)


def _is_sh_a(code: str) -> bool:
    return code.startswith(_SH_A_PREFIX)


def _is_bj_a(code: str) -> bool:
    return code.startswith(_BJ_A_PREFIX)


def parse_codes(text: str):
    """从文本中解析股票代码（每行一个，支持逗号/分号/空格/制表符分隔）。

    支持两种格式：
    1. 普通 CSV/TXT：6 位真实代码，如 `002159`、`600097`
    2. 通达信 EBK：市场标识(1位) + 代码(6位)，如 `0002159`→`002159`、
       `1600097`→`600097`、`2920808`→`920808`
       市场标识：0=深证 1=上证 2=北证（首位剥离后按 6 位代码重新判定市场）

    校验规则：6 位数字、属于 A 股市场前缀（上证/深证/北证/科创/创业）。
    返回 (valid_codes, invalid_entries)，valid 已去重保序。
    """
    tokens = re.split(r"[\s,;，；、\t]+", text or "")
    valid: List[str] = []
    invalid: List[str] = []
    seen = set()
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        digits = re.sub(r"\D", "", t)          # 剔除 .SH/.SZ 等后缀及非数字
        # EBK 格式：7 位且首位为市场标识(0/1/2)，剥离首位取后 6 位代码
        if len(digits) == 7 and digits[0] in "012":
            digits = digits[1:]
        code = digits[:6] if len(digits) >= 6 else digits
        if re.fullmatch(r"\d{6}", code) and config.classify_market(code) != "other":
            if code not in seen:
                seen.add(code)
                valid.append(code)
        else:
            invalid.append(t)
    return valid, invalid


def to_ebk_code(code: str) -> Optional[str]:
    """把 6 位 A 股代码转成通达信 EBK 格式（市场标识 + 6 位代码）。

    市场标识：0=深证(含创业板) 1=上证(含科创板) 2=北证。
    无法归类（other）时返回 None。
    """
    c = str(code).zfill(6)
    m = config.classify_market(c)
    if m in ("sz", "cyb"):
        return "0" + c
    if m in ("sh", "kcb"):
        return "1" + c
    if m == "bj":
        return "2" + c
    return None


class Universe:
    """A 股股票池。"""

    def __init__(self, include_bj: bool = False):
        self.include_bj = include_bj
        self._codes: List[str] = []
        self._names: dict = {}

    # ------------------------------------------------------------------
    def from_mootdx(self) -> "Universe":
        """从通达信拉取全市场 A 股列表（沪深，可选北交所）。"""
        from mootdx.quotes import Quotes
        client = Quotes.factory(market="std")
        codes: List[str] = []
        names: dict = {}

        # 深市 market=0
        try:
            df_sz = client.stocks(market=0)
            for _, row in df_sz.iterrows():
                code = str(row.get("code", "")).zfill(6)
                if _is_sz_a(code):
                    codes.append(code)
                    names[code] = _clean_name(row.get("name"))
        except Exception:
            pass

        # 沪市 market=1
        try:
            df_sh = client.stocks(market=1)
            for _, row in df_sh.iterrows():
                code = str(row.get("code", "")).zfill(6)
                if _is_sh_a(code):
                    codes.append(code)
                    names[code] = _clean_name(row.get("name"))
        except Exception:
            pass

        # 北交所（可选）
        if self.include_bj:
            try:
                df_bj = client.stocks(market=2)
                for _, row in df_bj.iterrows():
                    code = str(row.get("code", "")).zfill(6)
                    if _is_bj_a(code):
                        codes.append(code)
                        names[code] = _clean_name(row.get("name"))
            except Exception:
                pass

        self._codes = sorted(set(codes))
        self._names = names
        return self

    def from_list(self, codes: List[str], names: Optional[dict] = None) -> "Universe":
        self._codes = [str(c).zfill(6) for c in codes]
        self._names = names or {}
        return self

    # ------------------------------------------------------------------
    @property
    def codes(self) -> List[str]:
        return self._codes

    def name_of(self, code: str) -> str:
        return self._names.get(code, "")

    def __len__(self) -> int:
        return len(self._codes)

    # ------------------------------------------------------------------
    def save_csv(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["code", "name"])
            for c in self._codes:
                w.writerow([c, self.name_of(c)])

    def load_csv(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        codes, names = [], {}
        with open(path, "r", encoding="utf-8-sig") as f:
            for row in csv.reader(f):
                if not row or row[0] == "code":
                    continue
                code = str(row[0]).zfill(6)
                codes.append(code)
                names[code] = row[1] if len(row) > 1 else ""
        self._codes = sorted(set(codes))
        self._names = names
        return True


def load_universe() -> Universe:
    """统一加载本地股票池（全市场 A 股）。

    改造后不再区分「精选池 / 全市场」，所有筛选统一使用本地数据源：
    1. 本地已有 universe.csv 缓存 → 直接读
    2. 本地缺失 → 从通达信拉全市场列表并落盘缓存（仅首次）
    """
    cache_path = os.path.join(BASE_DIR, config.UNIVERSE_CACHE)

    u = Universe()
    if u.load_csv(cache_path) and len(u) > 100:
        return u
    u.from_mootdx()
    if len(u) > 0:
        u.save_csv(cache_path)
    return u
