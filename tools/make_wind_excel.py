"""生成 Wind Excel 插件取数表：每个序列一个工作表，表名 = data/manual 下的序列名。

用法：python tools/make_wind_excel.py 输出路径.xlsx [起始日 [截止日]]
"""
import sys

from openpyxl import Workbook
from openpyxl.worksheet.formula import ArrayFormula
from openpyxl.styles import Font, PatternFill

out = sys.argv[1]
start = sys.argv[2] if len(sys.argv) > 2 else "2021-11-01"
end = sys.argv[3] if len(sys.argv) > 3 else "2026-11-16"

# 日期直接写进公式（不跨表引用），避免插件把引用单元格当成非法参数
S, E = f'"{start}"', f'"{end}"'
# 以传统数组公式（等同 Ctrl+Shift+Enter）写入一块区域：
# openpyxl 写出的普通公式在新版 Excel 中会被加上隐式交集 @，数组结果被截断成 #VALUE!
SPILL = "A3:B2200"
# 序列名, 中文说明, 公式, 备注
SERIES = [
    ("y10", "中国:国债到期收益率:10年（中国货币网）", f'=EDB("M0048271",{S},{E},"Fill=Previous")', "%"),
    ("omo7d", "中国:逆回购利率:7天", f'=EDB("M0041371",{S},{E},"Fill=Previous")', "%，仅操作日有值，程序会前向填充"),
    ("cdb3", "国开行政金债(AAA)到期收益率:3年（中国货币网）", f'=EDB("M1005175",{S},{E},"Fill=Previous")', "%，信用利差基准"),
    ("mtn_aaa3", "中短期票据到期收益率(AAA):3年（中证）", f'=EDB("M1002841",{S},{E},"Fill=Previous")', "%"),
    ("mtn_aap3", "中短期票据到期收益率(AA+):3年（中证）", f'=EDB("M1002877",{S},{E},"Fill=Previous")', "%"),
    ("pe", "万得全A 市盈率TTM", f'=WSD("881001.WI","pe_ttm",{S},{E},"")', "倍；API 缺 2024-11 至 2026-10，重点补"),
    ("dy", "沪深300 股息率（近12个月）", f'=WSD("000300.SH","dividendyield2",{S},{E},"")', "%；API 每年只取到前约100个交易日，需全量"),
    ("fund_close", "偏债混合型基金指数 收盘", f'=WSD("885003.WI","close",{S},{E},"")', "点；API 已有 2018-11 起完整数据，可不取"),
    ("cb_premium", "全市场可转债 转股溢价率 中位数", "", "%；见说明第 4 条，没有现成序列可留空"),
    ("cb_parity", "全市场可转债 转换价值(平价) 中位数", "", "元；同上"),
]

wb = Workbook()
ws = wb.active
ws.title = "说明"
bold = Font(bold=True)
rows = [
    ["固收+多资产温度计 · Wind Excel 回填取数表"],
    [],
    ["起始日", start],
    ["截止日", end],
    [],
    ["用法"],
    ["1. 在装有 Wind 插件的 Excel 里打开本文件，登录 Wind，等各工作表公式刷新出数据（可点 Wind 插件的「刷新」）。"],
    ["2. 每个工作表的 A3 是公式，结果需要有两列：日期、数值。若只出了数值没有日期，请在 Wind 函数向导里勾选「显示日期」后重新插入。"],
    ["3. 起止日期已写进各表公式（与本页 B3/B4 一致，改日期请让我重新生成）。刷新后保存为 .xlsx，把文件发回项目即可，我来导入仓库。"],
    ["4. cb_premium / cb_parity 是全市场存续转债的转股溢价率、转换价值的每日中位数。若 Wind 有现成的全市场序列（如 EDB 里搜「转股溢价率 中位数」），把公式或导出数据放到对应工作表 A3 起（日期、数值两列）；找不到可留空，程序沿用 API 已取到的 2022-04 起数据。"],
    ["5. 与 API 已有数据重叠的日期以 API 为准，Excel 数据只用于补缺。"],
    [],
    ["工作表", "内容", "单位/备注"],
] + [[n, d, note] for n, d, _, note in SERIES]
for r in rows:
    ws.append(r)
ws["A1"].font = Font(bold=True, size=14)
for c in ("A6", "A13", "B13", "C13"):
    ws[c].font = bold
ws["B3"].fill = ws["B4"].fill = PatternFill("solid", fgColor="FFF2CC")
ws.column_dimensions["A"].width = 14
ws.column_dimensions["B"].width = 48
ws.column_dimensions["C"].width = 50

for name, desc, formula, note in SERIES:
    s = wb.create_sheet(name)
    s["A1"] = f"{desc}（{note}）"
    s["A1"].font = bold
    s["A2"], s["B2"] = "日期", "数值"
    if formula:
        s["A3"] = ArrayFormula(SPILL, formula)
        s["D1"] = "公式文本（若 A3 仍报错，可复制到 A3 手工输入，或用 Wind 函数向导重插）："
        s["D2"] = formula
        s["D2"].data_type = "s"  # 以文本保存，便于复制
    s.column_dimensions["A"].width = 14
    s.column_dimensions["B"].width = 14
wb.save(out)
print("written", out)
