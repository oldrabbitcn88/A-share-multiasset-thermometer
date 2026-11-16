import tomllib
from pathlib import Path

import numpy as np
import pandas as pd

from thermometer import model

CFG = tomllib.loads((Path(__file__).parent.parent / "config.toml").read_text(encoding="utf-8"))


def synthetic_raw(n_years=6, seed=0):
    idx = pd.bdate_range("2019-01-01", periods=250 * n_years)
    rng = np.random.default_rng(seed)
    walk = lambda s, sd: s + np.cumsum(rng.normal(0, sd, len(idx)))
    return pd.DataFrame({
        "y10": walk(3.2, 0.01), "omo7d": 2.0, "mtn_aaa3": walk(3.6, 0.01), "gov3": walk(2.8, 0.01),
        "mtn_aap3": walk(3.9, 0.01), "pe": np.abs(walk(15, 0.1)) + 5, "dy": walk(2.5, 0.01),
        "fund_close": np.exp(np.cumsum(rng.normal(0.0002, 0.002, len(idx)))) * 1000,
        "cb_premium": walk(25, 0.3),
    }, index=idx)


def test_range_and_direction():
    raw = synthetic_raw()
    t = model.temperatures(raw, CFG)
    last = t.dropna(subset=["composite"])
    assert len(last) > 100
    for c in ["composite", "stock", "bond", "cb", "mr"]:
        assert last[c].dropna().between(0, 100).all() and last[c].notna().any(), c
    # 收益率创新低 → 利率温度应接近 100（债券贵）
    raw2 = raw.copy()
    raw2.iloc[-30:, raw2.columns.get_loc("y10")] = raw.y10.min() - 0.5
    t2 = model.temperatures(raw2, CFG)
    assert t2.T_y10.iloc[-1] > 95


def test_missing_factor_renormalizes():
    raw = synthetic_raw().drop(columns=["cb_premium", "mtn_aap3"])
    t = model.temperatures(raw, CFG)
    row = t.dropna(subset=["composite"]).iloc[-1]
    assert pd.isna(row.cb) and not pd.isna(row.composite)
    assert row.n_factors == 6


def test_rolling_pct_bounds():
    s = pd.Series(np.arange(600, dtype=float), index=pd.bdate_range("2020-01-01", periods=600))
    p = model.rolling_pct(s, 1, 100).dropna()
    assert p.iloc[-1] > 0.99
