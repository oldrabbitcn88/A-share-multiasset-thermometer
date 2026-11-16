"""用法：
  python -m thermometer daily               # 每日增量：抓近 20 天数据、重算温度、记录当日
  python -m thermometer backfill 2021-11-01 # 一次性回填历史
  python -m thermometer rebuild             # 不联网，仅用现有数据重算
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tomllib
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from . import model, report, sources

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw.csv"
TEMP = DATA / "temperature.csv"
LOG = DATA / "daily_log.csv"
MANUAL = DATA / "manual"


def load_cfg() -> dict:
    return tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))


def load_raw() -> pd.DataFrame:
    raw = pd.read_csv(RAW, index_col=0, parse_dates=True) if RAW.exists() else pd.DataFrame()
    # 手工历史（如从 Wind 终端导出）：data/manual/<序列名>.csv，两列 date,value；Wind 数据优先
    for f in sorted(MANUAL.glob("*.csv")):
        m = pd.read_csv(f, parse_dates=[0])
        s = pd.Series(m.iloc[:, 1].astype(float).values, index=pd.DatetimeIndex(m.iloc[:, 0]))
        cur = raw[f.stem] if f.stem in raw else pd.Series(dtype=float)
        raw = raw.reindex(raw.index.union(s.index))
        raw[f.stem] = cur.reindex(raw.index).combine_first(s.reindex(raw.index))
    return raw.sort_index()


def upsert(raw: pd.DataFrame, new: dict[str, pd.Series]) -> pd.DataFrame:
    for name, s in new.items():
        s = s.dropna()
        if s.empty:
            continue
        raw = raw.reindex(raw.index.union(s.index))
        raw.loc[s.index, name] = s.values
    return raw.sort_index()


def summary(lines: list[str]) -> None:
    text = "\n".join(lines)
    print(text)
    if p := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "daily"
    cfg = load_cfg()
    today = dt.datetime.now(ZoneInfo("Asia/Shanghai")).date()
    raw = load_raw()
    errors: list[str] = []
    failed_hard = False

    if cmd in ("daily", "backfill"):
        start = argv[1] if cmd == "backfill" else str(today - dt.timedelta(days=20))
        new, errors = sources.fetch_all(cfg, start, str(today), backfill=(cmd == "backfill"))
        # 额度/认证错误，或一个源都没取到 → 让 Action 标红提醒
        failed_hard = not new or any("停止后续请求" in e for e in errors)
        raw = upsert(raw, new)
        DATA.mkdir(exist_ok=True)
        raw.round(6).to_csv(RAW, date_format="%Y-%m-%d")

    if raw.empty:
        summary(["## 温度计", "没有任何原始数据。", *[f"- ⚠️ {e}" for e in errors]])
        return 1

    t = model.temperatures(raw, cfg)
    t.round(4).to_csv(TEMP, date_format="%Y-%m-%d")
    latest = t.dropna(subset=["composite"]).tail(1)
    if latest.empty:
        summary(["## 温度计", "历史样本不足，尚无可计算的温度。", *[f"- ⚠️ {e}" for e in errors]])
        return 1 if failed_hard else 0

    row = latest.iloc[0]
    data_date = latest.index[0].strftime("%Y-%m-%d")
    # 追加式日志：同一数据日期只记一次，用于保留"当日所见"的温度（后续历史修订不改写）
    log = pd.read_csv(LOG) if LOG.exists() else pd.DataFrame()
    if cmd == "daily" and (log.empty or data_date not in set(log["data_date"])):
        rec = {"run_date": str(today), "data_date": data_date,
               **{k: round(float(row[k]), 2) for k in ("composite", "stock", "bond", "cb", "mr", "stock_minus_bond")},
               "regime": row["regime"], "n_factors": int(row["n_factors"]), "errors": " | ".join(errors)}
        pd.concat([log, pd.DataFrame([rec])]).to_csv(LOG, index=False)

    report.write(t, ROOT / "docs", errors)
    summary([f"## 温度计 {data_date}",
             f"综合温度 **{row.composite:.1f}**（{row.regime}），有效因子 {int(row.n_factors)}/{len(model.FACTORS)}",
             *[f"- ⚠️ {e}" for e in errors]])
    return 1 if failed_hard else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
