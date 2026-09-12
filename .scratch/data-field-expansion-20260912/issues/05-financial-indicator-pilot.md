# 05 — 贯通 fina_indicator 的代表性指标链路

**What to build:** Researcher 能在 Financial data 中使用每股、比率、单季和同比指标；先用 6 个代表性字段验证供应商指标从采集、观察版本、财务刷新到研究计算的完整路径，后续指标直接复用同一能力。

**Blocked by:** 01 — 统一现有字段目录、准入和家族合同

**Status:** ready-for-agent

**Execution contract:** 在从 main 创建并核实的新 worktree 中，严格按 01→08 串行执行。每票开始实现前先记录 Plan；完成实现后逐项验收，进行代码审查、修复及复审，更新 tracker 并形成该票独立 git commit，完成后才开始下一票。审查同样串行，不并行委派实现或审查。

**Latest user decision:** 按用户最新要求，直接实现当前合同，不做兼容、版本迁移或 vXX 升级链；这覆盖母规格中有条件引入迁移的旧提议。保留数据、原有字段语义与必要研究引用的要求继续有效，不将“不迁移”解释为允许清库。

**Execution order:** 05；必须先完成 04 的验收、复审、tracker 更新和独立提交。

- [ ] 首批作者入口固定为 eps、bps、current_ratio、roe、q_roe、netprofit_yoy，归入 equity.financial_indicator。逐列核实单位、期间、归属和适用性；q_roe 是单季来源指标，netprofit_yoy 是归母同比，不将整批改成 TTM。
- [ ] 从首批采集开始显式请求普通 fina_indicator 的全部 167 个来源列，保留 163 个数值来源和 4 个元数据列；其余指标暂未通过资格或实现时不声明可用。6 项是正常实施范围，不创建临时功能开关、独立目录或第二版响应。
- [ ] 使用历史 Instrument Identity，普通单股接口按有界报告期区间取数，包括所需 pre-start 报告及历史退市证券。start_date/end_date 是报告期过滤，不能充当公告增量游标；达到 100 行上限继续验证完整性，不假定 offset/limit 有效，最小分片仍不确定则未完成。
- [ ] 在既有 Operator 流程保存原始响应、报告期、公告日、来源更新标记、首次观察和内容哈希。同内容重试去重并保留最早观察；接口没有保证的 report_type、comp_type 或修订时间不得填造。
- [ ] 有公告日期的记录从下一 Research Session 可见；缺少日期隔离。首次历史回填按已接受的 Announcement-Aligned Financial History 使用并说明证据有限，不能声称完整 PIT。
- [ ] 同逻辑记录、同公告日后见更正最早从首次观察后的可用 Session 生效；真实新披露日期保留来源证据。无法确定次序的冲突隔离，不用响应顺序、哈希或未验证的 update_flag 排序。
- [ ] Financial Refresh 通过公告发现触发股票重查，并有有界历史更正核对及独立 reconciliation watermark。目标未返回时保留指标来源 pending；三表成功、无变化或已完成不能清除该 pending。
- [ ] 权限不足、限流、超时、截断和缺列保留未完成状态，重试恢复不丢旧证据。区分采集未完成、来源缺失和不适用；供应商字段为空不从三表反算补上。
- [ ] 财务指标保持稀疏版本，按每个字段固定期间选择最新可见报告，再取该列；选中空值不回溯旧非空值。百分数按证据转为小数，倍数保持原尺度；读取只投影需要的列、股票和时间。
- [ ] 家族仍通过单一 Head 随 Financial Refresh 发布；刷新和恢复保留其他家族及真实覆盖。已接入 6 项在目录、Financial 区块、补全、HTTP/MCP 和 Agent 中一致，整类不能在指标未齐时显示全部 ready。
- [ ] 在固定 Generation 上演示 roe 等指标从查询到研究完成；覆盖公告可见性、后见修订、独立 pending、截断重试和指标未就绪拒绝。ResearchRun、Batch、DailyTrack 值一致，研究禁用供应商网络仍完成。
- [ ] 保存首批有界真实来源资格与脱敏请求证据；完成相关公开模块、真实 Worker/存储、合同和页面验证。新增来源直接采用当前数据合同，不增加版本迁移、vXX 升级链或兼容分支；保留已有来源和研究引用。

**Verification:** 母规格 T02、T06、T08、T09、T10、T11、T15。163 项全量作者入口由 06 补齐，完整历史覆盖由 07 汇总；本票不单独上线。

## Comments

- 2026-09-12：用户确认发布工单。已纳入最新的串行执行、每票 Plan / 验收 / 审查修复复审 / tracker / 独立提交，以及不兼容、不做版本迁移的要求。
