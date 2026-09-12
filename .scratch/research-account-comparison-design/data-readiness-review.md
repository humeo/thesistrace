# 数据就绪、执行重试与 exposure 无效的分层处理

Status: needs-triage

> 用户再次指出现有准入已保证数据可研究。复核结论：没有发现或复现实际线上数据异常，也未证明已有校验存在漏洞。此前以“已接受回测可能缺整体历史”为由要求产品另选错误策略不成立。当前范围仅要求新增市场/exposure 依赖接入已有发布、覆盖、warm-up 和冻结校验；不另起一套缺数据策略。下文故障矩阵仅用于工程语义区分，不是已发生缺陷或新增首版需求。

## 对“完整”的精确定义

回测接受前，research_run/service.py:3794–3914 已检查当前数据、研究范围、字段、财务/行业覆盖及所需整体预热历史，随后固定 Generation。历史长度不足会在接受前被拒绝，不能把它描绘成正常运行中突然才发现的问题。单独选 Universe 不是全部校验发生的时点，最终保证来自数据发布与接受检查共同完成。

完整符合数据合同，不等于所有股票所有字段每天非空：generation_validation.py:80–108 明确允许 full_session_suspension / data_unavailable 状态；market_series.py:86–101 按有效价格和正成交额过滤研究成员；Financial Coverage 不承诺非空。Missing Alpha 也可能来自公式本身。这些有定义的缺失按既有样本/执行规则处理，不等于整个数据集损坏或整次回测失败。

首版新增 CSI300 收盘/exposure 时将新字段、交易日覆盖、窗口、类型和输出约束纳入同一准入/执行合同即可。若要声称存在具体缺陷，必须提供可复现的接受输入与出错证据；本轮没有这样的证据。

2026-09-11。用户指出 DailyTrack 手动 Refresh，要求系统分析，不能笼统将缺数据等同于整个回测失败。本记录替代此前各提案中的“exposure 缺失就终止计算”统一表述。以下明确区分当前代码和新增能力建议；未运行测试或修改产品实现。

## 当前代码事实

- ADR0234：Dataset Head 变化不自动创建 Tracking 工作；手动 Refresh 排队一次 Advance，接受后的内部异步执行可重试。
- daily_track/service.py:917–1025：Refresh 先检查 active、idle、当前 Head 和进度。无 Head 抛 DailyTrackRefreshUnavailable；已经追平也抛同类 unavailable，不排队、不标记 Track 或原 ResearchRun 为失败。
- research_run/service.py:3794 起：无数据、区间超覆盖、字段不支持、历史 warm-up 不足在准入拒绝。已接受 Run 的输入冻结，今天有没有新的发布不改变既有研究问题。
- research_run/failure_policy.py：InfrastructureUnavailable / WorkerLost 最多3次；SelectedDataInvalid / CalculationFailure 等确定性错误不原样重试。service.py:3501 起将失败 attempt 与研究终态区分，仍可重试时 Run 保持 running。
- daily_track/service.py:3348 起：暂时基础设施错误先有限重试；不可恢复或耗尽时推进与 Track 进入 blocked，失败路径不覆盖成功 checkpoint。financial / industry coverage 有专项阻塞原因。
- blocked 的 Retry 与 active/lagging 的 Refresh 是不同动作；手动 Refresh 不等于从供应商采集所有缺失数据。

## 建议处理矩阵

| 情况 | 新回测 | 手动 DailyTrack Refresh / Advance |
|---|---|---|
| 今天还没有比当前进度更新的已发布数据 | 在支持的已发布区间正常研究；不能擅自改变用户日期 | 显示已追平当前数据及实际数据日期，不创建推进；不是运行失败 |
| 用户区间/市场指标历史长度超过可用数据 | 接受前返回所需/可用区间和具体缺口，不创建注定失败的 Run | 准入/推进前检查依赖；未就绪不给账户算新值，保留上次结果并说明等待哪项数据 |
| 数据已冻结且有效，但存储暂时不可读、Worker 丢失 | 相同身份/输入按现有有界重试恢复 | 接受的 Advance 内按现有重试规则恢复，耗尽后 blocked；不抹掉旧结果 |
| 数据清单声称完整，固定数据却缺行或损坏 | 系统核验具体字段、日期、对象完整性并记录根因；当前确定性错误会使该 Run 失败，不能偷偷换新 Generation | 阻塞本次推进，保留既有账户；修复后按当前显式 Retry 合同恢复，不自动发起下一次 Advance |
| 所需时点公式确实产出 missing/越界 | 区分未选分支缺失、warm-up、分母为零与非法输出；固定输入下不可恢复时明确研究无有效结果 | 阻塞推进，保留上次 checkpoint；不能把公式问题当供应商延迟反复重试 |

“已追平”的正常产品提示是建议，当前 Refresh 底层实际用 DailyTrackRefreshUnavailable 返回，应在 HTTP/MCP/Web 中检查并明确表达。不能声称当前已有新的正常 no-op 返回合同。

## 系统诊断最小内容

给出 stage（准入/准备/读取/计算/发布）、dependency、所需与可用日期、缺失 session、固定数据身份、错误类别、可否重试以及下一步动作。不能只给 DATA_MISSING，也不能把所有 None 归为采集失败。

新增 exposure 需要在准入合并 signal/exposure 依赖：市场历史、warm-up、字段可用性。校验能发现的数据问题尽量在创建 Run 前暴露；不能因此承诺所有动态表达式错误都能在无计算的预检发现。

对冻结数据异常，自动重读/完整性核验可以帮助诊断；更新数据版本、修改公式或缩短日期改变研究问题，需要新的显式研究，不可伪装同 Run 恢复。当前模型没有为所有确定性 ResearchRun 错误提供 blocked 状态，本次不假定已经存在。

手动刷新不应因为等待数据变成永久后台监视/自动研究。新数据发布后用户可再次 Refresh；如果先前已 blocked，则按当前 Retry 语义处理。展示入口必须明确区分两者。

## 结果保留与科学含义

原成功 ResearchRun 的不可变 Result 不因后来的 DailyTrack 数据问题被改成失败。失败/blocked 的推进也不抹掉既有成功 checkpoint。一个尚未成功的回测若固定输入确定无效，仍不能发布部分净值冒充完整 Result；这是与“短暂问题立即失败”不同的情况。

缺失值不自动变成0仓位、1仓位、保持上一值或跳过交易日。这些操作属于显式策略语义。用户目前要求的是原因分类和合理恢复，并未授权这类兜底交易规则。
