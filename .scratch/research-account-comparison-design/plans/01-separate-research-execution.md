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

- Kernel 与长回测验收器最新整轮 346 项通过（kernel-final.log）；先前失败与修正保留在原始日志。Strategy 禁止标签构造回归已先失败再通过。Run/Batch/Track 禁止标签检查 11 项通过。
- Web：TypeScript 通过；ResearchRunsPage / DailyTracksPage 36 项通过。
- 长回测验收合同：29 项通过。只运行验收器测试，未运行完整性能基准。
- 真实依赖第一轮：385 通过、79 失败。实际根因包括 Strategy 发布筛选指标仍读取 Factor、Batch 私有产物强制未来标签周期；已修复。其余旧合同断言按实际新接口同步，其中 ownership 用例原先仍使用已不存在的游标分页，改用当前页码合同验证所有者隔离。第二轮及首次定向 E2E 又发现 Strategy SQL CHECK 强制 Rank IC 字段；直接修改当前 schema 后，第二轮已停止并正常回收。第三轮（首个失败即停）和第二次定向 E2E 正在运行，尚未达到验收通过；证据在 `.local/test-runs/issue-01/`。

## 审查

- Standards 初审无阻塞发现；追加复审发现 Tracking 禁止标签只 patch 定义模块，未拦截消费绑定。修正后正常 3 项通过，独立进程注入实际标签调用后 3 项预期失败（tracking-label-mutation.log）；复审已关闭，无新增发现。
- Spec：发现长回测验收器仍要求 Strategy Factor。已改为每种研究独立 Summary 一致性、Strategy 无 Factor 耗时/产物，并同步采集脚本与 fixture；29 项测试通过。最终完整差异复审已关闭，无新增发现。
- 票据仍在进行，不提前勾选验收或提交。

- 追加 schema 修复：Strategy key_metrics CHECK 只允许账户指标；既有迁移测试使用其原目标 SQL fixture，不改任何迁移代码、指纹或版本。Standards / Spec 追加复审均无新发现。

## 后续验收记录

- 最新网页类型检查通过；独立 Factor/Strategy/Track 的真实 E2E 1 项通过（e2e-second.log）。
- Strategy 筛选去除 Rank IC 入口；Factor 保留三周期。定向 Playwright 4 项通过（browser-filters-second.log），首次本机沙箱 MachPort 启动失败已记录；追加 Standards / Spec 复审无发现。
- Agent DailyTrack fixture 去除 Factor section，Scripted Model 24 项通过；Standards 复审无发现。
- 集成第三轮 237 通过后发现策略排序 fixture 仍写入 Rank IC；修正后相应 Standards 复审无发现。
- 第四轮 271 通过后，一次 Worker claim barrier 在释放后 30 秒超时。已增强该测试的超时输出与进程清理；未把它认定为运行时修复。独立用例 1+10 次通过（15–18 秒），带全部本模块前置用例 25 项通过（129 秒）；根因暂未复现，保留风险和证据。
- 使用同一保留的 TestRun 和原 integration 阶段，按 pytest last-failed 继续验证未通过项；随后才运行原有各依赖重启阶段。尚未宣称本票验收完成。

- 剩余集成首轮 65 通过、3 失败：冻结 Generation 的 Strategy Result 旧断言、HTTP MCP DailyTrack Factor 旧断言、容量 fixture 旧上限假设。前两修正后真实复验 2 项通过。容量测试当前 Auth 上限为 3，原先预置 8 条已经超限，现改为已有 1 条加 1 条预置，留 1 名额给 2 个并发请求；仍要求恰好一成功一拒绝，正在复验。Standards 追加复审无发现。

## 交付验收

- 最新容量真实用例 1 项通过（84.09 秒）；HTTP MCP 与冻结 Generation 用例上轮 2 项通过。Standards / Spec 追加复审均无 findings。
- 原有六项重启阶段全部通过：数据库提交恢复、RustFS Factor、RustFS Strategy、RustFS 取消清理、PostgreSQL Factor、PostgreSQL Strategy。`integration-remaining-third.log`，运行器退出 0 并清理该隔离项目。此前通过的主集成用例和本次修正复验构成分阶段证据，不冒称一轮全绿。
- 最终全部改动 Python 文件 Ruff 通过，diff 格式检查通过。未运行完整性能基准或 `pnpm check`。
- 一次 Worker barrier 超时仍为未复现诊断记录，不宣称因重跑通过而修复；已保留失败记录及超时输出/清理改进。后续独立重复和原模块前置场景通过，未发现与能力分离有关的可复现故障。
- 01 验收完成，独立提交；后续任务尚未实施。
