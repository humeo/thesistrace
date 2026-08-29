# 12 — 证明确定性 Agent 任务轨迹

**What to build:** 用 Fake Model/Scripted Response 驱动公开 MCP 合同，证明一个 Agent 能可靠选择正确 Tool、修正可修正输入、提交和轮询 durable work、分页读取结果，并在授权、幂等和临时失败场景中采取正确恢复动作，而不依赖真实模型的随机输出。

**Blocked by:** 11 — 闭合固定入口边界与精确 V1 合同

**Status:** completed

- [x] 建立完全确定性的 Agent trajectory harness，固定模型响应、时间、UUID、随机种子、Fixture data 和 transport 行为，不访问公网或真实模型。
- [x] 覆盖 context discovery、Alpha Catalog lookup、Formula Diagnostics 修正、Factor/Strategy submission、`retry_after_seconds` polling、终态判断和多页 Result inspection。
- [x] 覆盖 Research Batch admission、ordered item monitoring、child ResearchRun Result 读取和授权 Batch cancellation。
- [x] 覆盖 DailyTrack start、history/detail、blocked-only Retry、result paging，以及有/无 `tracking:stop` 时的 Stop selection 与拒绝。
- [x] 覆盖 transport 失败后的相同 `request_id` 重试、原 outcome replay、changed fingerprint conflict、HTTP token expiry/refresh后的 rediscovery、临时失败 backoff 和永久错误不重试。
- [x] 断言任务完成、durable IDs、Product State、Result sections、权限、调用成本与最大轮询次数等不变量，不断言模型逐字输出或私有 handler 调用次数。
- [x] 所有轮询都有明确 timeout/最大步数且不使用 arbitrary sleep；失败保存 trajectory、Tool envelopes、trace IDs、随机种子与经净化的服务状态。
- [x] Fake Model 轨迹与真实数据库/Worker 的工程测试保持分离；概率性真实模型表现不进入确定性发布门禁。
- [x] 全部 trajectory 测试可由现有本地测试入口重复运行并稳定通过，无 flaky retry 掩盖失败。
