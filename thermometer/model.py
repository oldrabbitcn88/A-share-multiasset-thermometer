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


def parity_adjusted_premium(prem: pd.Series, parity: pd.Series) -> pd.Series:
    """把全市场溢价率中位数修正到"平价=100"口径。

    股市下跌时转债平价下移、溢价率被动抬升，原始中位数会误显示"贵"。
    用历史样本回归 溢价率中位数 ~ a + b·ln(平价中位数)，再按 b 把当日值平移到 ln(100)。
    无平价数据或样本不足时返回原值。
    """
    ok = prem.notna() & parity.notna() & (parity > 0)
    if ok.sum() < 60:
        return prem
    x, y = np.log(parity[ok]), prem[ok]
    b = np.polyfit(x, y, 1)[0]
    return (prem - b * (np.log(parity) - np.log(100))).where(ok, prem)


def build_factors(raw: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """raw 列：y10, omo7d, mtn_aaa3, mtn_aap3, cdb3, gov3, pe, dy, fund_close, cb_premium（单位：%/倍/点）"""
    r = raw.sort_index().ffill(limit=5)  # 节假日错位最多前向填充 5 天
    if "omo7d" in raw:  # 政策利率为阶梯序列，只在操作日有记录，无限期沿用
        r["omo7d"] = raw["omo7d"].sort_index().ffill()
    if "y10" in raw:  # 以 10Y 国债有值的日期为交易日历，剔除接口在非交易日/盘前返回的占位行
        r = r[raw["y10"].sort_index().notna()]
    col = lambda c: r[c] if c in r else pd.Series(np.nan, index=r.index)
    f = pd.DataFrame(index=r.index)
    f["erp"] = 100.0 / col("pe").where(col("pe") > 0) - col("y10")
    f["dy_spread"] = col("dy") - col("y10")
    f["y10"] = col("y10")
    f["y10_omo"] = col("y10") - col("omo7d")
    base = col("cdb3") if col("cdb3").notna().any() else col("gov3")
    f["credit"] = (col("mtn_aaa3") - base) * 100  # bp
    f["grade"] = (col("mtn_aap3") - col("mtn_aaa3")) * 100
    f["cb_premium"] = parity_adjusted_premium(col("cb_premium"), col("cb_parity"))
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
