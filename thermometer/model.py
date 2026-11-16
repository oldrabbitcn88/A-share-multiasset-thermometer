"""因子构造、滚动分位标准化与分层合成。"""
from __future__ import annotations

import numpy as np
import pandas as pd

# 因子名 -> (中文名, 方向)  方向 +1：越高越热；-1：越高越冷
FACTORS = {
    "erp":          ("股权风险溢价 ERP", -1),
    "dy_spread":    ("股债利差(股息率−10Y)", -1),
    "y10":          ("10Y国债收益率", -1),
    "y10_omo":      ("10Y−7天逆回购", -1),
    "credit":       ("信用利差", -1),
    "grade":        ("等级利差 AA+−AAA", -1),
    "cb_premium":   ("转股溢价率", +1),
    "fund_3y":      ("偏债混基3年年化", +1),
}

REGIMES = [(20, "极冷"), (40, "偏冷"), (60, "中性"), (80, "偏热"), (101, "过热")]


def regime(t: float) -> str:
    if pd.isna(t):
        return "—"
    return next(label for hi, label in REGIMES if t < hi)


def build_factors(raw: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """raw 列：y10, omo7d, mtn_aaa3, mtn_aap3, cdb3, gov3, pe, dy, fund_close, cb_premium（单位：%/倍/点）"""
    r = raw.sort_index().ffill(limit=5)  # 节假日错位最多前向填充 5 天
    col = lambda c: r[c] if c in r else pd.Series(np.nan, index=r.index)
    f = pd.DataFrame(index=r.index)
    f["erp"] = 100.0 / col("pe").where(col("pe") > 0) - col("y10")
    f["dy_spread"] = col("dy") - col("y10")
    f["y10"] = col("y10")
    f["y10_omo"] = col("y10") - col("omo7d")
    base = col("cdb3") if col("cdb3").notna().any() else col("gov3")
    f["credit"] = (col("mtn_aaa3") - base) * 100  # bp
    f["grade"] = (col("mtn_aap3") - col("mtn_aaa3")) * 100
    f["cb_premium"] = col("cb_premium")
    close = col("fund_close").dropna()
    yrs = cfg["model"]["fund_lookback_years"]
    if len(close):
        past = close.reindex(close.index - pd.DateOffset(years=yrs), method="ffill")
        past.index = close.index
        ok = close.index - pd.DateOffset(years=yrs) >= close.index[0]
        f["fund_3y"] = (((close / past) ** (1 / yrs) - 1) * 100).where(ok)
    else:
        f["fund_3y"] = np.nan
    return f


def rolling_pct(s: pd.Series, years: int, min_obs: int) -> pd.Series:
    """当前值在过去 N 年窗口内的分位（0–1），含当期。"""
    s = s.dropna()
    out = pd.Series(np.nan, index=s.index)
    vals, idx = s.to_numpy(), s.index
    start = 0
    for i, t in enumerate(idx):
        lo = t - pd.DateOffset(years=years)
        while idx[start] <= lo:
            start += 1
        win = vals[start:i + 1]
        if len(win) >= min_obs:
            out.iloc[i] = (np.sum(win < vals[i]) + 0.5 * np.sum(win == vals[i])) / len(win)
    return out


def _wavg(parts: list[tuple[pd.Series, float]]) -> pd.Series:
    """加权平均；某分项缺失时在剩余分项间重新归一化。"""
    num = sum(s.fillna(0) * w for s, w in parts)
    den = sum(s.notna() * w for s, w in parts)
    return (num / den.replace(0, np.nan))


def temperatures(raw: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    m, w = cfg["model"], cfg["weights"]
    f = build_factors(raw, cfg)
    t = pd.DataFrame(index=f.index)
    for k, (_, sign) in FACTORS.items():
        sm = f[k].rolling(m["smooth_days"], min_periods=1).mean().where(f[k].notna())
        p = rolling_pct(sm, m["window_years"], m["min_obs"]).reindex(f.index)
        t[f"T_{k}"] = (p if sign > 0 else 1 - p) * 100

    t["stock"] = _wavg([(t.T_erp, w["stock_erp"]), (t.T_dy_spread, w["stock_dy"])])
    rate = _wavg([(t.T_y10, w["rate_level"]), (t.T_y10_omo, w["rate_spread_omo"])])
    credit = _wavg([(t.T_credit, w["credit_spread"]), (t.T_grade, w["credit_grade"])])
    t["bond"] = _wavg([(rate, w["bond_rate"]), (credit, w["bond_credit"])])
    t["cb"] = _wavg([(t.T_cb_premium, w["cb_premium"]), (t.stock, w["cb_stock"])]).where(t.T_cb_premium.notna())
    t["mr"] = t.T_fund_3y
    t["composite"] = _wavg([(t.stock, w["comp_stock"]), (t.bond, w["comp_bond"]),
                            (t.cb, w["comp_cb"]), (t.mr, w["comp_mr"])])
    t["stock_minus_bond"] = t.stock - t.bond
    t["n_factors"] = t[[f"T_{k}" for k in FACTORS]].notna().sum(axis=1)
    t["regime"] = t.composite.map(regime)
    return pd.concat([f.add_prefix("F_"), t], axis=1)
