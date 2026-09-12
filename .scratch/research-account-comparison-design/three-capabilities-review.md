# 三种能力设计审查：规则与当前实现的差异

Status: needs-triage

2026-09-12。按用户要求使用 grill-with-docs；两项并行只读核对分别覆盖 Signal/Weighting 与账户/产物/续算。代码基线 `2daf193`，没有运行产品测试或修改实现。已接受规则写入 [设计](three-capabilities-design.md)，本轮 Q1–Q3 均已回答，见 [决策树](decision-frontier.md)。

## 已确定的实质修改

### 末日执行与不可替换的追踪边界

当前 [Strategy](../../apps/core/src/thesistrace/research_kernel/strategy.py) 在最后 Session 使用 `terminal_valuation` 并跳过交易；[Track 查询](../../apps/core/src/thesistrace/daily_track/service.py) 用 successor 覆盖旧边界日期的观察。[现有测试](../../apps/core/tests/kernel/test_tracking_observation_state.py) 的 `test_replaced_boundary_does_not_leave_an_obsolete_peak_or_loss` 专门验证这种替换行为。这说明新方案的严格追加要求不能只通过增加结果字段实现。

用户 Q2 已选择：最后 Session 也完成应执行的 Open 交易及费用，末日不强平；收盘新决定留待以后执行。后续 Advance 从完整状态继续，不重算旧日期。新结果与旧合同末日可能有实际交易和费用差异，不能承诺跨旧合同完全等价。

### 配权口径

当前 [等权计算](../../apps/core/src/thesistrace/research_kernel/strategy.py) 按候选数均分账户。[rank 与 ts_std](../../apps/core/src/thesistrace/research_kernel/alpha_builtins.py) 已有固定口径；全 Universe 的百分位排名不能直接冒充“入选股票的线性排名加权”。

在最终入选集合内使用线性名次权重，并列使用平均名次权重；波动率采用调整后 Close 单日收益和完整窗口，总体标准差，默认窗口 20。用户 Q3 已选择零波动排除顺延、候选不足时使用有效者、全部无效时空仓。完整计算定义写入设计，无隐藏 epsilon 或等权替代。

## 可直接补齐的工程规则

| 事实 | 设计修正 |
|---|---|
| [Chunk](../../apps/core/src/thesistrace/research_kernel/research_chunks.py) 将每日 Factor 变成累计统计；[公开 Result](../../apps/core/src/thesistrace/research_run/models.py) 只有摘要 | 在汇总前保留每日各期限统计、组人数及覆盖；月/年按信号日期汇总，不伪称旧摘要能恢复每日结果 |
| [Factor 标签](../../apps/core/src/thesistrace/research_kernel/factor.py) 的 `t+1+h` 超出研究末日时为 `right_censored_by_research_period_end` | 沿用所选研究边界并说明尾部未评价；按月分组不再次截断标签，不称为数据缺失 |
| [PendingSignal](../../apps/core/src/thesistrace/research_kernel/terminal_state_schema.py) 主要保留日期；[Track calculation](../../apps/core/src/thesistrace/daily_track/calculation.py) 可从新 Generation 重建临时 Alpha | 权威状态保存已经确定的下一 Open 目标及其数据身份；缓存消失不能改写过去决定 |
| [Strategy](../../apps/core/src/thesistrace/research_kernel/strategy.py) 用 `len(orders)` 等产生局部身份；Chunk/Track 续算会清空数组 | 明细公开前定义与 Chunk/Attempt 无关的确定性逻辑事件键，并维护父子及成交关联 |
| 当前 Fill 有 raw notional，但合成卖出按调整后持有单位结算 | 明细包括实际结算金额、现金变化和调整后单位变化，使对账承诺成立 |
| 每日持仓在可选 ledger 中，主 Chunk 路径没有发布这些分区 | 按用户最新选择，复用核心并有界输出独立临时每日持仓，读取续期、到期清理；永久事件及终端结果保持自己的发布合同 |
| 旧 Result 没有保存这些明细 | 当前结果合同区分未记录与零条记录；显式保留数据迁移不制造旧交易，不伪称新合同重算等于旧结果重放 |

## Q1 的事实依据与已接受修改

当前 [Strategy Result](../../apps/core/src/thesistrace/research_run/models.py)、[Chunk 完成](../../apps/core/src/thesistrace/research_kernel/research_chunks.py) 与 [Track Checkpoint](../../apps/core/src/thesistrace/daily_track/checkpoint.py) 均强制依赖 Factor 数据。仅把前端分成两个按钮并不能实现计算职责分离。

用户已回复“分开运行”：Factor Evaluation 独立提交；Strategy Backtest 与 DailyTrack 保留必要 Signal/Alpha 计算，只输出账户与交易结果。普通 Run、Batch 和 Track 的执行、结果、Chunk 完成条件与续算状态均需解除隐式 Factor 依赖，首版不增加复合运行选项。设计及 ADR 已同步；存量 Result 的附带 Factor 数值通过显式迁移保留历史归属，不静默删除或伪造独立 Run。

交叉检查发现 [ADR-0216](../../docs/adr/0216-share-bounded-batch-calculation-and-recover-complete-tasks.md) 原先明确写了 Strategy Sweep 共享 Alpha-and-Factor。已随 Q1 调整为按请求类型共享，保留完整任务恢复边界，避免 Batch 设计仍要求被取消的 Factor 计算。

## 文档维护

CONTEXT 只记录领域词义；参数、公式、状态字段和验证留在 spec。沿用现有 ADR 编号记录已确认的配权、结果保留和终点决定，没有新增泛化架构 ADR。产品三项能力、手动 Refresh、已有 Universe/行业范围和受阻规则不再要求重复确认。

2026-09-12 存储范围最终修订：用户选择正常运行即保存每日持仓，实际读取续期，闲置到期删除；以后按当前数据重跑并接受差异。这替代了此前不保存每日持仓和原条件按需复现的备选，完整规则见 [临时每日持仓设计](temporary-holdings-design.md)。CONTEXT 增加 Daily Holding Observation 的领域含义，期限、存储与清理机制保留在 spec。

原输入 pin 会在 Run 完成后释放，但这已不构成新回测排障的阻碍：新 Run 正常准入当前数据即可。原结果、已发布 Track 与单次运行内部的一致性要求保持不变；放宽跨 Run 的数据版本要求不允许在运行中混用可变数据或回写旧净值。Publication 的引用校验必须保护永久 Result/Checkpoint，临时明细不能作为它们到期后会缺失的必需分区。
