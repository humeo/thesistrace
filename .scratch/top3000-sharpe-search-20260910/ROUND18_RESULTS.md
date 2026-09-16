# 经营效率、成交活动稳定性与日线价差代理

更新：2026-09-09T23:56:01.622364+00:00

已采集6/6项预先固定的因子方向/对照、2项实际策略。三个研究方向并不等于三个已证明独立的收益来源；反号与匹配水平对照不增加家族数。数据固定到2026-09-09，区间从2025-09-10开始。

成交额稳定性方向通过因子初筛，实际10只和20只/每20交易日组合均未通过Sharpe1.2；低价差方向虽有正20日Rank IC，q5平均收益却为负，也未达到预声明筛选条件。

策略仍用平台固定1000万元，无杠杆，默认费用；不等于用户10万元账户。[完整预声明](round18-plan.json)、[一手论文及与实现的差异](ROUND17_SOURCES.md)。

|因子方向|1日Rank IC|5日Rank IC|20日Rank IC|20日q5均值|20日每日多空差均值|20日Rank IC有效/信号日|是否进入实际策略|
|---|---:|---:|---:|---:|---:|---:|---|
|[efficiency_change252](https://thesistrace.com/research-runs/run_7cc76e54acae44e08a15)|0.0019|0.0051|0.0075|0.8151%|0.6758%|221/242|是|
|[efficiency_level_matched](https://thesistrace.com/research-runs/run_9663e16b7372410ea861)|-0.0000|-0.0008|-0.0063|-0.2405%|-0.3664%|221/242|否|
|[amount_cv60_low](https://thesistrace.com/research-runs/run_eacbec2c3a244eb7b7f7)|0.0197|0.0328|0.0698|1.0729%|1.8463%|221/242|是|
|[amount_cv60_high](https://thesistrace.com/research-runs/run_0d882b87a1f64c4ebc7c)|-0.0197|-0.0328|-0.0698|-0.7750%|-1.8498%|221/242|否|
|[chl_spread20_low](https://thesistrace.com/research-runs/run_71964d3822e644108386)|0.0029|0.0089|0.0328|-3.1855%|-0.2774%|221/242|否|
|[chl_spread20_high](https://thesistrace.com/research-runs/run_3241e665026c4dddbba0)|-0.0029|-0.0089|-0.0328|0.0834%|0.2740%|221/242|否|

q5是因子标签的等权分组均值，不是扣成本的连续账户收益；IC没有直接可比的策略Sharpe。截止日前没有完整未来标签的信号日不会参与对应预测期均值。

## 已完成的连续账户策略

|参数|累计净收益|最大回撤|Sharpe|费用/初始本金|通过全年筛选|
|---|---:|---:|---:|---:|---|
|[QS18 1y amount_cv60_low H10 R20](https://thesistrace.com/research-runs/run_3cbd7537dd7a4a2b999d)|-0.36%|25.58%|0.084|1.04%|否|
|[QS18 1y amount_cv60_low H20 R20](https://thesistrace.com/research-runs/run_2cdc9b788a394081894a)|7.66%|19.59%|0.507|0.96%|否|

仅当同一全年策略同时Sharpe>1.2、回撤≤20%时，按计划安排三年/近期及小资金验证。低CV两项不触发后续；没有改用另一个预测期、分位或调仓频率来追加择优。

## 分组覆盖的诊断发现

CHL代理先对样本矩截零，会产生大量并列。低价差20日q5=-3.1855%，q1=+0.0821%，两个均值的差为-3.2676%，而逐日两端差的均值为-0.2774%。这几项可能来自不同有效日期；手工两日例子已与当前计算核对。

本地233个信号日，未筛未来标签前q5为空193日。该统计截至8月27日，不等于远端9月9日结果的精确有效日。MCP只返回整体quantile_valid_session_count，缺每组与配对差值的有效日期数。见[分组覆盖证据](QUANTILE_COVERAGE.md)。

## 尚未完成

- 已过因子初筛且实际策略仍待完成：efficiency_change252
- 单任务 `run_c17b5a72dc0d483da801` 已失败：Research execution exceeded its resource limit.。未产生Result，不能填入收益或计作经济负结果；不会原样重提已确定的资源失败。
- 单任务 `run_4cfbc3af66b84752ac4c` 已失败：Research execution exceeded its resource limit.。未产生Result，不能填入收益或计作经济负结果；不会原样重提已确定的资源失败。

效率变化的两项Strategy Sweep因共享批次容量被拒绝，未创建批次或策略。保持原公式、TOP3000、区间和10/20只、20日调仓参数，改为单ResearchRun提交；单任务是否完成以上述状态和Result为准。拒绝记录不计作经济负结果。见[容量诊断](product-audit/issues/09-batch-capacity-diagnostics.md)。

当前252交易日财务滞后只表示相隔252个研究交易日的可见字段，不能声称精确年度财报同比或完整Piotroski F-score。价差代理不是实测盘口，也不能替代滑点。[2025年成交活动研究](https://onlinelibrary.wiley.com/doi/full/10.1111/jtsa.12802)还提示方向会随采样变化，因此本文不从文献继承收益保证。

[QS24等价恢复](ROUND24_RESULTS.md)：22节点原式简写为11节点delta后，单H10任务仍在第68个研究日因资源限制失败，没有Result；依照预声明停止H20派发。该恢复没有改变252回看或经济定义，两项实际策略仍未完成。
