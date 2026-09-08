# Researcher quotas

普通 Researcher 每个北京时间自然日可使用 USD 1 的模型预算、提交 10 个
ResearchRun；最多持有 10 个未停止的 DailyTrack。当前 Operator 豁免这三项
业务配额，仍记录使用量。资源容量、请求大小与执行超时独立生效。

## 计数规则

- 日界线统一为 `Asia/Shanghai` 零点，未使用额度不结转。
- 每个被接受的 ResearchRun 消耗一个名额；Research Batch 的每个子项分别计数，
  整个 Batch 原子接受或拒绝。幂等重放和内部重试不重复计数。
- 取消、失败和删除不返还已接受的 Run 次数。保留的 Run Ownership 是计数依据。
- DailyTrack 的 active、blocked、stopping 均占名额，Stop 完成后释放。
- 模型主回答、上下文整理和自动标题均计入所属 Researcher 的同一个预算。

## 统一政策管理

三项业务额度及日界线的唯一配置为 `apps/auth/src/quota-policy.config.json`。
Auth 的 `ResearcherQuotaPolicy` Module 校验配置，并根据当前 Operator 身份返回
有效政策：普通用户使用配置值，Operator 的三项上限均为 `null`（无限额）。
配置可使用零额度；缺失、无效时拒绝启动，不使用内置默认额度补齐。

修改该 JSON 后构建并重启 Auth；Agent、ResearchRun 和 DailyTrack 在后续受限操作
中读取当前政策，不需要同时修改或重启消费者。它们分别在各自资源事务中执行
政策，并在 Auth 不可用或政策格式无效时拒绝新的受限操作。已接受任务继续执行。
这是启动配置，不提供热加载或在线编辑。

## 模型价格和预算

价格放在现有 `apps/agent/config/model-registry.json` 每个模型的
`pricing_usd_per_million_tokens` 中。`input`、`cache_read`、`cache_write`、
`output` 均是 USD / 百万 Token，必须显式配置。内部使用整数纳美元。
价格应覆盖该配置允许的上下文范围和供应商计费档位；不得用缺失价格表示免费。
确定性测试模型显式配置零价格，不访问真实供应商。

当前 Luna 输入 USD 0.20、缓存读取 USD 0.02、输出 USD 1.20 / 百万 Token，
依据 2026-09-08 核对的 [官方模型价格](https://developers.openai.com/api/docs/models/gpt-5.6-luna)。

供应商请求由已有 SDK 构造；调用前使用供应商 Token Count 接口取得输入计数，
以未折扣输入价格上界和本次输出上限预留费用，完成后按供应商 usage 结算，
释放差额。缓存输入单独计价，reasoning 已包含在总输出中，不重复计费。
预留不足拒绝新调用，因此尚有余额也可能不足以覆盖本次调用的完整输出上限。
供应商计数不可用时不发送生成请求。费用依赖配置价格及供应商计数契约。

每次调用的预留先持久化，随后发送生成请求。用量缺失、流式中断或进程退出时，
不将未知用量视为零，也不自动释放其当日预留。次日使用新的日期分区，旧账仍保留。
结算幂等，日期固定为预留所属日期，不因跨零点完成而转移。

Auth 提供内部只读有效额度政策查询，Core/Agent 不直接访问 Auth 表，也不解释角色。
Core 在实际资源事务中检查研究及跟踪配额；Agent 在 PostgreSQL 用户锁下原子预留。
管理员身份变化后的新配额判断读取当前政策。

本次不增加用量页、额度编辑页、套餐或支付接入。

## 验证

使用仓库现有隔离测试入口。验证配置拒绝、实际计费、未知用量、预算拒绝后不发送
生成请求、并发预留、幂等结算、跨日和用户隔离、Operator 豁免、Run 原子入场以及
DailyTrack Stop 后名额释放。测试状态以本次实际证据为准。

2026-09-08 验证记录：快速检查及 18 项浏览器组件测试通过；模型预算与 Schema 的
12 项独立 PostgreSQL 测试通过。Core 首轮发现日期 Fixture、历史分页数据、
管理员批次身份和 MCP 测试环境缺少 Auth 地址的问题，修正后 9 项定向验收通过，
运行器的 6 项独立依赖重启验证也全部通过，测试资源已清理。
证据位于 `.local/test-runs/20260908t034722z-93601-64768e98/`。
Auth 管理员政策的真实 HTTP / PostgreSQL 定向验证通过。

完整回归不记为通过：Auth 全套有一项原有审计测试超过 5 秒；Agent 全套的两个
批次展示用例仍断言并行卡片改动前的文案，其他 92 项通过。两项展示失败的复测
详情保存在 `/private/tmp/thesistrace-quota-agent-integration.json`。本次未运行
完整 E2E、发布验收或真实付费模型调用，也未部署。

统一管理调整的验证：Auth 政策与路由 68 项测试、真实 HTTP 管理员政策测试、
Auth 构建和两端 TypeScript 类型检查通过；模型包装与计费 9 项测试通过；
Core 政策及架构检查 44 项通过（监听端口的用例在获准的权限下复核）。
Core 的 12 项定向验收及 6 项独立依赖重启检查通过，测试资源已清理，证据位于
`.local/test-runs/20260908t042054z-7668-c062ed1c/`。
Agent 集成首次为 93 项通过、3 项失败：两项原有卡片文案断言，另有一次多步
工具循环超过 5 秒。工具循环定向复测的 2 项通过，未将这次通过视作超时问题
已解决。完整详情为 `/private/tmp/thesistrace-central-quota-agent.json`。
