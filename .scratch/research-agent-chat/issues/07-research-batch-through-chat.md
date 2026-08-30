# 07 — Research Batch through Chat

**What to build:** 让 Researcher 在 Chat 中要求比较多个 Alpha 或 Strategy 配置时，Mastra 使用同一个动态 MCP Tool 集提交并监控 Research Batch，通过 A2UI 展示有序进度和 Child ResearchRun 结果；Agent Host 不增加 Batch 专用 Planner、聚合结果或取消路径。

**Blocked by:** 06 — Validated A2UI research surfaces

**Status:** complete

## Implementation Plan

1. Reuse the existing authenticated dynamic MCP discovery, bounded Mastra
   execution, durable Messages, and validated A2UI catalog. Clarify Batch
   semantics in the Agent instructions: preserve caller request/item identity,
   follow tool polling guidance, and explain each ordinary Child ResearchRun
   rather than inventing a Batch Result. Do not add a Host Batch planner,
   watcher, command builder, cancellation path, or new display protocol.
2. Add deterministic Fake Model trajectories for natural-language Factor
   comparison and Strategy Sweep. Share the already-used transcript, scope,
   and metric-reading helpers with the single-run Fake where they genuinely
   overlap. Commands come only from the Fake Model; production Host stays
   schema-agnostic. The current Batch MCP schema does not accept `folder_id`:
   retain Core's common-folder admission behavior instead of inventing an
   unsupported argument or coupling Chat to Research organization.
3. Compose ordered Batch progress and child comparisons from the existing
   Text, Table, Provenance, and Navigation catalog. Display only authoritative
   IDs, status, available result metrics, and child routes. Distinguish partial
   failure, unavailable results, and still-running work without fabricating
   metrics or mutating a historical surface.
4. Cover Fake trajectories, discovery absence, clarification, stable replay,
   structured rejection, transient/disconnected MCP, bounded polling, child
   failures, and paginated results at their lowest reliable test seam. Reuse
   Core's real admission/cardinality/duplicate-key/ownership coverage; exercise
   real PostgreSQL persistence and the complete Caddy/MCP/Core/Batch Worker/
   RustFS path for both Batch kinds with deterministic Fixture Data.
5. Verify in a real browser that ordered comparisons, child navigation,
   refresh/replay, and Chat rename/deletion preserve independent Batch/Run/
   Result facts. Run affected regression suites and production-image checks,
   obtain independent Standards and Spec reviews of one staged patch, close
   findings and re-review, then update this tracker and commit Issue 07 alone.

- [x] Scripted Fake Model 轨迹把一个自然语言比较请求转为当前 MCP Schema 支持的 Factor Evaluation Batch 或 Strategy Sweep，而不是让浏览器构造 Batch Command。
- [x] Agent 可调用 Discovery 返回的 Batch Submit、List 和 Detail Tools，并通过 Child ResearchRun Tools 读取各 Item Result；Host 不硬编码 Tool 名称、Batch Item Schema 或 Tool 顺序。
- [x] Agent 根据对话和 MCP Context 选择共同 Folder、日期、Universe、Neutralization、Alpha 及 Strategy 参数；缺失的关键比较意图由模型决定是否追问。
- [x] Batch Admission 的 Request ID 与每个 Item Key 在重试、响应丢失和同一 Agent Run 内保持稳定；重复提交重放同一 Batch，不产生重复 Child ResearchRun。
- [x] Agent 根据 Tool Guidance 自主轮询 Batch 及所需 Child Runs，并能解释 Queued、Running、Partial、Succeeded、Failed 和结构化 Admission Rejection；Host 不创建 Batch Watcher 或 Synthetic Batch Result。
- [x] A2UI Batch Surface 展示 Batch ID、比较目标、有序 Item、进度、状态、关键结果和前往各权威 ResearchRun 的 Navigation，不显示 Manifest、Object Key、Checkpoint 或内部 Worker 状态。
- [x] Built-in Agent 的 OAuth Grant 不包含 Research Cancel Scope，因此 Batch Cancel Tool 不可发现；页面没有 Batch Cancel 或 Confirm Action，伪造调用仍由 Core 拒绝。
- [x] Chat Session 与 Batch 保持独立；删除或重命名 Chat 不改变 Batch、Child ResearchRun 或 Result，Core 状态变化也不改写历史 Message。
- [x] 使用真实 PostgreSQL、RustFS、Batch Research Worker 与 Fixture Data 验证 Factor Batch 和 Strategy Sweep 从 Admission 到终态，并断言顺序、Child Identity、Result 与 Existing Core Invariants。
- [x] 覆盖边界 Cardinality、Duplicate Item Key、Admission Rejection、Partial Child Failure、MCP Disconnect、Agent Run Bound、Idempotent Replay 和 Result Pagination；测试不逐字断言模型输出。
- [x] 完成后可从一个真实浏览器 Session 演示“比较多个 Alpha”到 Batch 结果解释的闭环，且实现只新增通用 Agent/MCP/A2UI 组合，不复制 Core Batch 业务规则。

## Verification and Review

- Standards and Spec independently reviewed staged patch
  `59e81e06e4428c749cb1dae676d9208a1660032ada3c2f64a30fadb14875df50`
  from fixed base `8b5f21a3da34082ddb0d98fa1c4b8df7d0bd3f33`;
  both reported zero findings before this tracker-only completion update.
- Deterministic baseline: Ruff, Python `917 passed`, Agent `258 passed`,
  Auth `163 passed`, Web `156 passed`, and both Agent/Web typechecks.
  The 22 Batch model cases cover both kinds, partial/failed/active states,
  admission rejection, discovery absence, exact effect replay, nested JSONB
  key normalization, malformed facts, and bounded opaque pagination.
- Full isolated integration run `20260830t202156z-33321-d548a3c7` passed
  Core `370` cases plus all `6` explicit PostgreSQL/RustFS restart cases.
  This includes one/twenty-item boundaries, duplicate keys, atomic admission,
  concurrent replay, deterministic child failure, independent ownership,
  shared-generation computation equivalence, MCP pagination, and denied
  cancellation. Auth `89` and final Agent PostgreSQL `34` cases also passed.
- Production-image browser run `20260830t202811z-45773-52f3c16f` passed
  all `6` selected scenarios. Both Batch kinds reached real Worker terminal
  Results; ordered item keys and child identities matched Core. A paused test
  Batch Worker proved a completed Agent Turn does not stop queued Core work.
  Lost admission response replay left one receipt, one Batch, and two children.
- Browser assertions prove no direct browser Core mutation, authoritative
  child navigation, A2UI refresh/replay, shared immutable Data Generation,
  built-in Batch Research folder, and unchanged Batch/Run/Result snapshots
  after Chat rename/deletion. Desktop/narrow table evidence is saved under
  that run's `evidence/playwright-report/` directory. Related existing A2UI
  running-state, large-table, and single Strategy regression scenarios pass.
- An initial diagnostic image run exposed the fixture's incorrect zero-based
  ordinal assumption. It was stopped, Core's one-based contract was used
  directly, and the corrected image passed; the interrupted attempt is not
  counted as successful evidence. No compatibility translation was added.
- Production Web bundle remains `11` assets / `1,652,001` bytes total /
  `1,577,411` JavaScript bytes. `git diff --check` passed. Test containers,
  volumes, and runtime secrets were cleaned by their isolated harnesses.
