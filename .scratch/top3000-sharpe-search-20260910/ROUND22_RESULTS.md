# 既有正向因子的实际策略覆盖补齐

更新：2026-09-09T23:41:05.676329+00:00

九项均来自已看过的最新年因子结果。本轮不新增公式，不把中性化、组合或持仓参数变体算作独立Alpha。此前QS19覆盖七项，现按同一正向条件补齐其余未接受过实际策略任务的案例。效率变化的资源失败另行保留，没有原样重提。

固定区间2025-09-10至2026-09-09、TOP3000、10或20只、每20交易日调仓；保留各原因子的行业去均值选择。原生本金1000万元、默认费用，无杠杆，不能直接缩放成10万元账户。[提交前预声明](round22-plan.json)、[全量筛选审计](round22-selection-audit.json)、[数据状态](round22-research-context.json)。

|因子案例|20日Rank IC|20日q5均值|20日配对差均值|q4高于q5|
|---|---:|---:|---:|---|
|[wq002_none](https://thesistrace.com/research-runs/run_60df9a11a25f46818d29)|0.033|0.50%|0.49%|否|
|[wq003_none](https://thesistrace.com/research-runs/run_96f0e93b67a64188996f)|0.031|0.59%|0.88%|否|
|[lowmax20_industry](https://thesistrace.com/research-runs/run_f4e09b8219c941809880)|0.074|0.06%|0.45%|是|
|[lowvol20_industry](https://thesistrace.com/research-runs/run_33fdd58ba3dc40e3b755)|0.073|0.00%|0.33%|是|
|[cash_margin_industry](https://thesistrace.com/research-runs/run_d035fa00d9da461a99db)|0.013|0.43%|0.01%|否|
|[positive_roe_industry](https://thesistrace.com/research-runs/run_6664419e68454db592ee)|0.033|0.40%|0.58%|是|
|[profit_margin_industry](https://thesistrace.com/research-runs/run_eaeefdeffbb54d0ba37d)|0.032|0.70%|0.95%|否|
|[quality_defensive_none](https://thesistrace.com/research-runs/run_81043aa264fb4a2881a0)|0.043|0.11%|0.18%|是|
|[volume_dry_lowvol_none](https://thesistrace.com/research-runs/run_dcb3b9c7536f433f8179)|0.082|0.07%|0.16%|是|

筛选条件为20日Rank IC、q5和逐日配对差均值均正，Rank IC日覆盖至少90%，且同公式/区间/股票池/中性化尚无已接受的实际策略尝试。极小分组收益及q4高于q5的警示保留，不事后改阈值。因子标签均值尚未扣相同的持仓与费用，不能用它代替连续账户结果。

|实际策略|累计净收益|最大回撤|Sharpe|状态／全年通过|
|---|---:|---:|---:|---|
|[wq002_none H10 R20](https://thesistrace.com/research-runs/run_0b392f7f468c4823b6b0)|25.71%|29.50%|0.987|否|
|[wq002_none H20 R20](https://thesistrace.com/research-runs/run_521b1c390bc9431fbbef)|3.98%|27.57%|0.289|否|
|[wq003_none H10 R20](https://thesistrace.com/research-runs/run_1fef61cdcb8b47d58aae)|10.91%|22.35%|0.556|否|
|[wq003_none H20 R20](https://thesistrace.com/research-runs/run_31aa367b51854a9fbd52)|10.99%|17.62%|0.595|否|
|[lowmax20_industry H10 R20](https://thesistrace.com/research-runs/run_63393a4c245040f4bfd2)|4.92%|14.87%|0.353|否|
|[lowmax20_industry H20 R20](https://thesistrace.com/research-runs/run_d6b632ee5ee143269c38)|1.34%|17.14%|0.167|否|
|[lowvol20_industry H10 R20](https://thesistrace.com/research-runs/run_52968cf79c994b49a8e8)|-1.25%|14.04%|-0.007|否|
|[lowvol20_industry H20 R20](https://thesistrace.com/research-runs/run_7bb62048148e4ae0a282)|-2.92%|15.73%|-0.121|否|
|[cash_margin_industry H10 R20](https://thesistrace.com/research-runs/run_8327dd40cdf54721b6a2)|-21.40%|41.97%|-0.546|否|
|[cash_margin_industry H20 R20](https://thesistrace.com/research-runs/run_1d82f358d6504066b9b8)|-16.97%|39.62%|-0.500|否|
|[positive_roe_industry H10 R20](https://thesistrace.com/research-runs/run_a3b6fad0acd04f869b6b)|-17.85%|33.13%|-0.680|否|
|[positive_roe_industry H20 R20](https://thesistrace.com/research-runs/run_172ba011cc4e4f47941d)|-6.07%|27.82%|-0.176|否|
|[profit_margin_industry H10 R20](https://thesistrace.com/research-runs/run_6fb4b3a3dc80443a94a7)|-23.08%|37.95%|-1.010|否|
|[profit_margin_industry H20 R20](https://thesistrace.com/research-runs/run_1e4fb5bcda304fcfaaf5)|-28.64%|43.70%|-1.350|否|
|[quality_defensive_none H10 R20](https://thesistrace.com/research-runs/run_fd375d4b19d042a7826a)|-8.47%|23.61%|-0.430|否|
|[quality_defensive_none H20 R20](https://thesistrace.com/research-runs/run_ef1ee9e6f70941f58f19)|-12.69%|22.34%|-0.763|否|
|[volume_dry_lowvol_none H10 R20](https://thesistrace.com/research-runs/run_7f7cb4b361c24e72836d)|4.15%|29.16%|0.301|否|
|[volume_dry_lowvol_none H20 R20](https://thesistrace.com/research-runs/run_1680945deddc4abc85da)|2.47%|25.54%|0.228|否|

已采集18/18项全年策略，0项通过。未完成、失败和已完成的经济负结果分开记录。

仅实际全年Sharpe>1.2且回撤≤20%触发相同参数的固定三年（2023-09-11起）和季度（2026-06-11起）验证。已经看过的历史仍属探索，不能称未接触的样本外。不在本轮结果出来后继续调频率、符号或门槛。

在跑批次：无。在跑单任务：无。成功待采集：无。

行业去均值作用于Alpha，不等于实际组合行业中性。10万元本金、板块权限和最新行情回放仍需独立证据；原始行情导出授权未解决，不据此停止可用MCP上的研究，也不绕过传输审批。

本轮收益最高WQ002 H10的242条完整净值已另用Decimal复算：累计净收益25.71%、最大回撤29.50%、Sharpe0.987，与平台摘要一致。峰值2026-05-14、谷值2026-07-21；高收益仍不符合20%回撤目标。[完整净值审计](round22-high-return-nav-audit.json)。
