# 07 — 启动并查询 DailyTrack

**What to build:** 让 Research Agent 从一个成功的 Strategy Backtest 启动 DailyTrack，获得 durable `track_id`，并通过稳定分页历史与紧凑详情监控其来源、状态、进度、阻塞信息和可用结果，而不能绕过当前 tracking invariants。

**Blocked by:** 03 — 提交并轮询 ResearchRun

**Status:** complete

- [x] 发布 `list_daily_tracks`、`get_daily_track`、`start_daily_track`；读取要求 `tracking:read`，启动要求 `tracking:execute`。
- [x] 将 DailyTrack history 深化为真正的 seek-based module pagination，默认 20、最大 50、稳定 opaque cursor 和确定性 tie-break；MCP adapter 不允许全量读取后内存切片。
- [x] compact detail 返回 origin ResearchRun、lifecycle、progress、timing、block reason、Retry/Stop eligibility、结果可用 section 和轮询建议，不内嵌无界 observations/positions 或私有 checkpoint。
- [x] start 只接受 succeeded Strategy Backtest `run_id` 和 caller-stable `request_id`，并保持一条 origin run 只能有一条 DailyTrack、最多十条 non-stopped DailyTracks 等当前 Core invariants。
- [x] 非 Strategy origin、非 succeeded origin、重复 origin、容量已满和非法输入产生明确 admission rejection 或 state conflict，不创建部分资源。
- [x] 相同 start command 在并发、capacity race 和进程重启后返回同一 `track_id`；相同 `request_id` 的不同 fingerprint 返回 `IDEMPOTENCY_CONFLICT`。
- [x] MCP 断开不会停止 tracking；重连后可以从 durable `track_id` 继续查询，transport/session 不拥有执行状态。
- [x] 使用隔离的真实 PostgreSQL、RustFS、Research Worker 与 Tracking Worker 验证成功 activation、容量竞争、Worker progression、阻塞和重启恢复。
- [x] module pagination、Capability Registry、stdio/HTTP contract 与受影响 acceptance 门禁通过，且 V1 不出现 DailyTrack delete Tool。

## Comments

- 完整快速门禁：686 Python tests、TypeScript typecheck、63 frontend tests；`git diff --check` clean。
- 最终隔离集成运行 `20260826t202633z-68705-34880acd`：297 passed、7 deselected；数据库重启、RustFS Factor、RustFS Strategy、RustFS batch cancel、PostgreSQL batch、PostgreSQL Strategy 六个阶段全部通过并完成隔离资源清理。
- stdio 与 Streamable HTTP 均覆盖并发/重启幂等、changed fingerprint 无部分状态、真实数据库临时故障、Worker progression 与 blocked 投影；容量错误语义的最终真实验收 1 passed，Standards 与 Spec 最终复审均 clean。
