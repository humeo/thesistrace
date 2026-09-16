# 自回归预测增量与历史波动率稳定性

更新：2026-09-09T23:10:07.366263+00:00

两个候选各有一个匹配数据覆盖的旧机制对照。区间2025-09-10至2026-09-09，TOP3000，不做行业去均值。对照与窗口变化不增加独立家族数。[预声明](round20-plan.json)、[一手资料及差异](ROUND19_SOURCES.md)。

|方向|角色|1日Rank IC|5日Rank IC|20日Rank IC|固定筛选期|该期q5均值|该期配对差均值|该期Rank IC有效/信号日|候选触发策略|
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
|[ar1_increment60](https://thesistrace.com/research-runs/run_a175dcaa4d43478a9342)|candidate|-0.005|-0.004|-0.001|5|0.03%|-0.08%|236/242|否|
|[reversal1_ar_coverage](https://thesistrace.com/research-runs/run_08d5d897759345438db7)|matched_control|0.019|-0.001|0.006|5|-0.16%|-0.19%|236/242|对照不单独触发|
|[historical_vol_instability20_60_low](https://thesistrace.com/research-runs/run_2e4f8362b0514bb19962)|candidate|0.018|0.034|0.065|20|1.32%|2.42%|221/242|是|
|[lowvol20_instability_coverage](https://thesistrace.com/research-runs/run_33d1768f08b44cb58dcf)|matched_control|0.034|0.052|0.075|20|-0.00%|-0.05%|221/242|对照不单独触发|

AR方向预先固定看5日，且要求1日Rank IC也为正；若通过，再与旧反转对照一起做10/20只、每5日策略。风险稳定性预先固定看20日；若通过，再与旧低波动对照一起做10/20只、每20日策略。所有指标均须正向且Rank IC日覆盖至少90%。

只在1日有效不能推导20日持仓有效，因子IC/ICIR也不是策略Sharpe。控制组单独通过不会触发新的择优搜索。

|实际策略|累计净收益|最大回撤|Sharpe|全年通过|
|---|---:|---:|---:|---|
|[QS20 1y historical_vol_instability20_60_low H10 R20](https://thesistrace.com/research-runs/run_ca1d2fa5162d4eb8bdd1)|4.05%|32.39%|0.288|否|
|[QS20 1y historical_vol_instability20_60_low H20 R20](https://thesistrace.com/research-runs/run_9746504e8af8470380a1)|11.15%|27.81%|0.538|否|
|[QS20 1y lowvol20_instability_coverage H10 R20](https://thesistrace.com/research-runs/run_12ba53e001414fe0b5ff)|4.14%|11.57%|0.426|否|
|[QS20 1y lowvol20_instability_coverage H20 R20](https://thesistrace.com/research-runs/run_966cdd3adfbf4876a99a)|-0.43%|14.21%|0.015|否|

本轮固定检验已完成。自回归方向未通过因子筛选；风险稳定性通过因子筛选后，10只/20只实际策略均低于Sharpe1.2，且回撤超过20%。两个匹配低波动对照也未达到Sharpe1.2。因此本轮没有触发三年、季度或小本金后续，不改窗口或符号继续择优。

风险稳定性10只/20只组合的最大回撤32.39%/27.81%，明显高于匹配低波动对照的11.57%/14.21%。低历史波动率变异系数并不等于低账户回撤；因子相关、分组收益与TopN账户风险需要分别验证。

独立公式核对：本地2026-08-27单日、80个价格观测，4个公式共11678个有效评分；排名/资格差异0项。OLS用独立最小二乘求解，历史波动用独立滚动窗口；两个候选与各自对照的数据覆盖一致。收益重排和正比例缩放的确定性例子验证了公式含义。见[证据](round20-signal-proof.json)。这不证明最新远端收益，也不证明独立经济Alpha。

当前策略若提交，仍是平台原生1000万元。现有本地行情从2025-08-01开始，不足以支持2025-09-10起点所需的61/79日预热；不能删减预热冒充同条件10万元回测。历史波动率代理也不是原文使用的期权隐含波动率。

在跑批次：无。成功待采集：无。
