# 10 — 统一结构化错误与安全运维事件

**What to build:** 让所有 MCP Tool 在两个 transport 上使用同一套可恢复的结构化 outcome/error 语言，并为每次调用产生足够排障但不泄漏研究内容的 operational event；Product State 仍是业务权威，日志不能成为第二套审计或恢复数据库。

**Blocked by:** 02 — 提供 OAuth 保护的 Streamable HTTP 只读闭环; 05 — 按独立权限取消 ResearchRun; 06 — 提交、监控并取消 Research Batch; 08 — 恢复和停止 DailyTrack; 09 — 分页读取 DailyTrack 语义结果

**Status:** completed

- [x] 所有 Tool 都使用 explicit structured output Schema；Formula Diagnostics 与 domain admission rejection 保持 successful discriminated outcome，不被包装成 protocol error。
- [x] 边界非法输入、not found、forbidden、lifecycle conflict、idempotency conflict、临时依赖失败和未知内部失败分别稳定映射为 `INVALID_INPUT`、`NOT_FOUND`、`FORBIDDEN`、`STATE_CONFLICT`、`IDEMPOTENCY_CONFLICT`、`TEMPORARILY_UNAVAILABLE`、`INTERNAL`。
- [x] structured error 包含稳定 code、简洁 message、`retryable`、可选有界 retry delay、trace ID 和安全上下文；临时失败可重试，永久输入/权限/状态问题不可伪装成临时失败。
- [x] 内部异常永不转换为空成功结果，且响应不包含 SQL、credentials、raw token claims、stack trace、filesystem path、object key 或 string-encoded nested JSON。
- [x] 每次 Tool 调用产生一个 completion event，包含 subject、transport、Tool name、已知 resource ID、已提供 request ID、outcome/error code、latency、response bytes、trace ID。
- [x] completion event、应用日志、health 与协议错误均不记录 bearer token、Formula、hypothesis、full arguments/results、observations、terminal positions、storage locations 或 credentials。
- [x] 使用唯一 canary 值覆盖 token、Formula、hypothesis、SQL、path、credential、observation 和 position 泄漏，并自动断言所有诊断输出中均不存在这些值。
- [x] stdio 与 HTTP 对代表性成功和每类失败返回相同的业务结构；授权失败不改变 Product State，日志丢失也不影响 ownership、retry、recovery、cancel、Stop 或 publication。
- [x] 不新增 MCP audit、telemetry recovery 或 error cache schema；结构化错误、redaction 和 operational event 契约测试及受影响门禁全部通过。
