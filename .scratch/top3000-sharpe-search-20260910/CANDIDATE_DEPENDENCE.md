# 高Sharpe案例之间的账户收益相关性

更新：2026-09-09T22:52:41.922404+00:00

只比较相同起止日期、相同原生本金的完整日净收益。先排除两项已证明逐日观察重复的现金对照，再读取已完成的净值；不把不同起始持仓的账户拼接，不组合资金或拟合权重。

原先14个Sharpe>1.2案例去掉两项重复对照后为12项；其中12项有完整净值，缺失0项。按区间分别比较，共25对。单独的三年案例没有同起点的过线对照。

|区间起点|左侧案例|右侧案例|净日收益数|Pearson相关性|同一公式文本|
|---|---|---|---:|---:|---|
|2025-09-10|[QS10 1y lowamount LOO_breadth20 H10 R5](https://thesistrace.com/research-runs/run_e20c03fe0028468799de)|[QS16 1y market_switch_amount_lowvol H10 R5](https://thesistrace.com/research-runs/run_c9871f3c547147bc80a1)|241|0.865|否|
|2025-09-10|[QS10 1y lowamount LOO_breadth20 H20 R10](https://thesistrace.com/research-runs/run_ec334d7e6ddd464f806e)|[QS16 1y market_switch_amount_lowvol H20 R10](https://thesistrace.com/research-runs/run_fe6c5b6b5f2d4a2395da)|241|0.748|否|
|2025-09-10|[QS16 1y market_switch_amount_lowvol H10 R5](https://thesistrace.com/research-runs/run_c9871f3c547147bc80a1)|[QS16 1y market_switch_amount_lowvol H20 R10](https://thesistrace.com/research-runs/run_fe6c5b6b5f2d4a2395da)|241|0.625|是|
|2025-09-10|[QS10 1y lowamount LOO_breadth20 H20 R10](https://thesistrace.com/research-runs/run_ec334d7e6ddd464f806e)|[QS15 1y wq006_strong_breadth20 H20 R10](https://thesistrace.com/research-runs/run_8fedee28b1d84c1ebd4b)|241|0.619|否|
|2025-09-10|[QS10 1y lowamount LOO_breadth20 H10 R5](https://thesistrace.com/research-runs/run_e20c03fe0028468799de)|[QS15 1y wq006_strong_breadth20 H20 R10](https://thesistrace.com/research-runs/run_8fedee28b1d84c1ebd4b)|241|0.549|否|
|2025-09-10|[QS15 1y wq006_strong_breadth20 H20 R10](https://thesistrace.com/research-runs/run_8fedee28b1d84c1ebd4b)|[QS16 1y market_switch_amount_lowvol H20 R10](https://thesistrace.com/research-runs/run_fe6c5b6b5f2d4a2395da)|241|0.461|否|
|2025-09-10|[QS15 1y wq006_strong_breadth20 H20 R10](https://thesistrace.com/research-runs/run_8fedee28b1d84c1ebd4b)|[QS16 1y market_switch_amount_lowvol H10 R5](https://thesistrace.com/research-runs/run_c9871f3c547147bc80a1)|241|0.454|否|
|2025-09-10|[QS10 1y lowamount LOO_breadth20 H10 R5](https://thesistrace.com/research-runs/run_e20c03fe0028468799de)|[QS10 1y lowamount LOO_breadth20 H20 R10](https://thesistrace.com/research-runs/run_ec334d7e6ddd464f806e)|241|0.433|是|
|2025-09-10|[QS10 1y lowamount LOO_breadth20 H20 R10](https://thesistrace.com/research-runs/run_ec334d7e6ddd464f806e)|[QS16 1y market_switch_amount_lowvol H10 R5](https://thesistrace.com/research-runs/run_c9871f3c547147bc80a1)|241|0.390|否|
|2025-09-10|[QS10 1y lowamount LOO_breadth20 H10 R5](https://thesistrace.com/research-runs/run_e20c03fe0028468799de)|[QS16 1y market_switch_amount_lowvol H20 R10](https://thesistrace.com/research-runs/run_fe6c5b6b5f2d4a2395da)|241|0.375|否|
|2026-06-11|[QS16 quarter market_switch_amount_lowvol H20 R10](https://thesistrace.com/research-runs/run_7e94f022b5da43838f6f)|[QS5 63s lowvol20 H100 R10](https://thesistrace.com/research-runs/run_96384289b08844dca9dc)|63|0.849|否|
|2026-06-11|[QS17 quarter market_switch_neighbor H10 R4](https://thesistrace.com/research-runs/run_88c7a5cd7d1a4ff3b57e)|[QS17 quarter market_switch_neighbor H20 R9](https://thesistrace.com/research-runs/run_b97c74f3cf7946eea447)|63|0.812|是|
|2026-06-11|[QS16 quarter market_switch_amount_lowvol H10 R5](https://thesistrace.com/research-runs/run_9a68e61b294844ab9aa7)|[QS17 quarter market_switch_neighbor H20 R11](https://thesistrace.com/research-runs/run_d898227ac09e41779c31)|63|0.804|是|
|2026-06-11|[QS17 quarter market_switch_neighbor H20 R11](https://thesistrace.com/research-runs/run_d898227ac09e41779c31)|[QS17 quarter market_switch_neighbor H20 R9](https://thesistrace.com/research-runs/run_b97c74f3cf7946eea447)|63|0.774|是|
|2026-06-11|[QS16 quarter market_switch_amount_lowvol H10 R5](https://thesistrace.com/research-runs/run_9a68e61b294844ab9aa7)|[QS16 quarter market_switch_amount_lowvol H20 R10](https://thesistrace.com/research-runs/run_7e94f022b5da43838f6f)|63|0.756|是|
|2026-06-11|[QS16 quarter market_switch_amount_lowvol H20 R10](https://thesistrace.com/research-runs/run_7e94f022b5da43838f6f)|[QS17 quarter market_switch_neighbor H10 R4](https://thesistrace.com/research-runs/run_88c7a5cd7d1a4ff3b57e)|63|0.733|是|
|2026-06-11|[QS16 quarter market_switch_amount_lowvol H20 R10](https://thesistrace.com/research-runs/run_7e94f022b5da43838f6f)|[QS17 quarter market_switch_neighbor H20 R11](https://thesistrace.com/research-runs/run_d898227ac09e41779c31)|63|0.717|是|
|2026-06-11|[QS16 quarter market_switch_amount_lowvol H10 R5](https://thesistrace.com/research-runs/run_9a68e61b294844ab9aa7)|[QS17 quarter market_switch_neighbor H20 R9](https://thesistrace.com/research-runs/run_b97c74f3cf7946eea447)|63|0.681|是|
|2026-06-11|[QS16 quarter market_switch_amount_lowvol H10 R5](https://thesistrace.com/research-runs/run_9a68e61b294844ab9aa7)|[QS17 quarter market_switch_neighbor H10 R4](https://thesistrace.com/research-runs/run_88c7a5cd7d1a4ff3b57e)|63|0.677|是|
|2026-06-11|[QS16 quarter market_switch_amount_lowvol H20 R10](https://thesistrace.com/research-runs/run_7e94f022b5da43838f6f)|[QS17 quarter market_switch_neighbor H20 R9](https://thesistrace.com/research-runs/run_b97c74f3cf7946eea447)|63|0.662|是|
|2026-06-11|[QS17 quarter market_switch_neighbor H20 R11](https://thesistrace.com/research-runs/run_d898227ac09e41779c31)|[QS5 63s lowvol20 H100 R10](https://thesistrace.com/research-runs/run_96384289b08844dca9dc)|63|0.660|否|
|2026-06-11|[QS16 quarter market_switch_amount_lowvol H10 R5](https://thesistrace.com/research-runs/run_9a68e61b294844ab9aa7)|[QS5 63s lowvol20 H100 R10](https://thesistrace.com/research-runs/run_96384289b08844dca9dc)|63|0.644|否|
|2026-06-11|[QS17 quarter market_switch_neighbor H10 R4](https://thesistrace.com/research-runs/run_88c7a5cd7d1a4ff3b57e)|[QS17 quarter market_switch_neighbor H20 R11](https://thesistrace.com/research-runs/run_d898227ac09e41779c31)|63|0.594|是|
|2026-06-11|[QS17 quarter market_switch_neighbor H10 R4](https://thesistrace.com/research-runs/run_88c7a5cd7d1a4ff3b57e)|[QS5 63s lowvol20 H100 R10](https://thesistrace.com/research-runs/run_96384289b08844dca9dc)|63|0.586|否|
|2026-06-11|[QS17 quarter market_switch_neighbor H20 R9](https://thesistrace.com/research-runs/run_b97c74f3cf7946eea447)|[QS5 63s lowvol20 H100 R10](https://thesistrace.com/research-runs/run_96384289b08844dca9dc)|63|0.527|否|

这些都是从已搜索历史中挑出的案例，相关性只是该段账户收益的描述。高相关提示不能简单把策略数量当作分散程度；低相关也不证明经济机制独立、未来相关性稳定或合并后的10万元账户可执行。季度样本尤其短，不能从它反推出全年关系。

原始来源为每个Result和完整strategy_observations；所有输入净值重算Sharpe已与对应摘要核对。当前结果没有新增策略或新的Sharpe>1.2案例。[完整配对数据](candidate-dependence.json)。
