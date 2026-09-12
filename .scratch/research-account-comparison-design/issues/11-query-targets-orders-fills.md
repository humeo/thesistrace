# 11 — 查询可对账的目标、订单与成交

**What to build:** Researcher 与 Agent 能从回测和 Track 结果按日期、股票和事件关系追查目标、模拟订单及成交，独立对账现金和持仓变化。

**Blocked by:** 08 — 每日按共同条件加减仓

**Status:** ready-for-agent

- [ ] 同一 Strategy 核心将实际 Target Selection/Exposure 目标事件、Simulated Orders、Child Orders、Simulated Fills 及实际估值调整有界地纳入主计算/发布链；无更新日期不新增空事件。
- [ ] 逻辑事件键独立于 Chunk、Attempt、Retry 和数组下标；父目标、逻辑订单、子订单和成交可关联，不依赖特定配权算法才能记录。
- [ ] 证据包含决策/执行 Session、原因、执行股数、Raw Open/Notional、费用、Research Settlement、现金及 Adjusted Holding Units 变化；终端退市核销不伪装成交。
- [ ] 从期初现金、成交真实结算、费用与实际调整独立对账期末现金及两种数量坐标；原始成交名义金额不替代合成现金结算。
- [ ] 永久 Result 保留事件和必要终态；Track 只追加新增段、不复制全历史；后台 Retry 不重复发布，部分执行不作为完整结果可读。
- [ ] 网页和 MCP 新增有类型的分页 sections，使用支持的日期/股票/事件过滤及最大 50 条限制；cursor 固定 Researcher、来源执行、发布版本和过滤，后续 Refresh 不混页。
- [ ] Research Ownership 与 scope 防止越权，错误 cursor/过滤明确拒绝；旧未保存事件返回 not_recorded，真实零事件返回合法空集，不从摘要造交易。
- [ ] 真实依赖验证不可变发布、断线/Retry、过滤分页、跨账户拒绝和父子关系；独立人工账本覆盖调整单位及受阻订单，UI 可从目标追到相关模拟交易。
- [ ] 持久合同直接使用当前定义；不加入逐算子、全 Universe 评分或自然语言解释历史。

## Notes

规格：永久目标与交易证据、逻辑 ID、结算对账、权限分页。

母规格：Agent Quant Research：信号评估、策略回测与前向追踪。遵循其当前合同与范围；每票直接交付当前合同，前端、MCP、验证随行为交付，不作为尾部补接工作。

## Comments

- 2026-09-12 最新执行约束：用户明确当前为开发阶段。本轮只实现单一当前合同，直接修改调用方与产物定义，不新增兼容分支、字段别名、旧合同读取适配、vXX 升级或版本迁移。先前所有存量转换、迁移备份/回滚/重复升级验收均撤回；其余产品功能和失败恢复验收保持。只操作新 worktree 与隔离测试资源，不删除或重置现有 dev/线上数据。严格按 01–14 串行：每票计划 → 实现 → 验证 → Standards 审查 → Spec 审查 → 修复复审 → tracker 更新 → 独立提交。

- 2026-09-12：用户确认 14 票拆分及阻塞关系，正式发布为 ready-for-agent；尚未开始实现。
