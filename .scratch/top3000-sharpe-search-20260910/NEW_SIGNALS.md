# 新信号、价量择时与尾部对照

更新：2026-09-09T21:36:56.034388+00:00

**新增价量择时的一年期原生候选，但10万元、近期、三年和频率邻居均不支持当前投入。** WQ006开盘价/成交量负相关加MA20强市宽度门控，20只/10日的原生一年期Sharpe为1.480；三年Sharpe降至0.525、回撤23.42%，超过用户上限。它的信号不同于低成交额，市场状态规则相同；不能把参数或状态变体当作完全独立的收益来源。

线上策略固定1000万元，区间终值为2026-09-09开盘；10万元独立回放止于2026-08-27。用户目标仍为100000元、不加杠杆、最大回撤目标20%、Sharpe>1.2。模型收益不能承诺未来亏损封顶。

## 六个新公式的初筛

分属日夜收益分解、收盘位置、非流动性、年度高点附近等方向；低隔夜风险仍是防御风险的成分分解。因子Rank IC与分组收益不等于组合Sharpe。下面每个公式均为同一年期、TOP3000、none。分组收益未计交易费用，按每日信号的重叠持有标签求平均。

|信号|1日Rank IC|5日Rank IC|20日Rank IC|20日q1|20日q5|
|---|---:|---:|---:|---:|---:|
|[QS13 1y overnight_mom20](https://thesistrace.com/research-runs/run_554fb58546b746199ece)|0.018|0.029|0.049|-1.11%|1.40%|
|[QS13 1y intraday_mom20](https://thesistrace.com/research-runs/run_c7887afceb5a48c18dee)|-0.041|-0.058|-0.092|0.69%|-0.34%|
|[QS13 1y low_overnight_risk20](https://thesistrace.com/research-runs/run_938881bcf9fa4ca9a218)|0.021|0.033|0.041|0.44%|-0.41%|
|[QS13 1y clv_volume20](https://thesistrace.com/research-runs/run_2235fb65aad74b129f19)|-0.025|-0.037|-0.053|0.55%|-0.38%|
|[QS13 1y amihud20](https://thesistrace.com/research-runs/run_decb166e6248430b8354)|-0.009|-0.004|-0.010|0.54%|0.07%|
|[QS13 1y near_high252](https://thesistrace.com/research-runs/run_8955849ca2264900b777)|-0.013|-0.017|-0.018|-0.30%|0.64%|

隔夜均值的三个期限IC与q5均为正，因此转入实际策略检验。日内均值和收盘位置出现负向排序关系，之后检验反向规则并保留原方向。年度高点附近虽然q5为正，IC为负且q4更高，不按单一指标直接判定可交易。

这些是探索性日频改写。原论文的市场、信号时点、持有期或多空构造与这里不同；没有把分钟级隔夜预测论文当作20日做多策略的收益证据。[一手文献核查](ROUND13_SOURCES.md)。

## 已完成的实际交易结果

所有行均扣平台费用。本金1000万元，净收益为区间累计值，不是年化值。频率邻居和固定90%分位对照保留；仍在运行的项目另列，不假定结果。

|规则与参数|起点|净收益|最大回撤|Sharpe|费用拖累|
|---|---|---:|---:|---:|---:|
|[QS15 3y wq006_strong_breadth20 H20 R10](https://thesistrace.com/research-runs/run_803cf573db1041b8a73a)|2023-09-11|28.98%|23.42%|0.525|3.81%|
|[QS13 1y overnight_mom20 H10 R20](https://thesistrace.com/research-runs/run_64cbaef8c4124373a82c)|2025-09-10|-4.49%|37.71%|0.152|1.31%|
|[QS13 1y overnight_mom20 H20 R20](https://thesistrace.com/research-runs/run_7b73782d1631488e8d17)|2025-09-10|-23.37%|42.10%|-0.395|1.15%|
|[QS13 1y wq006 H10 R10](https://thesistrace.com/research-runs/run_9aab8652d8a14142b06d)|2025-09-10|2.92%|24.94%|0.245|2.69%|
|[QS13 1y wq006 H20 R10](https://thesistrace.com/research-runs/run_3d8373b9b84642818bac)|2025-09-10|17.54%|20.00%|0.872|2.78%|
|[QS14 1y clv_volume_reversal20 H10 R20](https://thesistrace.com/research-runs/run_62ccbec1662247099e0c)|2025-09-10|-9.50%|29.31%|-0.241|1.25%|
|[QS14 1y clv_volume_reversal20 H20 R20](https://thesistrace.com/research-runs/run_59a79ac183fe4a23bd16)|2025-09-10|-11.23%|32.81%|-0.341|1.21%|
|[QS14 1y intraday_reversal20 H10 R20](https://thesistrace.com/research-runs/run_aa814c655423400bb497)|2025-09-10|-24.17%|44.97%|-0.635|1.13%|
|[QS14 1y intraday_reversal20 H20 R20](https://thesistrace.com/research-runs/run_c514e854a88a4306893d)|2025-09-10|-16.83%|37.57%|-0.434|1.15%|
|[QS14 1y overnight_mom20_industry H10 R20](https://thesistrace.com/research-runs/run_ce498bb41bae4b4182dd)|2025-09-10|-27.74%|36.15%|-0.696|1.15%|
|[QS14 1y overnight_mom20_industry H20 R20](https://thesistrace.com/research-runs/run_13708ce23eba4bed9a0c)|2025-09-10|5.33%|37.84%|0.331|1.39%|
|[QS15 1y neighbor wq006_strong_breadth20 H20 R20](https://thesistrace.com/research-runs/run_02a73e3bcfb14c34a5c6)|2025-09-10|2.18%|13.22%|0.230|0.46%|
|[QS15 1y neighbor wq006_strong_breadth20 H20 R5](https://thesistrace.com/research-runs/run_01769e720e4d4c408b79)|2025-09-10|2.55%|10.78%|0.244|1.95%|
|[QS15 1y overnight20_percentile90 H20 R20](https://thesistrace.com/research-runs/run_3f53d9cb02b6411b9540)|2025-09-10|9.95%|27.53%|0.469|1.45%|
|[QS15 1y wq006_percentile90 H20 R10](https://thesistrace.com/research-runs/run_12a224fe408e4f448d10)|2025-09-10|-4.10%|24.40%|-0.067|2.54%|
|[QS15 1y wq006_strong_breadth20 H10 R10](https://thesistrace.com/research-runs/run_2ccb38495fec4ce894c2)|2025-09-10|7.11%|15.33%|0.520|0.98%|
|[QS15 1y wq006_strong_breadth20 H20 R10](https://thesistrace.com/research-runs/run_8fedee28b1d84c1ebd4b)|2025-09-10|20.60%|7.45%|1.480|0.98%|
|[QS15 1y wq006_weak_breadth20 H10 R10](https://thesistrace.com/research-runs/run_ef92215f1b0f4d3bb19d)|2025-09-10|-6.01%|23.88%|-0.250|1.64%|
|[QS15 1y wq006_weak_breadth20 H20 R10](https://thesistrace.com/research-runs/run_fda37c0660e346399d7a)|2025-09-10|-3.04%|19.32%|-0.103|1.66%|
|[QS15 quarter wq006_strong_breadth20 H20 R10](https://thesistrace.com/research-runs/run_bfd15d265dc74f59aa22)|2026-06-11|-3.43%|6.21%|-1.252|0.11%|

分组q5约覆盖最高20%的股票，而实际策略取极端10/20只，并且只在指定调仓日产生交易。隔夜q5为正但极端Top20亏损，不能单凭这组对比把差异全归因于尾部或手续费。固定90%分位的对照把隔夜策略从亏损变为盈利，但Sharpe仍低且回撤超过20%；不继续搜索最优分位。

## 新候选的10万元回放

保持价量强市规则、20只/10日；全部止于2026-08-27。板块权限筛选、每笔额外10bp成本从真实成交与资金可负担量中计算，没有事后从收益直接相减。

|本金|范围|每笔额外成本|净收益|最大回撤|Sharpe|平均现金|
|---|---|---:|---:|---:|---:|---:|
|10,000,000|all|0bp|20.60%|7.45%|1.509|66.17%|
|100,000|all|0bp|8.85%|5.56%|1.108|78.28%|
|100,000|all|10bp|7.85%|5.75%|0.998|78.26%|
|100,000|main|10bp|5.89%|6.84%|0.712|74.10%|

新增1000万元对照的232个共同历史Session逐日净值与线上完全相同；本地终值日因终值政策不同被明确排除。三个10万元情景与该对照的现金、持仓单位、费用和净值独立核验通过，使用产品的合成总收益结算模型，不是完整券商现金/分红税费账本。

10万元基础情景平均现金约78.28%，1000万元约66.17%。小本金下的可成交数量和费用会改变结果，不能用原生20.60%收益直接推算个人账户。详细边界见[资本回放报告](CAPITAL_REPLAY.md)。

## 数值与样本边界

隔夜Top10一年期净收益-4.49%但Sharpe为+0.152，已独立复算。这段路径的算术日均收益约+0.0299%、日收益标准差约3.135%，平均对数收益约-0.0190%；正的算术均值与亏损的复利结果可以同时出现，不是直接的计算错误证据。[数值诊断](overnight-risk-diagnostic.json)。

价量强市20只/10日与低成交额强市20只/10日的一年期日收益相关系数约0.619。这是共享已观察市场状态下的描述统计，不是组合账户回测或未来分散效果保证。

全部区间与这些公式都参与了探索；后续三年、季度和邻居检查不能冒充未接触的样本外。文献、因子方向、原生收益、实际本金结果均分开记录。

## 产品问题与待续工作

[产品问题10](product-audit/issues/10-factor-tail-diagnostics.md)补充了q5与极端TopN的真实落差；[问题01](product-audit/issues/01-capital-and-account-constraints.md)补充本金适配证据。没有修改或部署产品实现。

原始计划：[Round13](round13-plan.json)、[Round14](round14-plan.json)、[Round15](round15-plan.json)、[候选的后续验证](round15-followup-plan.json)。

最新日10万元回放仍缺数据授权：自动审批拒绝约80MB远端原始行情复制到本地指定目录，尚待明确答复。没有重新传输、拆分或绕路；用户板块权限问题也仍待回复。
