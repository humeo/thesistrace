# 批次容量约束需要可发现的估算与可恢复诊断

Status: needs-triage
Priority: P2
Type: product-research
Evidence class: reproduced MCP admission problem
Observed: 2026-09-10

## 复现

get_research_context声明批次1至20项。本次12个公式都通过diagnose_alpha_formula，TOP3000、最近一年、industry组合提交时收到RESEARCH_BATCH_EXCEEDS_WORKER_CAPACITY。错误field=universe，只说明Worker不能执行一个共享Research Batch session，没有估算值、当前上限或建议拆分依据。

请求：submissions/r7-new-factors-industry.json。相同股票池、时间段、中性化和公式，拆成6个行情类与6个财务类后两批均被接受。恢复请求：submissions/r7-new-factors-industry-market.json、submissions/r7-new-factors-industry-financial.json。没有重提已接受任务，也没有缩小研究范围。

## 影响与建议

公开20项是数量上限，不保证每个20项组合都能运行，这个边界本身可以合理；问题是agent必须在写入提交阶段试探组合容量，且错误指向universe容易误导它改变研究范围。

建议提供有权限和大小边界的提交前容量评估，或者在拒绝中返回使用量/上限/主要影响项及安全拆分建议。保留无法执行时明确拒绝，不能通过运行时降级或默默减少股票池解决。

## 验收建议

相同输入与机器容量下评估和实际admission一致；错误明确是集合共享成本；支持从12项拆成6+6且不会重复接受被拒绝请求中的子任务；request_id重放语义一致。

## Comments

QS28后段完成记录：d080 H10/H20单任务均成功，保持251日预热与TOP3000。d091效率水平有效样本控制则在60.63秒后以通用资源限制失败，停在252/252预热、4/242研究日、4块；H20未派发。其静态24节点/工作24仍不能预测该运行边界。两类证据不能合并为“长回看不可执行”或具体OOM原因，详见[执行时序与原始输入](../../round28-long-lookback-execution-evidence.json)。

QS28 d080补充了行情长回看入口差异：`rank(close / ts_max(close, 252))` 的双账户H10/H20R20扫描在准入时被同一容量错误拒绝，没有batch_id或run_id。按冻结协议保留TOP3000、251个必需历史session、公式、none、日期及N/R，H10单任务被接受并成功完成251/251预热与242/242研究日；Sharpe−0.732、回撤45.03%，只说明能完成计算且该账户未达标。随后才提交H20单任务，其状态以实时研究记录为准。这说明此拒绝不能直接推断原条件不可运行；也不能通过削减历史或股票池恢复。原始拒绝文件未改写，[审查决定](../../round28-admission-resolutions.json)保留其SHA和固定计划SHA；[H10完整结果](../../results/run_eac1cfcf87f94f2ab955.json)。此处是MCP复现，无新增UI截图，也不声称产品问题已修复。

QS28 后续：d062 行业资产增长 H10 也在相同的 252 日预热、68/242 研究日、5块后以资源上限失败，耗时62.68秒；该定义 H20 未派发。同期 d063 行业收入增长 H10 在99.63秒成功完成全年，实际Sharpe−0.303。不能把不同定义的成功当作资产增长已恢复，也不能将两个失败推成所有252日财务任务不可运行。仍没有具体资源使用量或OOM证据。见[对照执行记录](../../round28-financial252-execution-evidence.json)。

QS28 又有一个合法单任务未能完成：d052 为单字段资产增长排名，静态 9 节点/工作9、有效回看252；TOP3000、none、H10/R20，单 ResearchRun 已接受。在 252/252 预热、68/242 研究日、5 个已提交块（末日2025-12-22）后以资源上限失败，耗时59.14秒，Result不可用。已停止该定义未派发的 H20，未原样重提；它与已关闭的效率变化失败一样留作执行未解决。简单表达式也发生运行失败，进一步说明语法/静态预算通过不足以说明运行资源充足；公开原因仍不能定位为具体内存或容器问题。冻结清单中的行业处理变体 d062 作为不同定义已按计划首次派发，必须单独记录结果，不能把它称为已恢复 d052。证据：[d052失败Run](../../runs/run_cc031d9dc41b4717aca1.json)、[固定审计计划](../../round28-plan.json)、[当前状态](../../round28-execution-state.json)。本段为 MCP 证据，未新增失败页截图。

2026-09-10，QS24增加了不同计算表达式的恢复证据：经营效率原式节点22、静态工作22，等价delta简写节点11、工作11；252回看和TOP3000未变。独立合成数据上14,226个有效评分在逐股、列式和分段上下文中均一致。本地容量模型示例的规划内存降低，但远端单H10任务仍在第68个研究日失败（原式为第4日），耗时84.60秒，仍只返回统一resource-limit说明。不能把失败变晚解读为已定位RSS问题或产品性能改善；没有Result，没有派发H20或再次原样重试。证据：../../ROUND24_RESULTS.md、../../round24-rewrite-proof.json、../../runs/run_164b822dc3dd48c98c1c.json。本次未新增UI截图或产品修复。

2026-09-10：两批拆分已经accepted；这仅解决当前研究提交，不代表产品问题已修复。证据以研究目录为根。


2026-09-10补充：none10项通过admission后运行472.81秒，整批终态failed，code=RESEARCH_BATCH_RESOURCE_EXHAUSTED，10个子Run均失败且没有Result。已将相同公式拆成行情4项、财务4项、252日增长2项提交恢复。不能根据通用resource_exhausted断言具体是内存耗尽。见product-audit/runtime-resource-failure.json。

再次复现：industry 财务6项批次 batch_0c014db66cef4ab187fe 被接受后运行603.657458秒，以相同资源错误结束，6个子任务均失败。none 的4+4+2恢复批次已全部成功，因此保持公式、日期、TOP3000不变，将该行业组同样拆为当前财务4项和252日增长2项。新请求与旧失败分别留档，失败不计作负收益证据。

新增入口差异：收入增长industry的2项Strategy Sweep（20/50只、20日调仓，252日历史）在admission被RESEARCH_BATCH_EXCEEDS_WORKER_CAPACITY拒绝；保持公式、日期、股票池和参数，改为两个单ResearchRun均被接受并成功完成。它们是当前不同执行入口的真实容量差异，不是缩小Universe。20只/50只的净收益分别约-22.72%/-5.56%，计算成功不等于收益达标。请求留档为`submissions/r9-revenue-growth-*.json`。

2026-09-10再次核实：QS19收入增长none与QS18效率变化的两个2项Strategy Sweep都被同一容量错误拒绝。保持公式、2025-09-10至2026-09-09、TOP3000、none和10/20只、20日调仓，分别改为单ResearchRun。收入增长两个任务约100秒成功；效率变化两个任务分别61.58秒、56.07秒后失败，公开原因为`Research execution exceeded its resource limit.`，均只有252日预热及4/242研究日已提交，没有Result。未将失败尝试计为收益不佳，也不再原样重提。完整请求、Run与状态见[四项恢复证据](../round21-capacity-recovery.json)。

真实[失败页](https://thesistrace.com/research-runs/run_c17b5a72dc0d483da801)同时保留冻结条件、失败原因、运行时间与Create a draft入口；[原始截图](../screenshots/07-round21-resource-failure.jpg)可见错误只有通用资源限制句，没有预算、使用量、具体执行边界或维持研究条件的恢复指引。应在不泄露内部路径、身份或数据的前提下返回受控资源诊断，让研究者知道原条件是否可执行；复制草稿本身不能解答这一点。

诊断边界：公开MCP/UI没有child_peak_rss_bytes、执行预算或cgroup证据。只读当前`research_run/execution.py`可见多条路径可归入相同公开资源错误，因此不据此断言是容器OOM或某个公式节点。当前`research_batch/planning.py`对同Alpha策略扫描使用共享Alpha状态和最大持仓数，移除相同Alpha的另一个策略项不必降低主要估算；未盲目重复试探。已保留实际失败复现，未完成最小运行环境复现或根因修复，未修改服务容量与产品代码。
