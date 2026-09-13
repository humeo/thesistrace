# 14 — 联合验收映射

状态：联合验收完成。首次失败与受影响边界复验分开记录；详见下方门禁表。

基线 `31a5214f`，与main共同基准 `2daf193e9bcd00ab18e8d5e1bf5e67dbcf557d8d`。以[母规格](../spec.md)当前执行约束为准：早期迁移验收已撤回；已有历史迁移测试只维护真实历史夹具，不为本功能新增迁移。

## 母规格可观察行为

| 行为 | 所属票 | 当前证据入口 | 已核对的独立边界 |
| --- | --- | --- | --- |
| 两种kind独立、Strategy/Track不调用未来标签 | 01 | [test_research_kind_contract.py](../../../apps/core/tests/kernel/test_research_kind_contract.py), [test_tracking_columnar.py](../../../apps/core/tests/kernel/test_tracking_columnar.py), [test_core_research_batch_factor_execution.py](../../../apps/core/tests/acceptance/test_core_research_batch_factor_execution.py) | Tracking的标签函数明确注入不可调用实现；分kind输入拒绝；普通与Batch入口各自完成。 |
| 实际本金、手数、费用、现金及收益分母 | 02、07 | [test_manual_strategy_ledger.py](../../../apps/core/tests/kernel/test_manual_strategy_ledger.py), [test_core_initial_cash.py](../../../apps/core/tests/acceptance/test_core_initial_cash.py), [test_core_research_batch_strategy_execution.py](../../../apps/core/tests/acceptance/test_core_research_batch_strategy_execution.py) | 10万/1000万独立运行与手算数量/费用/NAV对比；实际Strategy Sweep组合条件/共同Signal、10万、rank/inverse配权及0/0.7/动态Exposure，与普通Run规范Result和持仓字节逐一比较并开始Track；固定Exposure按权益计算，不能缩放另一本金结果。 |
| 三种Weighting及无效候选 | 09、10 | [test_portfolio_weighting.py](../../../apps/core/tests/kernel/test_portfolio_weighting.py), [test_inverse_volatility_weighting.py](../../../apps/core/tests/kernel/test_inverse_volatility_weighting.py), [test_manual_strategy_ledger.py](../../../apps/core/tests/kernel/test_manual_strategy_ledger.py) | rank 1/2、1/3、1/6；ties 5/12、5/12、1/6；sigma .1/.2产生2/3、1/3；零波动/缺失顺延、全无效空仓；实际账户消费权重。 |
| 共同市场/行业成员及无未来数据 | 05 | [test_common_market_inputs.py](../../../apps/core/tests/kernel/test_common_market_inputs.py), [test_common_input_admission.py](../../../apps/core/tests/kernel/test_common_input_admission.py) | 当前Universe和历史行业子集、排除原因、作用域广播、固定依赖及改未来价格保留此前输出。 |
| 比较/布尔/条件、Unknown和联合窗口 | 04、05、07、10 | [test_conditional_signal.py](../../../apps/core/tests/kernel/test_conditional_signal.py), [test_daily_exposure_expression.py](../../../apps/core/tests/kernel/test_daily_exposure_expression.py), [test_selection_exposure_contract.py](../../../apps/core/tests/kernel/test_selection_exposure_contract.py) | Signal与Exposure共用编译合同，布尔/作用域拒绝、未选分支、配权/Exposure观察窗口。 |
| 独立选股周期与日频Exposure触发 | 07、08 | [test_manual_strategy_ledger.py](../../../apps/core/tests/kernel/test_manual_strategy_ledger.py), [test_tracking_columnar.py](../../../apps/core/tests/kernel/test_tracking_columnar.py) | 比例减仓、只加/只减、空仓中更新名单、恢复使用保留目标、不按价格漂移每天重配。 |
| 不可成交与无自动补偿/重试 | 08、11 | [test_manual_strategy_ledger.py](../../../apps/core/tests/kernel/test_manual_strategy_ledger.py) | blocked/interval组合下固定目标，不将第一只卖不出补偿给第二只；真实后续触发才产生新订单。 |
| 末日Open、Chunk切点及连续Track | 03、07、08 | [test_research_chunk_continuation.py](../../../apps/core/tests/kernel/test_research_chunk_continuation.py), [test_tracking_columnar.py](../../../apps/core/tests/kernel/test_tracking_columnar.py) | 同输入不同切点比较规范结果/账户；完整末日与后续首Open延续冻结目标；不替换已发布边界。 |
| 缓存丢失、并发Refresh、失败恢复 | 03、05、08 | [test_daily_track_working_cache.py](../../../apps/core/tests/integration/test_daily_track_working_cache.py), [test_core_research_agent_mcp_daily_tracks.py](../../../apps/core/tests/acceptance/test_core_research_agent_mcp_daily_tracks.py) | 真实数据库/对象存储恢复与权限入口；完整门禁还必须跑专门restart阶段，普通pytest不能代替。 |
| Factor标签、每日证据与月年汇总 | 01、06 | [test_factor.py](../../../apps/core/tests/kernel/test_factor.py), [test_factor_daily_evidence.py](../../../apps/core/tests/kernel/test_factor_daily_evidence.py), [test_factor_periods.py](../../../apps/core/tests/kernel/test_factor_periods.py), [test_core_factor_daily_evidence.py](../../../apps/core/tests/acceptance/test_core_factor_daily_evidence.py) | Open标签时点/右删失、独立IC期望、完整每日值、等日权汇总及失败后发布重用。 |
| 目标/订单/成交、现金和数量坐标对账 | 11 | [test_manual_strategy_ledger.py](../../../apps/core/tests/kernel/test_manual_strategy_ledger.py), [test_core_research_agent_mcp_runs.py](../../../apps/core/tests/acceptance/test_core_research_agent_mcp_runs.py) | 独立ledger核对结算、费用、核销、拆分成交和稳定父子键；公开查询分页。 |
| 临时持仓收集不改变账户 | 12 | [test_daily_holding_evidence.py](../../../apps/core/tests/kernel/test_daily_holding_evidence.py), [test_manual_strategy_ledger.py](../../../apps/core/tests/kernel/test_manual_strategy_ledger.py) | 同核心计算启用/关闭收集比较账户事件；空仓覆盖、当日Open估值、只保存实际持股。 |
| 7天闲置TTL与只续期成功读取单元 | 12 | [test_holding_retention.py](../../../apps/core/tests/integration/test_holding_retention.py), [test_daily_holding_queries.py](../../../apps/core/tests/kernel/test_daily_holding_queries.py) | 控制时间验证成功空仓读取、非读取不续期、分单元到期及固定分页扫描预算。 |
| 读删竞争、共享引用及清理失败恢复 | 12 | [test_holding_retention.py](../../../apps/core/tests/integration/test_holding_retention.py), [test_publication_maintenance.py](../../../apps/core/tests/integration/test_publication_maintenance.py), [test_publication_records.py](../../../apps/core/tests/integration/test_publication_records.py) | 实际PG/RustFS的读赢/删赢、独立单元、永久字节保护、删除失败重试和未提交对象清理。 |
| 当前数据重跑，旧数据/源Run可不存在 | 13 | [test_core_current_data_rerun.py](../../../apps/core/tests/acceptance/test_core_current_data_rerun.py), [test_research_rerun_command.py](../../../apps/core/tests/kernel/test_research_rerun_command.py) | 修订历史价格允许新旧差异；Track自有Origin、原起点至调查日、来源关系、原历史不变、新持仓独立。真实浏览器闭环在14补入core-shell现有隔离用例。 |
| 所有权/scope/cursor/过滤与状态区分 | 11、12、13 | [test_research_agent_mcp_contract.py](../../../apps/core/tests/architecture/test_research_agent_mcp_contract.py), [test_core_research_agent_mcp_http.py](../../../apps/core/tests/acceptance/test_core_research_agent_mcp_http.py), [test_core_research_agent_mcp_runs.py](../../../apps/core/tests/acceptance/test_core_research_agent_mcp_runs.py), [test_core_research_agent_mcp_daily_tracks.py](../../../apps/core/tests/acceptance/test_core_research_agent_mcp_daily_tracks.py) | 来源读取scope缺失FORBIDDEN；跨拥有者/伪造cursor拒绝；expired/not_recorded/空仓和未扫描完页明确区分。 |

## 纵向票据与独立提交

每票验收子项的详细要求、实现过程、失败/修复证据与串行审查记录保留在对应票据及计划。此表核对前置状态和提交归属，不用勾选数替代测试覆盖。

| 票 | 已验收子项 | 独立提交 | 计划 |
| --- | --- | --- | --- |
| [01](../issues/01-separate-research-execution.md) | 8 | `a32208b6` | [01-separate-research-execution](01-separate-research-execution.md) |
| [02](../issues/02-initial-cash-through-account.md) | 8 | `ffc1eacd` | [02-initial-cash-through-account](02-initial-cash-through-account.md) |
| [03](../issues/03-completed-terminal-tracking.md) | 8 | `703c303e` | [03-completed-terminal-tracking](03-completed-terminal-tracking.md) |
| [04](../issues/04-conditional-signal-expressions.md) | 8 | `4e264862` | [04-conditional-signal](04-conditional-signal.md) |
| [05](../issues/05-shared-market-industry-inputs.md) | 8 | `0fbcaaeb` | [05-common-market-conditions](05-common-market-conditions.md) |
| [06](../issues/06-daily-factor-evidence.md) | 8 | `ca3bea90` | [06-daily-factor-evidence](06-daily-factor-evidence.md) |
| [07](../issues/07-selection-and-fixed-exposure.md) | 9 | `c62c085c` | [07-selection-and-fixed-exposure](07-selection-and-fixed-exposure.md) |
| [08](../issues/08-daily-exposure-adjustment.md) | 9 | `d7da500e` | [08-daily-exposure-adjustment](08-daily-exposure-adjustment.md) |
| [09](../issues/09-rank-portfolio-weighting.md) | 7 | `9c5e267e` | [09-rank-portfolio-weighting](09-rank-portfolio-weighting.md) |
| [10](../issues/10-inverse-volatility-weighting.md) | 7 | `46d5bd46` | [10-inverse-volatility-weighting](10-inverse-volatility-weighting.md) |
| [11](../issues/11-query-targets-orders-fills.md) | 9 | `c9a7c86e` | [11-query-targets-orders-fills](11-query-targets-orders-fills.md) |
| [12](../issues/12-expiring-daily-holdings.md) | 10 | `4c2ad039` | [12-expiring-daily-holdings](12-expiring-daily-holdings.md) |
| [13](../issues/13-rerun-holding-diagnostics.md) | 8 | `31a5214f` | [13-rerun-holding-diagnostics](13-rerun-holding-diagnostics.md) |

## 组合证据的范围

- `test_columnar_tracking_matches_every_checkpoint_and_recovery_boundary`参数化5组Signal/中性化/持股数/选股周期 × 2组Exposure × 3种Weighting，明确禁用未来标签，比较每个恢复边界。手工ledger另提供数字期望，避免仅用两种实现互相证明。
- `test_strategy_sweep_reuses_shared_alpha_factor_and_matches_ordinary_runs`为真实发布/Worker/存储组合，包含普通/条件/共同Signal及动态Exposure；验证完整Result、持仓、冻结配置与Track来源。是否在最终组合版本全部通过，以本次完整check结果为准。

## 联合门禁与容量边界

本次两次实际调用 `pnpm check` 均非 exit 0：首次停于 Core 旧夹具，第二次通过此前阶段后停于 Agent 旧断言。按 AGENTS 先修复并复跑受影响边界、继续未执行阶段，最终证据按下表组合；不把分段通过写成整条命令一次通过。

| 门禁 | 最终验证结果 | 证据（仓库 `.local/test-runs/issue-14/`） |
| --- | --- | --- |
| Quick | Python 1522、Agent 648、Auth 200、Web 368 passed；菜单回归加入后 Web 全量 369 passed，typecheck 通过 | check-second.log；web-shell-menu.log；web-typecheck-menu.log |
| 浏览器组件 | 49 passed | check-second.log |
| Core 真实集成/验收 | 492 passed、8 deselected；另外六个专门依赖重启阶段各 passed | check-second.log；20260912t234521z-54058-29efcb3e/run.txt |
| Auth / Agent 真实集成 | Auth 145 passed；Agent 修复断言后全量 96 passed、typecheck 通过 | check-second.log；agent-integration-second.log；agent-typecheck.log |
| E2E 普通组 | 第二轮 67 passed、4 failed；四处已明确定位并修复，当前镜像边界专项 4 passed（含一项额外恢复验证），MCP 日志专项 1 passed | e2e-full-second.log；e2e-final-boundaries-second.log；e2e-mcp-log-boundary.log |
| E2E 隔离组 | 第二轮 7 passed、1 failed；Invitation 修复后定向 1 passed（26.0 秒）。八组现行行为均通过，最终 Dataset 27.6 秒 passed；通过运行清理 exit 0 | e2e-full-second.log；e2e-invitations-third.log |
| 最终镜像 smoke | 初始化、真实 API/Worker/Result、Auth、健康与 Caddy 单源全部通过；诊断、敏感内容扫描和清理 exit 0 | image-smoke.log；20260913t005743z-13253-2668dd9b/run.txt |

新增过期重跑闭环已在真实浏览器通过（55.8 秒，后续完整隔离组再次 55.6 秒通过）：读取不创建任务、显式新 Run、原 Track 不变、新持仓可读。截图保留在 `20260912t234903z-56291-c5b356be/evidence/playwright-results/core-shell-Default-and-cus-b1833--safely-and-publish-results/` 的 `expired-track-holdings.png`、`current-data-rerun-holdings.png`；运行中/键盘/44px 窄屏证据在 `20260913t010217z-16543-9044710d/evidence/playwright-report/`，截图均已查看。

- 12容量证据：`.local/test-runs/issue-12/capacity-*.json`及`measure-holding-codec.py`。100持股×2500Session=250000行，Parquet1886560字节+描述108567字节，codec+本地写入4.201秒、峰值RSS133251072字节（含Arrow初始化，基线91275264）。这不是生产行情压缩率、完整策略耗时或S3持久写入承诺。
- 12小型真实清理失败恢复实测0.015秒，不含调度队列与生产负载；TTL限制历史累积，不消除窗口内产量、持续访问单元或一次写入峰值。
- 未运行真实模型、真实供应商、完整发布资格或线上部署；未合并到 main、未推送，不声明这些链路通过。最终交付限定本隔离工作树的当前合同。

## 最终审查与版本

- Standards：冻结36文件快照无发现；取消弹窗测试增量复审无发现。Spec：同快照与增量无发现，全部待完成门禁随后通过。代码快照后仅有验收记录与tracker更新。
- 普通71项由67个通过项及4个明确修复后的定向通过项闭合；8个隔离项由7个通过项及Invitation定向通过闭合，共79项，无skip/fixme。复验额外包含Provider恢复。
- 交付位于`codex/research-capabilities`，14独立提交包含本记录；以该文件所属提交定位最终版本。未合并或部署。
