# 04 — 分页读取 ResearchRun 语义结果

**What to build:** 让 Research Agent 通过一个有界的 `get_research_run_result` Tool 分 section 读取成功 ResearchRun 的产品语义结果，既能获得完整 Factor/Strategy 含义，也不会把大时间序列、positions 或底层 Result Bundle 一次性塞入模型上下文。

**Blocked by:** 03 — 提交并轮询 ResearchRun

**Status:** complete

- [x] 发布要求 `research:read` 的 `get_research_run_result`，并支持 `factor`、`strategy_summary`、`strategy_observations`、`terminal_strategy_state`、`terminal_positions`、`provenance` 六个显式 section。
- [x] section 输入使用 discriminated Schema；仅 collection section 接受 cursor/limit，不相关字段在边界被拒绝而非忽略。
- [x] Factor section 返回产品可见的 horizon、coverage、单位与 missing-value 语义；Strategy summary 返回产品可见指标、benchmark identity 和比较结果。
- [x] Strategy observations 按 session 升序分页，terminal positions 按 instrument 确定性顺序分页；默认 20、最大 50，cursor opaque 且绑定 run、section、order 和过滤上下文。
- [x] terminal Strategy state 与 positions 分离，紧凑状态读取不会携带无界 positions；分页遍历无重复、无缺口，并稳定重放 immutable Result。
- [x] provenance 足以解释 authoring input、数据/执行语义和结果来源，但不提供 Data Generation 选择能力，也不暴露 manifest、partition layout、RustFS key、checkpoint、attempt、lease、恢复状态、SQL 或路径。
- [x] Result 不可用、section 与 research kind 不兼容、cursor 错误、not found、超出响应上限和内部读取失败均返回稳定结构，绝不截断 JSON 或静默丢字段。
- [x] 使用真实成功 Factor 与 Strategy Result 验证全部 section、超过 50 条 observations/positions 的分页、重启后读取和独立语义重算/有限值不变量。
- [x] module interface、Capability Registry 和 stdio 协议的相关契约及 acceptance 测试通过，输出大小与失败诊断可自动判定。

## Comments

- 完整标准门禁：677 Python tests、TypeScript typecheck、63 frontend tests。
- 隔离集成运行 `20260826t150104z-59182-ef13378a`：290 passed、7 deselected；数据库重启、RustFS Factor、RustFS Strategy、RustFS batch cancel、PostgreSQL batch、PostgreSQL Strategy 六个阶段全部通过，cleanup status 0。
- Standards 与 Spec 最终复审均 clean；选择性读取由真实 PostgreSQL/RustFS `GetObject` 证据验证。
