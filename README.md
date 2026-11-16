# 固收+ 多资产温度计

每个交易日收盘后，于北京时间次日 00:05（万得每日赠送积分约 00:40 过期前），GitHub Actions 自动从万得 Alice Market 取数，计算六因子温度，并把结果提交回仓库。

- 最新读数：[`docs/latest.md`](docs/latest.md)
- 历史温度（每次全量重算）：`data/temperature.csv`
- 当日记录（只追加，保留当天所见，不受后续修订影响）：`data/daily_log.csv`
- 原始数据：`data/raw.csv`

## 因子与合成

| 资产 | 因子 | 方向 |
|---|---|---|
| 股票 | ERP = 1/PE_TTM − 10Y国债；股债利差 = 股息率 − 10Y国债 | 越高越冷 |
| 纯债 | 10Y国债水平、10Y − 7天逆回购；信用利差 AAA3Y − 基准3Y、等级利差 AA+ − AAA | 越高越冷 |
| 转债 | 转股溢价率（70%）+ 股票温度（30%） | 越高越热 |
| 均值回归 | 偏债混合型基金指数 885003 滚动3年年化 | 越高越热 |

- **标准化**：先取 20 日均值，再算 5 年滚动分位，换算成 0–100。
- **综合温度** = 股票 30% + 纯债 35% + 转债 15% + 均值回归 20%。缺失的分项会自动重新分配权重。
- 窗口和权重都在 `config.toml` 里调整。

## 部署步骤

1. 把本目录推送到一个 GitHub 仓库（建议私有）。
2. 在仓库的 Settings → Secrets and variables → Actions 中新建 secret，名称为 `WIND_API_KEY`，值为你的 Alice Market API Key。
3. 在 Actions 页面手动运行一次 **每日温度计**，mode 填 `backfill`，start 填起始日期（如 `2021-11-01`），完成一次性历史回填。
4. 之后北京时间周二至周六 00:05 自动运行 `daily`（00:20 补跑兜底，已成功则跳过）。节假日没有新数据，不会产生提交。

本地运行：

```bash
pip install -r requirements.txt
npx --yes skills add https://github.com/Wind-Alice/AliceMarket.git --skill wind-mcp-skill -g -y
WIND_API_KEY=... python -m thermometer daily
python -m pytest tests
```

## 手工补充历史

当 Wind 历史受权限或长度限制时，可以从 Wind 终端导出数据，放到 `data/manual/<序列名>.csv`。文件两列：`date,value`。与 Wind 返回的数据重叠时，以 Wind 为准。

可用的序列名：`y10 omo7d mtn_aaa3 mtn_aap3 cdb3 gov3 pe dy fund_close cb_premium`

## 已知限制

- 当前账号没有中债收益率曲线的权限，10Y 国债改用中国货币网口径（M0048271）。
- 单次 EDB 查询约返回近 5 年数据，所以分位窗口默认 5 年。
- 股息率、转股溢价率、885003 K 线使用的接口尚未实测返回格式；若解析失败，会在告警中列出并跳过该因子。
- GitHub 定时任务在高峰期可能延迟。

数据来源于万得 Wind 金融数据服务。
