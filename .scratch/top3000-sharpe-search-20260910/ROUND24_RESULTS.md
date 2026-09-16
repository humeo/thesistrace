# 经营效率策略的等价公式恢复

更新：2026-09-09T23:51:30.145Z

旧QS18经营效率变化因子通过预设筛选，但原式H10/H20策略都在252日预热后、第4个研究日因资源限制失败。本轮先证明等价简写，再提交一个H10R20恢复任务；该任务运行至第68个研究日后仍然失败，没有Result。依照预声明不再提交H20，因此两项实际策略的经济结论仍未解决。[恢复计划](round24-plan.json)、[本轮状态](round24-execution-state.json)、[失败Run](https://thesistrace.com/research-runs/run_164b822dc3dd48c98c1c)。

原式为：

```text
rank(revenue / assets - lag(revenue / assets, 252) + 0 * log(assets) + 0 * log(lag(assets, 252)))
```

等价简写为：

```text
rank(delta(revenue / assets + 0 * log(assets), 252))
```

正资产门控移入delta，在当前和252交易日前分别验证有效性；公式节点和静态工作量从22降到11，字段、252回看、股票池、日期和H10R20均保留。它属于同一个效率变化定义，不是新增经济机制。当前列式执行已经共享相同子表达式并释放不用的临时值，所以不能把节点减半直接解释为实际RSS减半。

独立计算验证了64个合成标的、252个预热及242个研究日，14,226个有效评分：原式、简写、逐股执行、列式执行以及64日分段/252日上下文均精确一致。覆盖零/负/缺失资产、负/缺失收入、非有限值与除法溢出、并列、变化的股票池和中间日期缺口。该证明验证Alpha代数与分段上下文，不声称验证了真实财报投影、Worker检查点或原生实际账户。[证明及代码](round24-rewrite-proof.json)、[校验脚本](prove_round24_efficiency_rewrite.py)、[原生公式诊断](round24-formula-diagnostics.json)。

在3000成员、2字段、1536MiB预算的本地容量模型示例中，规划峰值由567,076,864降至449,860,864字节，64日Chunk维持一致；这不是远端进程的内存实测。正式恢复任务耗时84.60秒，错误仍为“Research execution exceeded its resource limit.”。公开MCP未给出实际RSS、具体预算或触发分支，不能凭失败发生更晚就证明根因或性能改善。[原先四次提交与故障证据](product-audit/round21-capacity-recovery.json)。

原因子20日Rank IC约0.0075、最高分组均值约0.815%不等于可执行策略Sharpe。当前原生本金1000万元，用户本金10万元与20%回撤目标保持；没有缩短预热、更换股票池、修改产品、重试被拒绝的行情导出或把未完成任务算成收益为负。
