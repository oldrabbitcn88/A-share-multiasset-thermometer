"""生成 docs/latest.md 与 docs/temperature.png。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .model import FACTORS, regime


def _fmt(v, nd=1):
    return "—" if pd.isna(v) else f"{v:.{nd}f}"


def write(t: pd.DataFrame, out: Path, errors: list[str]) -> None:
    out.mkdir(exist_ok=True)
    valid = t.dropna(subset=["composite"])
    row, d = valid.iloc[-1], valid.index[-1]
    prev = valid.iloc[-21] if len(valid) > 21 else None

    lines = [
        f"# 固收+ 多资产温度计 · {d:%Y-%m-%d}",
        "",
        f"**综合温度：{_fmt(row.composite)}（{row.regime}）**"
        + (f"　20个交易日前：{_fmt(prev.composite)}" if prev is not None else ""),
        "",
        "温度 0–100，越高越贵 / 越拥挤 / 未来预期回报越低。",
        "",
        "| 资产 | 温度 | 状态 |",
        "|---|---|---|",
    ]
    for key, name in [("stock", "股票"), ("bond", "纯债"), ("cb", "转债"), ("mr", "均值回归(偏债混基)")]:
        lines.append(f"| {name} | {_fmt(row[key])} | {regime(row[key])} |")
    lines += [f"| 股债相对温度（股−债） | {_fmt(row.stock_minus_bond)} | {'股票相对便宜' if row.stock_minus_bond < -30 else '债券相对便宜' if row.stock_minus_bond > 30 else '均衡'} |",
              "", "## 因子明细", "", "| 因子 | 原始值 | 温度 |", "|---|---|---|"]
    for k, (name, _) in FACTORS.items():
        lines.append(f"| {name} | {_fmt(row.get('F_' + k), 2)} | {_fmt(row.get('T_' + k))} |")
    if errors:
        lines += ["", "## 本次取数告警", "", *[f"- {e}" for e in errors]]
    lines += ["", "![温度走势](temperature.png)", "", "数据来源于万得 Wind 金融数据服务。", ""]
    (out / "latest.md").write_text("\n".join(lines), encoding="utf-8")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    fig, ax = plt.subplots(figsize=(10, 4), dpi=120)
    for y0, y1, c in [(0, 20, "#2b6cb0"), (20, 40, "#90cdf4"), (60, 80, "#fbb6a0"), (80, 100, "#c53030")]:
        ax.axhspan(y0, y1, color=c, alpha=0.08, lw=0)
    for key, label, lw in [("composite", "Composite", 2.2), ("stock", "Equity", 1), ("bond", "Bond", 1),
                           ("cb", "Convertible", 1)]:
        ax.plot(valid.index, valid[key], label=label, lw=lw)
    ax.set_ylim(0, 100)
    ax.set_title(f"Fixed Income Plus Thermometer (latest {d:%Y-%m-%d}: {row.composite:.1f})")
    ax.legend(loc="upper left", ncol=4, frameon=False)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "temperature.png")
    plt.close(fig)
