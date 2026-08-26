# 09 — 分页读取 DailyTrack 语义结果

**What to build:** 让 Research Agent 按 section、有界地读取 DailyTrack 当前产品语义结果和 origin/provenance，并沿用 ResearchRun 已证明的稳定分页规则，而不暴露 tracking working cache、checkpoint、attempt 或对象存储布局。

**Blocked by:** 04 — 分页读取 ResearchRun 语义结果; 07 — 启动并查询 DailyTrack

**Status:** completed

- [x] 发布要求 `tracking:read` 的 `get_daily_track_result`，支持 `factor`、`strategy_summary`、`strategy_observations`、`origin`、`provenance` 五个显式 section。
- [x] section 使用 discriminated input/output Schema；collection 内容使用 opaque cursor、默认 20、最大 50，并拒绝与 section/resource/order 不匹配的 cursor。
- [x] Factor、Strategy summary、benchmark、dates、units、coverage 与 missing-value 语义和当前产品保持一致；observations 按 session 升序稳定分页。
- [x] origin 返回解释 DailyTrack 起点所需的产品语义，任何 positions 集合均为确定性有界页面，不允许 origin section 因持仓数量而无界增长。
- [x] provenance 足以关联 origin ResearchRun、frozen research input 与 tracking 结果，但不提供 Data Generation 选择器或 manifest、object key、cache、checkpoint、attempt、lease、SQL、路径。
- [x] blocked、stopped、尚无可读结果、not found、非法 section、错误 cursor、响应超限和内部读取失败有明确稳定结果，不截断 JSON 或返回成功空对象。
- [x] 使用真实 DailyTrack progression 验证多页 observations/positions、重启后读取、immutable origin、有限值与独立结果不变量。
- [x] ResearchRun 与 DailyTrack 的共享分页行为有一致契约测试，同时保持各自 module ownership，不建立跨模块 foreign-table 查询。
- [x] Capability Registry、stdio、HTTP 和真实依赖 acceptance 测试通过，失败证据不泄漏私有 tracking 状态。
