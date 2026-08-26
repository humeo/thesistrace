# 08 — 恢复和停止 DailyTrack

**What to build:** 让 Research Agent 可以对 blocked DailyTrack 执行可重放 Retry，并在具有独立危险权限时对 active 或 blocked DailyTrack 执行不可逆 Stop；所有竞争、失败和重连都由现有 Product State 决定。

**Blocked by:** 07 — 启动并查询 DailyTrack

**Status:** ready-for-agent

- [ ] 发布 `retry_daily_track` 与 `stop_daily_track`；Retry 要求 `tracking:execute`，Stop 要求 `tracking:stop`，两者都要求 durable `track_id` 与 caller-stable `request_id`。
- [ ] Retry 标记 effectful、idempotent、non-destructive、closed-world，只允许 blocked 状态，并返回同一个 `track_id`、权威 action outcome、replay 标记与轮询建议。
- [ ] Stop 标记 effectful、idempotent、destructive、closed-world，只允许 current active 或 blocked 状态，并保持 Stop 不可逆。
- [ ] 默认 `local_operator` discovery 包含 Retry 但不包含 Stop；显式本地授权或 OAuth `tracking:stop` grant 才能发现和调用 Stop。
- [ ] 服务端不接受 confirmation token；Host 是否弹出确认不影响 scope、resource state、idempotency 和现有 DailyTrack invariant 的独立检查。
- [ ] 覆盖 Retry/Stop 的所有合法与非法生命周期、容量释放、Retry 与 Worker claim 竞争、Stop 与 publication/claim 竞争、重复调用、相同 identifier 的 fingerprint conflict 和进程重启。
- [ ] 未授权、not found、state conflict 与临时失败不产生隐藏状态转移；成功和失败均可通过 `get_daily_track` 读取权威结果。
- [ ] 使用真实数据库、Tracking Worker 与两个 MCP transport 完成 concurrency、idempotency、crash recovery 和 scope acceptance 测试，禁止 arbitrary sleep。
