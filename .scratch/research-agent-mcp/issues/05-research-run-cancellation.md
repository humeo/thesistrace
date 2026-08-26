# 05 — 按独立权限取消 ResearchRun

**What to build:** 让被明确授予 `research:cancel` 的 Research Agent 可以通过 `cancel_research_run` 取消一个当前允许取消的 ResearchRun，同时让普通本地连接看不到该 Tool，并确保 Host 的确认界面永远不能替代服务端授权和 Product State 校验。

**Blocked by:** 03 — 提交并轮询 ResearchRun

**Status:** ready-for-agent

- [ ] 发布要求 `research:cancel` 的 `cancel_research_run`，输入包含 durable `run_id` 与 caller-stable `request_id`，输出包含同一资源的权威 action/lifecycle outcome。
- [ ] Tool 标记为 effectful、idempotent、destructive、closed-world；描述明确合法状态、不可忽略的副作用和轮询方式。
- [ ] 默认 `local_operator` discovery 不包含该 Tool；只有显式启动授权才可见并可调用，HTTP grant 缺少 `research:cancel` 时 discovery 与 invocation 均拒绝。
- [ ] 服务端只依据 authenticated principal、scope、资源状态、idempotency 与当前 ResearchRun invariants 授权；不接受 confirmation token，也不把 `destructiveHint` 当成人类确认凭据。
- [ ] 覆盖现有 ResearchRun module 所有合法取消状态、所有非法/终态冲突、取消与 Worker 领取/完成竞争，以及取消后的稳定查询结果。
- [ ] 相同 action command 在并发与重启后重放原 outcome；相同 `request_id` 搭配不同 run 或不同 command fingerprint 返回 `IDEMPOTENCY_CONFLICT`，不影响任一资源。
- [ ] 未授权、not found、state conflict 和临时失败均不改变 Product State，并返回可判定的结构化错误。
- [ ] 真实数据库、Worker 与两个 MCP transport 的权限、竞争、幂等和重启 acceptance 测试通过，无 arbitrary sleep 或模拟自有数据库。
