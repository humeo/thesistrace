# 01 实施计划

Status: in-progress

基线：main@2daf193；worktree：codex/research-capabilities。先完成本票再开始 02。

## 已核对问题

Kernel Run、Research Chunk 和 Batch 都无条件计算 Factor；Strategy Result 强制 factor_summary，DailyTrack Checkpoint 和恢复继续依赖 Factor 历史。输入虽已区分 kind，执行尚未分开。

## 实施步骤

1. 在公开 Kernel Run、Columnar/Chunk、Batch 和 Track 边界补回归：禁止未来标签计算时 Strategy 仍能完成；Factor 仍有正常统计。
2. 拆开必要 Alpha 与可选 Factor 的计算及续算合同。仅 Factor 请求构造标签/汇总；策略共享 Alpha 时不携带 Factor 状态。沿用已有模块，不新增通用 pipeline。
3. Strategy Result、Tracking Origin/Checkpoint 及发布校验移除 Factor 依赖；按 kind 保留严格 typed 查询与失败状态，不做旧版本读取适配。
4. HTTP/MCP 及网页只为 Factor 展示 Factor section，调整实际 schema、fixture 与文案；保留其他账户时点，末日行为留给 03。
5. 运行受影响 Kernel 和契约测试、类型/lint、真实 Run/Batch/Track 发布与恢复验证及网页/MCP 检查。
6. 顺序进行 Standards 和 Spec code review，记录发现、修复与复审结论；全部验收有证据后更新本票并独立提交。

## 验证重点

- 不只是隐藏摘要：无标签构造、无标签成熟状态、无隐式 Factor 产物。
- Factor 路径结果保持，Strategy NAV/ledger 在本票保持。
- Run、Batch 和冷恢复后的 Track 都遵守同一 kind。
- 数据库/Publication 结论用隔离真实依赖证明；不触碰 dev 数据。

## 证据

尚未运行产品测试。
