# 07 — 验收证据索引

本索引区分真实历史数据、确定性工程验收和未完成事项。数据候选已验收，串行 Standards / Spec 审查均通过；本索引随第 07 票独立提交交付。交接坐标及证据哈希见 [候选交接](issue07-candidate-handoff.json)。

固定源 Generation：`17f5694f6a9d47b915ffde326928b919a55181e75a4908cb661934850ac8c983`。研究范围：2010-01-04 至 2026-09-09；包含 5,550 个历史证券身份及 333 个退市身份。

## 真实来源及历史覆盖

| 边界 | 当前证据 | 证明范围 |
|---|---|---|
| 原始数据保留 | [源完整性报告](issue07-source-integrity.json) | 源 Head 未变；23,908 个传递引用的内容校验，含完整日历和基准 |
| 7 个价格字段 | [价格资格报告](issue07-price-source-qualification.json) | 14,007,368 个实际价格记录；逐字段、年份计数 |
| 15 个每日指标 | [完整候选](issue07-daily-basic-candidate.json)、[来源资格](issue07-daily-basic-source-qualification.json) | 4,053 个交易日的已保存分片；空值及空目标单独统计 |
| 41 个三表字段 | [重建报告](issue07-statement-history.json)、[研究日期覆盖](issue07-statement-dsl-qualification.json) | 复用原始报表，仅补采 8 个确证缺失证券的 24 个目标；覆盖全部 41 字段 |
| 原字段变化 | [逐坐标归因](issue07-statement-difference-audit.json)、[后续处理决定](issue07-statement-difference-disposition.json) | 15,098 个变化全部归因；旧冻结数据不改写，新候选修正日历生效和字段冲突 |
| 163 个财务指标 | [完整候选](issue07-indicator-candidate.json)、[来源资格](issue07-indicator-source-qualification.json)、[研究日期覆盖](issue07-indicator-dsl-qualification.json) | 全部历史身份已采集，每个字段存在实际非空 DSL 值；保留历史修订证据限制 |
| 可读摘要 | [实际覆盖摘要](issue07-field-coverage-summary.md) | 分母、年份、稀疏值及公司类型证据限制 |

每字段的非空记录不等于每个证券或报告都具备该字段。未披露、不适用、冲突和期间不匹配仍按当前合同表示缺失。

## 工程行为

| 边界 | 证据位置 | 结果与限制 |
|---|---|---|
| 并发发布、发布后回执故障、固定研究输入及 GC | `.local/test-runs/20260913t095335z-18839-2e698e25/` | 12 项真实依赖测试通过，清理成功；具体用例见工单日志，不等于全历史候选已发布 |
| 发布前真实文件写入故障 | `.local/test-runs/20260913t100556z-21534-7c6a7666/` | 1 项通过，清理成功；旧 Head、旧数据读取和刷新时间均保持 |
| 多家族后续刷新保留 | `test_complete_field_candidate_reopens_and_preserves_families_across_publications` | 当前 87 项候选/序列测试运行中的确定性夹具证据；不能替代真实历史覆盖 |
| TTM 起点及首年种子 | `test_ttm_seed_closure_supports_start_and_later_first_year_quarter` | 同一轮测试通过；验证组成报告与边界日期，不开放 pre-2010 研究 |
| 离线读取及按依赖投影 | [实际每日字段读取](issue07-daily-basic-offline-reads.json) | 真实候选的 1/22 列读取通过；解码列数减少，未声称压缩字节读取减少 |

## 最终候选与剩余流程

- 完整 226 字段候选组合已成功：最终根 `77d45ba1e49444b235308bc05fe1803e4e727532d0a8aec6e30bfe2a3b138e5d`，见 [完整候选报告](issue07-complete-candidate.json)。四个家族均 ready；Head 未切换。
- 实际完整候选独立重开、226 列读取及混合 DSL 验收通过：4,467 个证券身份、9 个起止及中间日期、19,262 个结果与独立计算一致，见 [离线验收](issue07-complete-offline-reads.json)。
- 最终根及可用性声明已汇总，工单全部验收项已核对。
- 串行 Standards / Spec 审查均通过；唯一的测试断言问题已修复、验证并复审关闭。本文件随第 07 票独立提交交付，之后才开始第 08 票。

`*-partial.*`、`*-before-consensus.*`、`*-initial-failure.*`、`*-built.json` 等历史报告保留为过程证据。最终采集、来源验证和当前 DSL 资格应使用上表指向的报告；三表差异报告的早期待确认状态由后续处理决定解释。
