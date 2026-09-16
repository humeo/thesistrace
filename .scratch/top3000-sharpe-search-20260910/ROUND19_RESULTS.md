# 既有正向因子转为实际持仓后的验证

更新：2026-09-09T23:10:07.366263+00:00

区间2025-09-10至2026-09-09，TOP3000；固定10只或20只，每20交易日调仓。以下使用平台原生1000万元、默认交易费用，不能直接当作10万元收益。

筛选来自已看过的因子结果，属于探索性检验。不同公式或参数不等于独立收益来源。[预声明](round19-plan.json)。

|方向|原因子20日Rank IC|原因子20日q5均值|持仓数|实际累计净收益|实际最大回撤|实际Sharpe|全年通过|
|---|---:|---:|---:|---:|---:|---:|---|
|[lowmax20_none](https://thesistrace.com/research-runs/run_8f7cab7e3b72467ca770)|0.078|0.08%|10|-4.44%|15.86%|-0.261|否|
|[lowmax20_none](https://thesistrace.com/research-runs/run_d164a8db96914d78b5e8)|0.078|0.08%|20|-0.12%|14.97%|0.053|否|
|[downside20_none](https://thesistrace.com/research-runs/run_285c38e87c074b839ec3)|0.049|0.28%|10|12.45%|10.01%|0.971|否|
|[downside20_none](https://thesistrace.com/research-runs/run_6f3a11540849479185aa)|0.049|0.28%|20|1.66%|13.91%|0.208|否|
|[quality_defensive_industry](https://thesistrace.com/research-runs/run_555dda7f88d744d998dd)|0.042|0.26%|10|-14.88%|27.30%|-0.800|否|
|[quality_defensive_industry](https://thesistrace.com/research-runs/run_264c7ea0243d454492aa)|0.042|0.26%|20|-8.26%|28.04%|-0.407|否|
|[positive_roe_none](https://thesistrace.com/research-runs/run_d44a5acfe66a42639bef)|0.042|0.28%|10|-9.59%|29.58%|-0.337|否|
|[positive_roe_none](https://thesistrace.com/research-runs/run_c465a7be404b436e85fa)|0.042|0.28%|20|-16.24%|27.60%|-0.880|否|
|[wq012_ret_none](https://thesistrace.com/research-runs/run_f135fd937953416f9ccd)|0.034|0.51%|10|-27.75%|37.10%|-0.528|否|
|[wq012_ret_none](https://thesistrace.com/research-runs/run_08ae57b1b5ca445ab584)|0.034|0.51%|20|-31.81%|40.17%|-0.789|否|
|[wq013_none](https://thesistrace.com/research-runs/run_eddb56451afe415c8d7c)|0.056|0.51%|10|-33.98%|47.31%|-1.128|否|
|[wq013_none](https://thesistrace.com/research-runs/run_b04fee5ce5314961aef0)|0.056|0.51%|20|-19.01%|39.50%|-0.636|否|
|[revenue_growth252_none](https://thesistrace.com/research-runs/run_b4709084b1c148d5bda1)|0.040|1.33%|10|-15.26%|26.41%|-0.490|否|
|[revenue_growth252_none](https://thesistrace.com/research-runs/run_0292b71688a64b9891e2)|0.040|1.33%|20|-9.03%|23.35%|-0.251|否|

已采集14项策略，0项达到全年Sharpe>1.2且回撤≤20%。原始q5是宽分组、重叠未来标签的均值，不是Top10/20连续账户收益；它没有包含相同的持仓和费用约束。

未通过的组合保留负结果，不在看到结果后继续挑调仓频率。通过全年筛选才按预声明进入固定三年和近期验证。

营业收入增长方向在QS18财务因子批次完成后提交。两项Strategy Sweep因共享批次容量被拒绝，随后保持原公式、区间、TOP3000及持仓参数改为单ResearchRun。原拒绝与恢复分别记录，接受不代表完成，也不是新增研究假设。见[容量诊断](product-audit/issues/09-batch-capacity-diagnostics.md)。

尚缺已接受任务的方向：无。在跑批次：无。在跑单任务：无。成功待采集：无。

产品发现：从已完成因子继续做策略，需要在本地保存源Result关联；当前批次内部确实共享Alpha/Factor计算，但跨批次来源与复用信息没有同等直接的工作流。见[问题12](product-audit/issues/12-factor-to-strategy-lineage.md)。
