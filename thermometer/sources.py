"""原始数据抓取。每个函数返回 {序列名: pd.Series(index=日期, 值)}。

数据可靠性分级（按 2026-11-16 实测）：
  已验证：EDB 时间序列（10Y 国债-中国货币网、7天逆回购），指数行情快照（含 市盈率(TTM)）
  未验证：指数基本面自然语言查询（股息率、转股溢价率历史）、指数 K 线（885003）
未验证的源若格式不符会记录错误并跳过；可在 data/manual/<序列名>.csv 手工补历史。
"""
from __future__ import annotations

import datetime as dt
import re

import pandas as pd

from . import wind

DATE_COL = re.compile(r"日期|交易日|时间|date", re.I)


def _to_date(v) -> pd.Timestamp | None:
    s = str(v)[:10].replace("-", "").replace("/", "")
    try:
        return pd.Timestamp(dt.datetime.strptime(s[:8], "%Y%m%d"))
    except ValueError:
        return None


def _series_from_table(body: dict, keyword: str, fallback_date: pd.Timestamp) -> pd.Series:
    cols, rows = wind.table(body)
    if not cols or not rows:
        raise wind.WindError("EMPTY", f"无表格数据（关键字 {keyword}）")
    vcol = next((i for i, c in enumerate(cols) if keyword in c), None)
    if vcol is None:
        raise wind.WindError("NO_FIELD", f"返回字段中没有『{keyword}』：{cols}")
    dcol = next((i for i, c in enumerate(cols) if DATE_COL.search(c)), None)
    out = {}
    for r in rows:
        d = _to_date(r[dcol]) if dcol is not None else fallback_date
        try:
            out[d or fallback_date] = float(r[vcol])
        except (TypeError, ValueError):
            continue
    return pd.Series(out, dtype=float).sort_index()


def edb(codes: dict[str, str], start: str, end: str) -> dict[str, pd.Series]:
    codes = {k: v for k, v in codes.items() if v}
    body = wind.call("economic_data", "query_economic_indicator_data",
                     {"question": ",".join(codes.values()), "beginDate": start, "endDate": end})
    metrics = body.get("data", body).get("metrics", [])
    by_code = {}
    for m in metrics:
        code = m.get("meta", {}).get("code")
        s = pd.Series([float(v) if v is not None else float("nan") for v in m.get("value", [])],
                      index=[_to_date(d) for d in m.get("date", [])], dtype=float)
        by_code[code] = s.dropna().sort_index()
    return {name: by_code[c] for name, c in codes.items() if c in by_code}


def index_pe_snapshot(code: str) -> pd.Series:
    body = wind.call("index_data", "get_index_price_indicators",
                     {"windcode": code, "indexes": "最新交易日,市盈率(TTM)"})
    return _series_from_table(body, "市盈率", pd.Timestamp.today().normalize())


def index_fundamental(question: str, keyword: str) -> pd.Series:
    body = wind.call("index_data", "get_index_fundamentals", {"question": question})
    return _series_from_table(body, keyword, pd.Timestamp.today().normalize())


def index_close(code: str, start: str, end: str) -> pd.Series:
    body = wind.call("index_data", "get_index_kline",
                     {"windcode": code, "begin_date": start, "end_date": end, "period": "1d"})
    return _series_from_table(body, "收盘", pd.Timestamp(end))


def fetch_all(cfg: dict, start: str, end: str, backfill: bool) -> tuple[dict[str, pd.Series], list[str]]:
    """抓取全部原始序列；单个源失败不影响其它源。遇额度/认证错误立即停止。"""
    w = cfg["wind"]
    out: dict[str, pd.Series] = {}
    errors: list[str] = []
    span = f"{start} 至 {end}" if backfill else end

    jobs = [
        ("EDB利率", lambda: edb({k: w[k] for k in ("y10", "omo7d", "mtn_aaa3", "mtn_aap3", "cdb3", "gov3")}, start, end)),
        ("PE", lambda: {"pe": index_fundamental(f"查询{w['equity_index']}指数{span}每日的市盈率TTM", "市盈率")}
                       if backfill else {"pe": index_pe_snapshot(w["equity_index"])}),
        ("股息率", lambda: {"dy": index_fundamental(f"查询{w['dividend_index']}指数{span}每日的股息率", "股息率")}),
        ("偏债混基", lambda: {"fund_close": index_close(w["fund_index"], start, end)}),
        ("转股溢价率", lambda: {"cb_premium": index_fundamental(
            f"查询{w['cb_index']}指数{span}每日的转股溢价率", "溢价率")}),
    ]
    for name, job in jobs:
        try:
            out.update(job())
        except wind.WindError as e:
            errors.append(f"{name}: {e}")
            if e.fatal:
                errors.append("账号额度不足或认证失败，停止后续请求")
                break
        except Exception as e:  # 网络超时等
            errors.append(f"{name}: {type(e).__name__}: {e}")
    return out, errors
