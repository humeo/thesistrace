# 06 — 查看每日信号证据和月年稳定性

**What to build:** 独立 Factor Evaluation 能在网页与 MCP 返回每日相关性、分组收益、样本覆盖及月年统计，让 Agent 直接核查信号证据。

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] Factor Evaluation Run 与其 Batch 实际保存 1/5/20 Session 的每日 IC、Rank IC、五组 Forward Return/组人数、有效/排除样本及必要覆盖分母，不尝试从摘要恢复每日值。
- [ ] 信号 t 的标签为 t+1 至 t+1+h 调整后 Open；超出所选研究末日明确 right_censored_by_research_period_end，即使更晚数据存在也不越界，返回实际评价范围和尾部未评价数量。
- [ ] 沿用 ties、合法空组、小样本和无法定义统计；Factor 不能为了填满五组拆散并列分数，也不能将不可用值填零。
- [ ] 全期和月/年汇总按信号日期聚合每日有效统计，IC/Rank IC 等日权，ICIR 使用既有样本标准差；跨月标签不再截断，不计算混合股票日期的一次相关性。
- [ ] 人工同序/反序截面 Rank IC 为 +1/−1，月统计可由返回每日值独立复核；五组收益和 Top-Bottom 明确不是扣费可执行策略收益。
- [ ] 新增有界结果 sections，按期限/信号日期查询，cursor 固定 Result、过滤及 Researcher，网页不把全矩阵下载后过滤；MCP 与网页显示一致。
- [ ] 当前 Factor Result 的摘要、每日证据及来源一致；缺失明细不能伪造空记录，不实现旧产物转换。
- [ ] 验证 Factor 模块及真实 Factor Run/Batch 发布、分页授权、统计视图交互；本票不需要先改策略账户或等待 Exposure。

## Notes

规格：每日 Factor、标签边界、时段统计及查询。

母规格：Agent Quant Research：信号评估、策略回测与前向追踪。遵循其当前合同与范围；每票直接交付当前合同，前端、MCP、验证随行为交付，不作为尾部补接工作。

## Comments

- 2026-09-12 最新执行约束：用户明确当前为开发阶段。本轮只实现单一当前合同，直接修改调用方与产物定义，不新增兼容分支、字段别名、旧合同读取适配、vXX 升级或版本迁移。先前所有存量转换、迁移备份/回滚/重复升级验收均撤回；其余产品功能和失败恢复验收保持。只操作新 worktree 与隔离测试资源，不删除或重置现有 dev/线上数据。严格按 01–14 串行：每票计划 → 实现 → 验证 → Standards 审查 → Spec 审查 → 修复复审 → tracker 更新 → 独立提交。

- 2026-09-12：用户确认 14 票拆分及阻塞关系，正式发布为 ready-for-agent；尚未开始实现。
