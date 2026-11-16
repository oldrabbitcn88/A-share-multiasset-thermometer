"""原始数据抓取。每个函数返回 pd.Series(index=日期, 值)。

数据源（2026-11-16 实测可用，见 README「数据源」一节）：
  EDB：10Y国债(中国货币网)、7天逆回购、国开3Y(中国货币网)、中短票AAA/AA+ 3Y(中证)
  index_data.get_index_fundamentals：万得全A PE(TTM)、沪深300 股息率
  index_data.get_index_kline：885003.WI 偏债混合型基金指数收盘
  analytics_data.get_financial_data：全市场可转债转股溢价率中位数、转换价值中位数
"""
from __future__ import annotations

import datetime as dt
import os
import re

import pandas as pd

from . import wind

DATE_NAME = re.compile(r"日期|交易日|时间|TIME|date", re.I)


def _to_date(v) -> pd.Timestamp | None:
    s = str(v)[:10].replace("-", "").replace("/", "")
    try:
        return pd.Timestamp(dt.datetime.strptime(s[:8], "%Y%m%d"))
    except ValueError:
        return None


def _series(body: dict, keywords: tuple[str, ...], fallback_date: pd.Timestamp) -> pd.Series:
    """在返回的各张表里找名字含关键字的数值列，配上日期列。"""
    for cols, rows in wind.tables(body):
        names = [c.get("name", "") for c in cols]
        is_date = [c.get("type") == "date" or bool(DATE_NAME.search(n)) for c, n in zip(cols, names)]
        vcol = next((i for i, n in enumerate(names) if not is_date[i] and any(k in n for k in keywords)), None)
        if vcol is None:
            continue
        dcol = next((i for i, d in enumerate(is_date) if d), None)
        out = {}
        for r in rows:
            d = (_to_date(r[dcol]) if dcol is not None else None) or fallback_date
            try:
                out[d] = float(r[vcol])
            except (TypeError, ValueError):
                continue
        return pd.Series(out, dtype=float).sort_index()
    if "text" in body:
        raise wind.WindError("NO_DATA", body["text"][:100])
    raise wind.WindError("NO_FIELD", f"返回中没有含 {keywords} 的数值列")


def _chunks(start: str, end: str, months: int = 12):
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    while s <= e:
        nxt = min(s + pd.DateOffset(months=months) - pd.Timedelta(days=1), e)
        yield s.strftime("%Y-%m-%d"), nxt.strftime("%Y-%m-%d")
        s = nxt + pd.Timedelta(days=1)


def _span(a: str, b: str) -> str:
    return f"{a}至{b}"


def edb(codes: dict[str, str], start: str, end: str) -> dict[str, pd.Series]:
    codes = {k: v for k, v in codes.items() if v}
    body = wind.call("economic_data", "query_economic_indicator_data",
                     {"question": ",".join(codes.values()), "beginDate": start, "endDate": end})
    by_code = {}
    for m in body.get("data", body).get("metrics", []):
        s = pd.Series([float(v) if v is not None else float("nan") for v in m.get("value", [])],
                      index=[_to_date(d) for d in m.get("date", [])], dtype=float)
        by_code[m.get("meta", {}).get("code")] = s.dropna().sort_index()
    return {name: by_code[c] for name, c in codes.items() if c in by_code}


def index_fundamental(code: str, field: str, keyword: str, start: str, end: str) -> pd.Series:
    body = wind.call("index_data", "get_index_fundamentals",
                     {"question": f"查询{code}指数{_span(start, end)}每日的{field}"})
    return _series(body, (keyword,), pd.Timestamp(end))


def index_close(code: str, start: str, end: str) -> pd.Series:
    body = wind.call("index_data", "get_index_kline",
                     {"windcode": code, "begin_date": start, "end_date": end, "period": "1d"})
    return _series(body, ("MATCH", "收盘", "CLOSE"), pd.Timestamp(end))


def cb_medians(start: str, end: str) -> dict[str, pd.Series]:
    body = wind.call("analytics_data", "get_financial_data", {"question":
        f"计算中国沪深市场全部上市可转债{_span(start, end)}每日转股溢价率的中位数和转换价值的中位数"})
    out = {"cb_premium": _series(body, ("转股溢价率",), pd.Timestamp(end))}
    try:
        out["cb_parity"] = _series(body, ("转换价值",), pd.Timestamp(end))
    except wind.WindError:
        pass  # 无平价时模型退回使用原始溢价率中位数
    return out


def fetch_all(cfg: dict, start: str, end: str, backfill: bool) -> tuple[dict[str, pd.Series], list[str]]:
    """抓取全部原始序列；单个源失败不影响其它源。遇额度/认证错误立即停止。
    回填分段请求，避免单次返回被截断。"""
    w = cfg["wind"]
    fund_start = str((pd.Timestamp(start) - pd.DateOffset(years=cfg["model"]["fund_lookback_years"])).date()) \
        if backfill else start
    jobs = [
        # (名称, 起始日, 回填分段月数, 取数函数)。自然语言/分析接口单次约返回 100 行，按 4 个月分段
        ("EDB利率", start, 12, lambda a, b: edb({k: w[k] for k in ("y10", "omo7d", "mtn_aaa3", "mtn_aap3", "cdb3", "gov3")}, a, b)),
        ("PE", start, 4, lambda a, b: {"pe": index_fundamental(w["equity_index"], "市盈率TTM", "市盈率", a, b)}),
        ("股息率", start, 4, lambda a, b: {"dy": index_fundamental(w["dividend_index"], "股息率", "股息率", a, b)}),
        ("偏债混基", fund_start, 12, lambda a, b: {"fund_close": index_close(w["fund_index"], a, b)}),
        ("转债溢价率", start, 4, cb_medians),
    ]
    if only := os.environ.get("THERMO_ONLY"):  # 只重抓部分源，如 THERMO_ONLY=PE,股息率
        jobs = [j for j in jobs if j[0] in only.split(",")]
    acc: dict[str, list[pd.Series]] = {}
    errors: list[str] = []
    for name, s0, months, job in jobs:
        for a, b in (_chunks(s0, end, months) if backfill else [(s0, end)]):
            try:
                for k, s in job(a, b).items():
                    acc.setdefault(k, []).append(s)
            except wind.WindError as e:
                errors.append(f"{name} {a}~{b}: {e}")
                if e.fatal:
                    errors.append("账号额度不足或认证失败，停止后续请求")
                    return _merge(acc), errors
            except Exception as e:  # 网络超时等
                errors.append(f"{name} {a}~{b}: {type(e).__name__}: {e}")
    return _merge(acc), errors


def _merge(acc: dict[str, list[pd.Series]]) -> dict[str, pd.Series]:
    out = {}
    for k, parts in acc.items():
        s = pd.concat(parts).dropna()
        out[k] = s[~s.index.duplicated(keep="last")].sort_index()
    return out
