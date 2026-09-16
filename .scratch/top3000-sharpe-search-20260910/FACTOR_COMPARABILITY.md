# 因子重复结果与分组样本口径核对

已核对427份因子摘要，按公式、区间、Universe、中性化、Data Generation和数值/语义版本归并为158个冻结案例。相同案例共有269次重复比较，269次完全一致，超过1e-12的数值差异或结构差异有0次。

这是已有真实结果的可重复性核对，不是新增因子试验，也不代表从原始行情独立重算每个IC。包含单独因子评估与不同持仓/调仓参数的策略关联因子。

三个预测期合计有6行出现q5均值减q1均值与每日配对差值均值相差超过1e-10，其中0行方向相反。平均所用日期可以不同；当前摘要不能恢复每组及配对的有效日期数。

|冻结案例代表|起点|预测期|q5-q1两个均值之差|逐日配对差均值|差距|符号相反|
|---|---|---:|---:|---:|---:|---|
|[QS18 1y chl_spread20_high](https://thesistrace.com/research-runs/run_3241e665026c4dddbba0)|2025-09-10|20|3.2690%|0.2740%|2.9949%|否|
|[QS28 1y d094 chl_spread20_low H10 R20](https://thesistrace.com/research-runs/run_259b855e449c405a92da)|2025-09-10|20|-3.2676%|-0.2774%|-2.9902%|否|
|[QS18 1y chl_spread20_high](https://thesistrace.com/research-runs/run_3241e665026c4dddbba0)|2025-09-10|5|-0.7282%|-0.1947%|-0.5335%|否|
|[QS28 1y d094 chl_spread20_low H10 R20](https://thesistrace.com/research-runs/run_259b855e449c405a92da)|2025-09-10|5|0.7281%|0.1957%|0.5324%|否|
|[QS28 1y d094 chl_spread20_low H10 R20](https://thesistrace.com/research-runs/run_259b855e449c405a92da)|2025-09-10|1|0.1574%|0.1293%|0.0281%|否|
|[QS18 1y chl_spread20_high](https://thesistrace.com/research-runs/run_3241e665026c4dddbba0)|2025-09-10|1|-0.1574%|-0.1295%|-0.0279%|否|

有差距的行需要同时读分组覆盖与配对差值，不应将两种口径混写成同一个“多空收益”。完整重复比较和所有异常汇总保存在[机器证据](factor-comparability-audit.json)。[并列评分与空分组复现](QUANTILE_COVERAGE.md)解释了一种已确认的产生机制，不能由摘要反推所有行的逐日原因。
