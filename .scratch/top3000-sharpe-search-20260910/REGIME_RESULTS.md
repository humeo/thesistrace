# 固定窗口中的个股状态切换结果

QS4全部9个个股规则/时间段与3个静态一年期对照已完成。均为TOP3000、100只、每20日调仓、1000万元本金，止于2026-09-09；这些是单个股票评分切换，不是组合转现金。没有一项Sharpe>1.2。

|策略与区间|起点|净累计收益|最大回撤|Sharpe|
|---|---|---:|---:|---:|
|[QS4 1y cfoa H100 R20](https://thesistrace.com/research-runs/run_3bf8a542b6cb4b9eb512)|2025-09-10|-6.92%|18.66%|-0.334|
|[QS4 1y lowamount20 H100 R20](https://thesistrace.com/research-runs/run_6c31d43b1d674ad8bce8)|2025-09-10|6.92%|20.71%|0.448|
|[QS4 1y lowvol20 H100 R20](https://thesistrace.com/research-runs/run_38add7ac94b24695ac79)|2025-09-10|-3.37%|15.81%|-0.269|
|[QS4 1y switch_trend_amount_lowvol H100 R20](https://thesistrace.com/research-runs/run_f11d10a6b3ca413883f5)|2025-09-10|0.81%|15.83%|0.130|
|[QS4 1y switch_trend_mom_lowvol H100 R20](https://thesistrace.com/research-runs/run_7df1db67efbf46ccbd60)|2025-09-10|-10.68%|21.85%|-0.405|
|[QS4 1y switch_vol_lowvol_moderate H100 R20](https://thesistrace.com/research-runs/run_c299d60f2e5f454bbfe3)|2025-09-10|-1.08%|24.75%|0.043|
|[QS4 3y switch_trend_amount_lowvol H100 R20](https://thesistrace.com/research-runs/run_5af32e2d6ea94dbc9144)|2023-09-11|15.41%|19.97%|0.347|
|[QS4 3y switch_trend_mom_lowvol H100 R20](https://thesistrace.com/research-runs/run_e96ea05294274d598dae)|2023-09-11|-2.72%|28.08%|0.107|
|[QS4 3y switch_vol_lowvol_moderate H100 R20](https://thesistrace.com/research-runs/run_7a4f01927a964fb583e4)|2023-09-11|5.69%|34.07%|0.206|
|[QS4 ytd switch_trend_amount_lowvol H100 R20](https://thesistrace.com/research-runs/run_95d75a49a8af4621aa66)|2026-01-05|0.06%|12.30%|0.073|
|[QS4 ytd switch_trend_mom_lowvol H100 R20](https://thesistrace.com/research-runs/run_dfdabe2dd5964f47b841)|2026-01-05|-4.03%|19.02%|-0.119|
|[QS4 ytd switch_vol_lowvol_moderate H100 R20](https://thesistrace.com/research-runs/run_25e41e948fd544c0b99d)|2026-01-05|-8.65%|23.45%|-0.614|

后续现金/股票切换已在独立10万元模型中回放，见[CAPITAL_REPLAY.md](CAPITAL_REPLAY.md)。现有公开rank公式还可表达特定的排除自身市场宽度择时，已通过原生MCP验证，见[MARKET_TIMING.md](MARKET_TIMING.md)；仍缺直接的市场状态与多策略组合接口。
