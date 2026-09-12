# 独立方案 A：最小 Interface，以 ResearchRun Module 接受并读取有界验证集合

状态：设计选项，未实施。阅读 codebase-design、DESIGN-IT-TWICE、DEEPENING、CONTEXT 和指定 ADR 后提出。仅覆盖本金、因子诊断、来源关系及跨日期／成本验证；不建立自动选策略或通用工作流平台。

## 核心判断

保留现有 Research Batch 定义与共享计算 Implementation。在 ResearchRun Module 内增加一个私有 validation Implementation 文件和两张持久表，提供 Research Validation 这个拟新增领域概念：一份明确变化条件、原子接受的有限 ResearchRun 集合，其成员都在接受时冻结同一个当前 Data Generation。每个成员仍由普通 Research Worker 执行和发布自己的 Result Bundle。

只增加三个概念入口：submit_research_validation、get_research_validation、cancel_research_validation。因子来源和账户参数同时进入已有 submit_research_run 的扩展；诊断继续由已有 get_research_run_result 的 factor 部分返回。不增加因子转策略工具、通用 compare 任意 ID 工具、计划 token、历史数据选择工具，也不把多个单 Run 的持久编排推给 Agent。

三个入口不是把 JSON 大袋子压到一个 run 方法：每个都对应一项完整授权动作，输入是闭合类型，行为、上限、错误和重放语义明确。MCP 与网页 HTTP 是跨同一 Seam 的两个 Adapter。

## Interface 草案

```python
class AccountInput:
    initial_cash_cny: DecimalCny   # 正数、有限、精度及上下限在 Authoring constraints 公布
    costs: SupportedCostInput     # 第一版可只开放 extra_cost_bps；不是任意键值字典

class SourceInput:
    # 恰好一种来源；既有 Run 成功且归当前 Researcher
    source_run_id: RunId | None
    authored_alpha: AuthoredAlpha | None

class ValidationCase:
    item_key: str
    start_date: NaturalDate
    end_date: NaturalDate
    account: AccountInput
    holdings_count: HoldingsCount
    rebalance_every_sessions: RebalanceInterval

class SubmitValidation:
    request_id: RequestId
    folder_id: FolderId
    source: SourceInput
    universe: ResearchUniverse
    neutralization: ResearchNeutralization
    varying: tuple[Literal['research_period', 'initial_cash', 'costs',
                          'holdings_count', 'rebalance_interval'], ...]
    cases: list[ValidationCase]   # 初版 1..20，显式列表，没有笛卡尔积

admit_validation(researcher, SubmitValidation) -> Accepted | Rejected
get_validation(researcher, validation_id) -> ValidationView | NotFound
cancel_validation(researcher, validation_id, request_id) -> CancelOutcome | NotFound
```

`SourceInput` 实际需要 discriminated union；示意 Python 两个 optional 不能成为最终协议。来源 Factor 时继承 Alpha、Universe、中性化；不能同时给冲突公式。希望改 Universe／中性化时第一版要求转为明确 authored 输入，来源关系记录为 authoring_reference，不能伪装完全相同研究条件。更严格的首版可只接受 source_run_id，已有提交方式承担全新研究。

新建研究一律使用一次接受操作取得的当前 Dataset Head，不接受 data_generation_id。Source 的 Generation 是历史证据身份，不是重算权限。Source 与新研究的数据或计算版本不同，返回显式 source_condition_differences；用户不能把它理解成相同条件因果对照。每个 Strategy Result 已有 Factor 结果，应使用本次 Run 内的 Factor 结果解释对应 Strategy；不需要额外创建隐藏 Factor Run 或误用旧来源分数。

例：Agent 以 Factor Result F 为来源，显式提交三行日期和 100000 CNY、相同费用／H10／R5，声明 varying=['research_period']。返回 validation_id、三条真实 run_id、完整冻结条件、数据日期与预计工作范围。读取返回三行状态和结果，包含实际日期／样本数／费用／现金比例／指标以及来源差异。Agent 不用重算 Sharpe，不用自己记哪条失败、哪条重试、哪条被删除。

## 必须固定的行为

- 所有 case 原子接受或全部拒绝；任一日期、Warm-up、配额、参数不合法，返回 item_key + code + field，无半组 Run。容量检查分别按普通 Run 实际执行路径，不调用 Strategy Sweep 的共享内存容量检查。
- 在准入 Implementation 中只解析一次 Dataset Admission Snapshot，对所有 case 使用同一 snapshot；事务接受时验证其仍可被 retain，各 Run 各自保留 Generation。刷新竞态不能让组内 Generation 混杂。若已回收或无法 retain，整体可重试拒绝；不能中途改成新 Head。
- source 的 Research Ownership、成功状态、输入和结果身份在同一受保护读取／接受流程中核验，避免删除竞态。不得向其他 Researcher 暴露来源存在性。
- source 关系存一个最小冻结快照：原 Run 身份、Kind、公式及口径、原研究条件、数据／计算身份、来源 Result 身份。名称是显示信息，不作匹配键。读比较所需的原指标若决定保留，必须标注为被捕获的来源证据，而不是新结果。
- case 的本金、费用等实际生效值进入 ImmutableRunInput、Result provenance、resume binding。不是 result 页展示参数。DailyTrack 必须继承该 Run 的 Initial Cash 和费用；Batch-Incremental Equivalence 要涵盖非默认本金。
- expected varying 与实际差异由 Module 确定性核对，未声明变化被拒绝。日期变化导致样本长度不同是已知比较限制，不把累计收益排序解释为策略优劣。
- 每一 case 是独立全现金起点。continuous_window 和 walk_forward 不是这个 Interface 的 mode；不把已有账户切片伪装重算，也不提前引入训练／选择协议。
- caller-stable request_id + canonical resolved request fingerprint；传入相同 request_id 的同请求重放返回原身份，异请求冲突。重连后按资源 ID 读取，与 MCP session 无关。
- cancel 是独立 authority；取消未结束成员，保留已完成 Result。普通 Run 的取消语义保持。首版需新增 Run 内部有界批量取消 Implementation，在同一事务持久化取消意图和幂等收据，不能在 Adapter 中逐项循环并声称原子。
- get 返回最多 20 行摘要和比较事实，不包含全历史逐股数据。日级明细继续使用绑定单个不可变 Result 的已有分页 Interface。读取不触发回测，不更改 Result。
- queued/running/failed/cancelled/deleted/not_available 与 null 指标保持不同；validation 状态从持久成员结果确定性投影，取消意图单独持久化，不另建重复 Worker 状态机。

## 诊断采用固定紧凑结果，减少 Interface 面积

在 factor 现有 horizon 1/5/20 中扩展 quantile statistics（逐组有效日、样本量统计）、paired top-bottom 样本与 mean；新增固定 TopN=[10,20,100] 标签统计，声明排序和 missing-label 规则。固定三个 N 可以消除一整套诊断配置和临时运算工具。代价是不能按任意 N 查询；未来需要任意 N 时显式新研究，不能读取时临时计算。

TopN 必须先按 Final Alpha Cross-Section 固定候选，再统计其中成熟有效 Labels，不能把 missing label 股票悄悄替换为更低名次；返回 requested_n、selected_count、valid_label_count 及有效日。Quantile 有自己既定并列语义，不把 Strategy Candidate Order 混作 quantile 分组。统计就是 Forward Return，不是账户曲线或已实现交易归因。

第一版不承诺完整交易历史 ledger。若要它，必须另行决定 ADR-0099 的 transient execution detail 保留原则、存储成本与生命周期。可以先用已有 cash/holdings/fee observations 和本次 Factor 对照提供诚实的诊断事实。

## Module / Seam / Adapter 与依赖

- 外部 Seam 位于 ResearchRun Module 的价值类型 Interface。Research Agent registry 和 HTTP route 只做身份、解析和传输；不得复制来源展开、差异识别、准入或指标计算。
- 在现有 research_run 内分拆私有 validation.py（计划解析／准入／投影）和 models 中闭合类型，避免把现有 4000 多行 service.py 再堆满。不要为了 3 个方法另造独立通用 orchestration Module。
- In-process：Alpha compile、Research Period 解析、成本合法性、差异比较、Factor 统计，复用确定性 Implementation；不加 Adapter。
- Local-substitutable：PostgreSQL、Publication/RustFS、DatasetLifecycle，复用项目注入能力与真实依赖集成测试。Validation 不访问 Tushare 或模型；不存在新增 true-external Adapter。
- HTTP 和 MCP 是已实际存在的两个入口 Adapter；新增能力沿用 registry 以闭合模型公开输入／输出。不要额外引入可插拔 Research Executor port；普通 Worker 就是当前 Implementation。
- 来源读取先做 Researcher 授权。持久取消和组接受由 Module 事务负责，普通 ResearchRun 保持执行权；没有远程循环编排。

## 删除与 GC

来源删除不级联删除验证和衍生 Run。Validation 接受时冻结最小来源快照，后续源链接返回 deleted；不为了“以后可能再跑”永久 retain 源 Data Generation。来源 Result hash 作为出处身份不自动产生 Publication retention。这样不会违反临时 Data Generation 决策。

成员被显式删除后保留 item_key/run_id/status/input-differences 的 tombstone；该行收益不可读就返回 deleted/null，不假装比较摘要仍是完整报告。复用现有 dependent history hook 在同事务保存成员删除状态，允许 Publication 正常释放；不隐藏保留完整被删除 Result。现有 DailyTrack 对 seed Result 的独立引用继续按原规则处理。

如果产品希望删除 Run 后比较表仍保留完整收益，那就是新的 Result 引用与保留决定，须明确告知用户并扩展 GC 引用检查；不在首版默认引入。

## Depth / Locality / deletion test

Depth 高在：一次请求得到完整、同 Generation、独立账户的可恢复有限验证；一次读取得到有来源、可比性和缺失状态的对照。调用方只学显式 case 和资源 ID，不承担事务、幂等、任务跟踪和比较规则。

Locality 高在 ResearchRun：账户接受、来源冻结、真实执行输入和 Result 事实仍在同一个 Module；比较投影只读其拥有的证据。Research Batch 的共享计算及恢复不受跨日期需求污染。

Deletion test：若删除 validation Implementation，原子多 Run 接受、同 Generation 校验、来源快照、幂等成员关联、取消意图和比较规则会散回网页与 Agent，所以它赚到了深度。若仅做一个遍历 `admit()` 的薄 wrapper，则删除后复杂性只剩循环，说明没有 Depth；这个方案明确禁止那种实现。

硬代价：新增一个持久领域对象、两张表和三种动作；普通 Worker 路径不能共享同 Alpha 多 case 计算，费用／本金扫参比现有 Strategy Sweep 可能慢。选择该方案是以可理解性及一致性换取首版吞吐，不宣称共享计算。将来仅在实际性能证据要求时按相同研究条件内部划分可共享组，公开 Interface 不变，但不要现在实现多层调度。

## 对上一份 MCP 草案的明确纠正

1. `strategy_comparison` 不能作为新批次名称：CONTEXT 的 Strategy Comparison 已专指 CSI300 基准对照。
2. Research Batch 目前统一 Research Period；把 case 日期加进去不是新增 enum 就完成，而是改领域契约及 shared Alpha/Factor Implementation。本方案不改这个含义。
3. `preflight` 不能声称冻结数据同时又不创建 retention 或准入资源。最小方案首版不增加独立 preflight；现有 context/diagnose 用于发现，真正 submit 做完整结构化准入。未来预检只能返回 observed Generation 和估计，不能承诺提交使用那一份。
4. 来源新研究不开放选择历史 Data Generation。使用当前 Head 时显式记录 source差异，不能提供 `select new version`／`replay original version` 开关却违背 ADR-0154。
5. 完整 ledger 新 section 与 ADR-0099 保存原则冲突，必须单独决策，不能当作纯传输扩展。

## 当前源码锚点

- CONTEXT.md:158 — Research Batch 同 Period / Universe / neutralization / Generation。
- CONTEXT.md:192 — Result Bundle 唯一固定研究结果。
- CONTEXT.md:304 — Initial Cash 是账户起点。
- CONTEXT.md:505 — Strategy Comparison 是策略相对 CSI300。
- CONTEXT.md:543 — Data Generation 不是 user-selectable history。
- docs/adr/0151-keep-research-authority-inside-a-module-first-core.md:3 — Core Modules 权威。
- docs/adr/0190-freeze-data-generation-at-researchrun-admission.md:3 — 准入冻结并 retain。
- docs/adr/0154-use-a-mounted-current-dataset-head-and-temporary-data-generations.md:3 — 历史 Generation 临时、可 GC。
- docs/adr/0216-share-bounded-batch-calculation-and-recover-complete-tasks.md:3 — 共享计算和完整任务恢复。
- docs/adr/0220-expose-research-agent-access-through-a-native-core-mcp-adapter.md:3 — 同 Module Interface、bounded semantic results。
- docs/adr/0222-keep-research-agent-execution-stateless-and-resource-addressed.md:3 — request identity / durable IDs。
- docs/adr/0099-make-one-immutable-result-bundle-the-research-run-truth.md:3 — transient execution detail 不保留。
- docs/adr/0104-continue-dailytrack-from-one-fixed-origin.md:3；docs/adr/0108-require-canonical-exact-batch-incremental-equivalence.md:3 — 固定起点／精确等价。
- apps/core/src/thesistrace/research_run/models.py:152 — 当前 Run 输入；:184 仅 H/R；:287 ImmutableRunInput；:490 五分组只有均值；:509 只有整体覆盖。
- apps/core/src/thesistrace/research_run/service.py:911 — prepare_child_admission 可注入同一 DatasetAdmissionSnapshot。
- apps/core/src/thesistrace/research_run/service.py:950 — 事务内准入，ordinary/research_batch owner；:1020 每 Run retention。
- apps/core/src/thesistrace/research_run/service.py:1108 — 逐次普通 admit 各取 current Head，故不能让 Agent 循环保证同 Generation。
- apps/core/src/thesistrace/research_run/service.py:1680 — 删除；:1728 dependent history hook；:1738 Publication 引用／释放。
- apps/core/src/thesistrace/research_run/service.py:2894 — 固定本金及固定成本执行检查；:3944 接受时写固定常量，需要一起改。
- apps/core/src/thesistrace/research_batch/models.py:37 — 只有两种 Batch Kind；:52 上限20；:55 共享日期；:95 sweep item 只有 H/R。
- apps/core/src/thesistrace/research_batch/service.py:702 — 同 snapshot 准入模式；:723 shared capacity；:800 transaction children；:835 Batch retention。
- apps/core/src/thesistrace/research_authoring/models.py:28 — 统一约束可扩展本金／费用／validation上限。
- apps/core/src/thesistrace/research_agent/registry.py:148 — Run Reader Interface；:264 注入的 Modules；:598 batch Tool；:627 run Tool。

## 最小验证

通过同一 Interface 验证：相同 request重放、异请求冲突、部分无效整体拒绝、刷新竞态同 Generation、删除竞态／跨 Researcher、不同本金和费用真实进入账户、来源删除及成员删除、取消与完成竞态、零有效组／TopN缺失标签。PostgreSQL/Publication/Dataset retention 用真实依赖；Factor/账本采用可独立计算小 Fixture；MCP和HTTP验证相同解析与权威返回。不增加只检查委托调用次数的测试，不要求真实模型才能通过。
