# 原始信号的一年期覆盖补测

更新：2026-09-10T00:35:09.014706+00:00

原始20个固定定义中，3个已有同公式的一年期结果；原始ROE已由正权益修正版取代，其余16个补测。不按旧收益挑选，也不更改方向、窗口或权重。非流动性已有正比例缩放版本，本轮原式另作核对，均不计新增经济家族。[预声明](round26-plan.json)、[20项完整覆盖清单](round26-selection-audit.json)。

固定TOP3000、2025-09-10至2026-09-09、无行业去均值。长区间为2018-01-02至2026-09-09，包含本次一年期，不是独立样本。因子统计不等于账户收益。

|原始信号|长区间20日Rank IC|本次20日Rank IC|本次20日最高组|本次20日配对差|有效/信号日|因子通过|
|---|---:|---:|---:|---:|---:|---|
|[1日反转](https://thesistrace.com/research-runs/run_da0745684e9a46db9395)|0.0135|0.0063|-0.10%|-0.33%|221/242|否|
|[5日反转](https://thesistrace.com/research-runs/run_1fa9b1f58bff4393a359)|0.0399|0.0370|-0.04%|-0.14%|221/242|否|
|[20日反转](https://thesistrace.com/research-runs/run_a8110468f00240e1ad52)|0.0749|0.0701|0.45%|0.21%|221/242|是|
|[5日均线偏离反转](https://thesistrace.com/research-runs/run_99120b5e714045c7b433)|0.0295|0.0203|-0.25%|-0.40%|221/242|否|
|[20日均线偏离反转](https://thesistrace.com/research-runs/run_58a23389973c40d8b30b)|0.0673|0.0613|0.19%|-0.05%|221/242|否|
|[5日日内反转](https://thesistrace.com/research-runs/run_524fbaf0a9e34f2b8f92)|0.0549|0.0535|0.34%|0.49%|221/242|是|
|[20日隔夜反转](https://thesistrace.com/research-runs/run_fbdc0fa7bbcc4647b712)|-0.0277|-0.0493|-1.11%|-2.50%|221/242|否|
|[5日收盘位置反转](https://thesistrace.com/research-runs/run_f8402f33bcaa4675acaa)|0.0284|0.0364|0.47%|0.89%|221/242|是|
|[中期动量跳过近期20日](https://thesistrace.com/research-runs/run_b1954e9403fa4d4985b1)|-0.0141|0.0011|1.07%|1.64%|221/242|是|
|[60日低收益波动](https://thesistrace.com/research-runs/run_2e21a54f71cc441c83f2)|0.0862|0.0508|-0.16%|-0.58%|221/242|否|
|[20日低振幅](https://thesistrace.com/research-runs/run_9739b9e70eb6441684e7)|0.0924|0.0667|-0.00%|-0.65%|221/242|否|
|[20日非流动性](https://thesistrace.com/research-runs/run_81dccaab20a8466a8a96)|0.0160|-0.0101|0.07%|-0.46%|221/242|否|
|[5比60日缩量](https://thesistrace.com/research-runs/run_37a6bf4f2a8942868c78)|0.0546|0.0612|-0.06%|0.32%|221/242|否|
|[资产盈利率](https://thesistrace.com/research-runs/run_778481f71efb4fb1a2c6)|0.0098|0.0349|0.20%|0.54%|221/242|是|
|[现金盈利相对利润](https://thesistrace.com/research-runs/run_72cb553f9e4446368270)|0.0119|-0.0230|-0.59%|-1.41%|221/242|否|
|[低资产负债率](https://thesistrace.com/research-runs/run_818481a893ff41989612)|-0.0046|-0.0042|0.24%|0.48%|221/242|否|

固定筛选要求20日Rank IC、最高组收益与配对差均为正，有效日覆盖至少90%。通过后按10/20只、每20日调仓检查真实策略；不把1/5日较好结果改为事后筛选标准。

|实际策略|持仓/调仓|累计净收益|最大回撤|Sharpe|全年通过|
|---|---|---:|---:|---:|---|
|[rev20](https://thesistrace.com/research-runs/run_44b9548bba4449559899)|10/20|-15.28%|43.43%|-0.2688|否|
|[rev20](https://thesistrace.com/research-runs/run_47cdfd9fa3b147ff8ae7)|20/20|0.26%|33.43%|0.1840|否|
|[intraday5](https://thesistrace.com/research-runs/run_b22b9be9d274427ca2d7)|10/20|-1.04%|40.62%|0.1698|否|
|[intraday5](https://thesistrace.com/research-runs/run_fe6db5c8d9264a54a1fe)|20/20|-16.03%|39.55%|-0.3399|否|
|[close_location5](https://thesistrace.com/research-runs/run_2f8ab0fceb9b4055a893)|10/20|-9.81%|32.78%|-0.1979|否|
|[close_location5](https://thesistrace.com/research-runs/run_d98414ebc0ac401298c1)|20/20|-0.88%|32.45%|0.1035|否|
|[momentum120_skip20](https://thesistrace.com/research-runs/run_adcd6e7d9237470b90de)|10/20|-5.86%|43.14%|0.1145|否|
|[momentum120_skip20](https://thesistrace.com/research-runs/run_a64d9045d7314c39bab4)|20/20|-17.09%|46.72%|-0.1617|否|
|[roa](https://thesistrace.com/research-runs/run_041d1b65491040b7b871)|10/20|-17.18%|23.69%|-0.6871|否|
|[roa](https://thesistrace.com/research-runs/run_546191d4caf44a40a8e9)|20/20|-21.05%|25.90%|-1.2692|否|

本轮16个因子全部完成，5个通过预设因子筛选，其10个实际策略全部未达到Sharpe>1.2与回撤≤20%。实际Sharpe范围−1.269至0.184，最大回撤23.69%至46.72%；不追加其他期限或调参。

中期动量20只持仓案例已取回完整242日净值（241个相邻收益区间）并用Decimal独立复算。净收益、46.72%回撤、峰谷日期及费用一致，Sharpe差小于3e−17。核对器最初误加一个零收益区间，修正后通过；产品和原Result均未修改。[完整复算及首次偏差说明](round26-momentum-nav-audit.json)。

已收集16/16个因子，10个全年策略；通过因子条件5项，待完成全年策略0项。

原生账户本金1000万元。用户的10万元、20%回撤目标不变；未通过本金、成本、权限、近期和长周期检验前，不列为可实施结论。
相同参数的三年和季度检查由全年实际Sharpe>1.2且回撤≤20%触发；窗口均已参与探索，不宣称样本外。

状态：complete_fixed_round_no_further_followup。活跃批次：无。成功待采集：无。
