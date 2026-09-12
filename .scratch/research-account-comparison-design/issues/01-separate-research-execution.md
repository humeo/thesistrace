# 01 — 让信号评估与策略执行真正分开

**What to build:** 网页和 MCP 分别运行 Factor Evaluation 或 Strategy Backtest；策略及其 DailyTrack 不再等待、计算或保存隐式 Factor 评价。

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] Research Kind 决定实际执行计划、Chunk 完成条件、Result 与续算状态；Factor Run 只生成评价，Strategy Run 保留必要 Signal 并生成账户，不提供 include_factor 或空的另一类结果占位。
- [ ] 没有 Factor 摘要、未来标签或标签成熟状态的成功 Strategy Result 可以创建并推进 DailyTrack；本票仍使用当前账户时点，末日合同由 03 修改。
- [ ] 普通 Run 与现有两类 Research Batch 同时遵守分离；兼容请求共享必要 Data/Alpha，仅实际 Factor Evaluation 请求执行 Factor，恢复仍以完整任务为单位。
- [ ] 网页的输入、运行详情、结果分区以及 HTTP/MCP schema 按 kind 一致；Factor 拒绝账户参数，新的 Strategy 与 Track 不展示 IC/Factor 分区。
- [ ] 当前 Strategy Result 只保存策略账户及必要 Signal 产物；读取严格按 kind 区分，不创建 Factor 占位或旧合同读取适配。
- [ ] 在公开计算边界使用禁止标签计算的测试依赖，证明 Strategy Run、Strategy Batch 与 Track 能完成；独立 Factor Run 仍按现有 1/5/20 Session 口径运行。
- [ ] 真实 Worker、PostgreSQL、RustFS 验证按 kind 发布与失败恢复，运行受影响网页及 MCP 成功/拒绝检查。
- [ ] 所有相关调用方使用单一当前合同，不为中间状态添加旧版本执行分支；形成一次可验收的完整交付并独立提交。

## Notes

规格：能力分离、按 kind 执行/共享/恢复、旧 Factor 证据保留。

母规格：Agent Quant Research：信号评估、策略回测与前向追踪。遵循其当前合同与范围；每票直接交付当前合同，前端、MCP、验证随行为交付，不作为尾部补接工作。

## Comments

- 2026-09-12 最新执行约束：用户明确当前为开发阶段。本轮只实现单一当前合同，直接修改调用方与产物定义，不新增兼容分支、字段别名、旧合同读取适配、vXX 升级或版本迁移。先前所有存量转换、迁移备份/回滚/重复升级验收均撤回；其余产品功能和失败恢复验收保持。只操作新 worktree 与隔离测试资源，不删除或重置现有 dev/线上数据。严格按 01–14 串行：每票计划 → 实现 → 验证 → Standards 审查 → Spec 审查 → 修复复审 → tracker 更新 → 独立提交。

- 2026-09-12：用户确认 14 票拆分及阻塞关系，正式发布为 ready-for-agent；尚未开始实现。
