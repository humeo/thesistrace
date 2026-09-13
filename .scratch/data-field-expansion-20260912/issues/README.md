# 226 字段扩展：正式工单

**Status:** ready-for-agent

2026-09-12 已获用户确认，发布 8 张正式工单。01—06 已完成独立验收与串行复审；07—08 尚未开始。

母规格：[226 字段规格](../spec.md)。逐字段定义沿用该规格的权威附件；母规格没有修改或关闭。

## 最新执行约束

- 在从 main 创建并核实的新 worktree 中执行，严格顺序为 **01 → 02 → 03 → 04 → 05 → 06 → 07 → 08**，不并行实现或审查。
- 每票独立完成：**先记录 Plan → 实现 → 验收 → code review → 修复与复审 → tracker 更新 → 独立 git commit**，然后才开始下一票。只有证据满足完成条件时才标 complete。
- Blocked by 保留真实技术依赖；Execution order 是用户要求的额外串行调度门槛。即使技术上可独立开始，也不得跳过前票。
- 直接实现一套当前合同，不做兼容、版本迁移、vXX 升级链或双读双写。用户最新要求覆盖旧规格的有条件迁移提议；既有原始数据、字段语义、研究结果和被引用数据仍保留，不能自动清库。
- 中间工单在隔离环境验收，最终统一硬切；Data 页仍维持四个顶层区块。当前发布工单不包含执行采集、代码修改或线上操作。
- 字段范围保持原有 12 + daily_basic 16 + 存量 16 + TTM 19 + 指标首批 6 + 其余指标 157 = **226**。

## 工单顺序

| 编号 | 工单 | 技术阻塞项 | 执行前置 | 状态 |
| --- | --- | --- | --- | --- |
| 01 | [统一现有字段目录、准入和家族合同](01-unify-field-contract.md) | 无 | 无 | complete |
| 02 | [接入 daily_basic 的 16 个 DSL 入口](02-daily-basic-fields.md) | 01 | 01 完成并提交 | complete |
| 03 | [开放三表的 16 个期末存量字段](03-statement-stock-fields.md) | 01 | 02 完成并提交 | complete |
| 04 | [提供 19 个 TTM 流量及不同期缺失规则](04-ttm-flow-fields.md) | 01 | 03 完成并提交 | complete |
| 05 | [贯通 fina_indicator 的代表性指标链路](05-financial-indicator-pilot.md) | 01 | 04 完成并提交 | complete |
| 06 | [补齐 fina_indicator 全部 163 个指标](06-financial-indicator-catalog.md) | 05 | 05 完成并提交 | complete |
| 07 | [构建并验证 226 字段完整历史候选数据集](07-build-full-history-candidate.md) | 02、03、04、06 | 06 完成并提交 | ready-for-agent |
| 08 | [完成统一验收并一次硬切发布](08-integrate-and-cut-over.md) | 07 | 07 完成并提交 | ready-for-agent |

## 验收和证据

各工单正文列明对应母规格 T01—T16 的验证边界，覆盖全部 226 项范围。实施时在每票追加 Plan、实际验证结果、审查及修复复审记录、提交引用；不以目录注册完成替代来源资格和完整历史数据验收。

历史草案已由本目录正式工单取代。
