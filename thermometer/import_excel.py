"""把 Wind Excel 取数表（tools/make_wind_excel.py 生成、刷新并保存后）导入 data/manual/<序列名>.csv。

用法：python -m thermometer.import_excel 取数表.xlsx
只读取单元格缓存值：在 Wind Excel 里刷新后保存即可，不需要本机有 Wind。
每个工作表中，第一列能解析为日期、后续列中第一个数值的行即为一条数据。
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

MANUAL = Path(__file__).resolve().parent.parent / "data" / "manual"
SKIP = {"说明"}


def _date(v):
    if isinstance(v, dt.datetime):
        return pd.Timestamp(v.date())
    if isinstance(v, dt.date):
        return pd.Timestamp(v)
    if isinstance(v, (int, float)) and 20000 < v < 80000:  # Excel 日期序列号
        return pd.Timestamp("1899-12-30") + pd.Timedelta(days=int(v))
    if isinstance(v, str):
        try:
            return pd.Timestamp(v.strip().replace("/", "-"))
        except ValueError:
            return None
    return None


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def read_sheet(ws) -> pd.Series:
    out = {}
    for row in ws.iter_rows(values_only=True):
        if not row:
            continue
        d = _date(row[0])
        if d is None:
            continue
        v = next((x for x in map(_num, row[1:]) if x is not None), None)
        if v is not None:
            out[d] = v
    return pd.Series(out, dtype=float).sort_index()


def main(path: str) -> int:
    wb = load_workbook(path, data_only=True, read_only=True)
    MANUAL.mkdir(parents=True, exist_ok=True)
    empty = []
    for ws in wb.worksheets:
        if ws.title in SKIP:
            continue
        s = read_sheet(ws)
        if s.empty:
            empty.append(ws.title)
            continue
        s.rename_axis("date").rename("value").to_csv(MANUAL / f"{ws.title}.csv", date_format="%Y-%m-%d")
        print(f"{ws.title}: {len(s)} 条，{s.index.min().date()} 至 {s.index.max().date()}")
    if empty:
        print("无数据的工作表（未刷新、留空或公式报错）：" + "、".join(empty))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
