# 08 最终验收对应表（发布前）

已验收产品代码 39e4b88c；其后 dde78933 与日志缓冲修正仅涉及测试和记录；真实历史候选及来源资格沿用 issue07-acceptance-index.md。下面定位已实施的验证边界；R2完整产品验证的唯一日志读取失败已定向修复通过，不声称整条release gate零退出，也不证明生产已切换。

| 规格 | 主要证据 | 状态边界 |
|---|---|---|
| T01 | 01/06验收；226目录；Core Alpha合同与Web Data目录测试 | 字段身份与旧语义已有确定性验收 |
| T02 | 07价格、每日指标、三表、指标来源资格及字段覆盖报告 | 真实来源和规范化证据；不宣称全市场全历史非空 |
| T03–T04 | test_financial_series.py、test_ttm_research_series.py | TTM组成、必要缺失、更正可见时间、旧语义 |
| T05 | test_ttm_research_series.py、test_series_execution_plan.py、test_research_chunk_continuation.py | 不同窗口缺失与列式/分块执行 |
| T06 | test_financial_indicator_evidence.py、test_financial_candidate.py及07隔离统计 | 可见日期、首次观察、冲突与修订限制 |
| T07 | 07完整历史/退市/种子报告及test_ttm_seed_closure_supports_start_and_later_first_year_quarter | 实际候选重开；研究不开放pre-2010 |
| T08 | TuShare daily_basic/indicator适配器、collection/checkpoint/progress测试；07采集报告 | 截断、重试、空目标、指标独立pending |
| T09 | financial_family_readiness、dependencies、mounted_generation_store及HTTP/MCP合同 | 依赖级准入、缺失与来源关联 |
| T10 | 07实际离线读取、完整候选19262坐标独立计算；单次/Batch/Track验收 | 冻结数据、列投影与无供应商网络读取 |
| T11 | complete_field_candidate_reopens_and_preserves_families_across_publications、刷新集成及Market/Financial/Industry隔离E2E | 无变化复用与后续刷新家族保留；生产正常刷新仍待验证 |
| T12 | 07并发/发布前失败/回执故障证据；dataset_lifecycle_fence及generation_collection | CAS、并发重组、发布结果恢复及引用保护 |
| T13 | current_head_research_run_retry、current_head_research_run_execution、generation_collection及DailyTrack验收 | 冻结旧Run/新Attempt合同在隔离依赖验证；真实生产旧结果与Track仍待核验 |
| T14 | 04验收、TTM研究序列与kernel缺失/策略/Tracking测试 | 使用既有缺失和交易规则，不新增隐式交易 |
| T15 | DataPage与data-fields浏览器；Complete field catalog composes one Formula and starts its DailyTrack | 四块、22/204/226、筛选和混合来源研究/Track已在隔离真实浏览器通过；生产仍待切换 |
| T16 | financial_indicator_schema_upgrade五项、历史schema恢复演练、完整镜像R8及Operator权限验收 | 当前合同、数据保留、重复验证与回滚已在隔离环境通过；真实备份、升级和发布仍待执行 |

最终门禁日志：/tmp/issue08-clean-release-gate-r2.log。R1为1422通过/白名单遗漏1失败，已9项定向通过并双轴串行复审0；首次失败保留。
