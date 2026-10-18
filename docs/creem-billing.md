# Creem 月付订阅

价格和额度的唯一运行配置是 [`quota-policy.config.json`](../apps/auth/src/quota-policy.config.json)。Free 为 $0 / 10 次研究 / 1 个跟踪 / $1 AI 日预算；Pro 为 $20 / 100 次 / 10 个 / $1.5；Max 为 $100 / 500 次 / 50 个 / $2。按 USD 月付，税费另计。研究及 AI 额度按北京时间零点重置，变更套餐或续费不重置已用量。

## 所有权与计量

Auth Billing 保存 Researcher 与 Creem Customer / Subscription 的关联、经过验签的事件收件箱，以及逐笔付款支持的权益。`subscription.paid` 还需核验对应交易、商品、币种、账期与归属，才形成权益。跳转成功页、Checkout 完成、订阅状态 active 或当前账单商品都不能单独开通付费额度。重复事件和乱序事件不重复发放，未完成处理的收件箱可重放。

Core 持有研究次数与跟踪选择。研究准入预占，Run 最终失败或开工前取消释放；开工后主动取消计次。Batch 每个子 Run 各计一份。账本保留原准入时间，历史删除和跨日失败不会改变新一天的额度。

跟踪是持续容量。降级保留历史和未选中的跟踪，第一次新推进选择允许继续的对象；选定后不能轮换。释放已选名额需主动 Stop 并等待完成，或升级增加容量。Stop 不可逆。Web、MCP、全部刷新和手动 Retry 共用准入规则，已接受的排队工作及自动恢复继续完成。

Agent 按模型配置 Token 单价记录实际费用。当前调用预留最坏费用上界，结束后结算实际费用；无法核实最终用量的已结束调用由平台承担，迟到用量不追扣。已知用量结算失败时保留预留，不能按未知费用释放。生成、记忆和标题都经过同一计量器。在途、已用、剩余分别显示。

## 套餐与异常账务

升级使用 `proration-charge-immediately`，可靠付款确认后提高额度。降级使用 `proration-none` 立即设置下期账单商品，但保留原高档付款所支持的权益至原到期日；不依赖期末定时器抢在续费前变更。

取消使用 scheduled 模式，本期付费权益保留，到期后回 Free。欠费没有额外宽限，可靠补款仍按付款对应的有效期恢复。Creem 暂时不可访问时，已确认的有效付款权益仍保留至其原到期日。

退款由商户人工审核，在 Creem Dashboard 执行。待处理退款不撤权，确认部分退款保留对应权益，全额退款仅撤销该笔付款的权益。退款和取消续费是独立操作。争议也仅暂停对应付款，不清空其他有效付款或历史。

## 商户配置

默认 `THESISTRACE_CREEM_MODE=disabled`。此时 Free 和已有有效权益仍可用，支付入口显示暂不可用。启用前配置：

- `THESISTRACE_CREEM_MODE=test|live`，显式区分 Test / Live。
- `CREEM_API_KEY`、`CREEM_WEBHOOK_SECRET`，通过受限环境文件提供，不提交仓库或发送到聊天。
- `THESISTRACE_CREEM_PRO_PRODUCT_ID`、`THESISTRACE_CREEM_MAX_PRODUCT_ID`，分别为两个独立商品。
- 商品必须为 USD、every-month、recurring，基础价分别 2000 / 10000 cents，tax_mode=exclusive，无 trial、无 business net pricing。SDK 读取后验证，不接受客户端传金额或 Product ID。
- `THESISTRACE_CREEM_API_ORIGIN` 通常留空，自动选择官方 Test / Live API；只有隔离 test runtime 可使用明确允许的 HTTP Fake 主机。

生产支付统一使用 `https://qagentis.com`：部署配置设置 `THESISTRACE_PUBLIC_ORIGIN=https://qagentis.com`，Checkout 的成功地址由此生成 `https://qagentis.com/billing?payment_return=1`。Creem 商户 Website 使用 `https://qagentis.com`，Pro / Max 商品的 Return URL 使用上述成功地址，公开 Webhook 使用 `https://qagentis.com/api/auth/billing/webhook`。Test / Live 的商品和 Webhook 分开配置；本地 CLI 转发端点不属于公网域名配置。Creem 官方 API 和托管 Checkout / Portal 的 `creem.io` 域名保持不变。

本机连接真实 Test Mode 时，Public Origin 使用 `http://localhost:端口`，Auth、Core、Agent 及 MCP 的 Origin / Issuer / Resource 配置保持一致。2026-10-17 联调中 Creem 明确拒绝 `http://127.0.0.1:端口` 的 success_url。可使用[官方 CLI 本地 Webhook 转发](https://docs.creem.io/code/cli)，签名密钥仅保存于受限本机配置；确定性工程测试仍使用隔离 Fake。支付 SDK 单次请求上限为 15 秒，不自动重试金融写入。

公开 HTTPS Webhook 为 `/api/auth/billing/webhook`，事件至少包括 Checkout 完成、订阅付款及状态变更、退款和争议。处理失败返回失败状态并保留可重放收件箱。托管账单入口复用 Creem 的发票、付款方式及取消功能；套餐变更由本站控制。Product Bundle 的 Self-Service Upgrades/Downgrades 必须关闭，不能让 Portal 绕过本站的降级和补差规则。依据：[Creem Product Bundles](https://docs.creem.io/features/product-bundles)、[Customer Portal](https://docs.creem.io/features/customer-portal)。

## 维护与恢复

所有维护入口使用数据库 owner 身份，不能通过公开 HTTP 或 MCP 调用。先完成 [显式数据库迁移](database-migrations.md)，再启动新版本。

- 重放收件箱：`node apps/auth/dist/billing-maintenance.js replay-event EVENT_ID`。
- 人工确认争议已解决且款项有效后：`node apps/auth/dist/billing-maintenance.js resolve-dispute TRANSACTION_ID --evidence MERCHANT_REVIEW_REFERENCE`。它重新核验交易，仅恢复剩余有效期；审查引用持久保存，旧争议事件不能再次暂停已解决的争议。
- Checkout 请求结果丢失时，先在 Dashboard 找到该 request 对应的 Checkout：`node apps/auth/dist/billing-maintenance.js recover-checkout REQUEST_UUID --checkout CHECKOUT_ID`。命令验证请求与商品，不重发创建或扣款。

- Dashboard / 商户支持已确认请求未执行、没有扣款且不会继续执行时，可用 `node apps/auth/dist/billing-maintenance.js reject-unapplied REQUEST_UUID --evidence MERCHANT_REVIEW_REFERENCE` 完成人工负面确认，之后允许新请求。此入口不会重发金融操作；已存在的 Checkout、目标商品或预约取消会阻止误判。不能仅因等待超时就使用此命令。

回调投影、付款及命令对账、争议恢复和人工未执行确认在同一 Researcher 会话锁下读取 Creem，外部查询完成后才开启短数据库事务。不得在网络请求期间维持数据库事务，也不通过放宽 PostgreSQL idle transaction 限制处理慢响应；连接异常复用现有 Auth coordinator 的保护与销毁路径。

Financial mutation 超时可能已经成功，不能用另一个 request_id 自动重发。后台只读对账确认现有 Checkout、目标商品或预约取消，再完成本地回执。支付 API 明确拒绝与请求尚未发出前的查询失败不按未知扣款处理。

## 上线门槛

确定性验证通过官方 SDK 和隔离 Fake 穿过真实 Auth API、签名回调、付款账本、Core / Agent 额度和浏览器。它不证明真实 Creem Test Mode 的扣款、税务、退款或银行卡认证行为。测试入口与运行规则统一见 [AGENTS.md](../AGENTS.md#testing)。

qagentis 商户 Test Mode 已实测银行卡拒付、Pro 首付、付款支持的 Max 补差升级、预约降级、取消续费、客户门户、发票、逐笔部分 / 全额退款和延迟付款事件重放。测试金额已全部退款，最终回到 Free。自然次月续费 / 到期未等待，真实争议恢复未实测；这些边界仍需区分确定性测试与商户证据。

2026-10-18 已在 qagentis 的 Live 商品目录创建 Pro `prod_sqIE1DFFpFJ7bUhB0KTtl` 和 Max `prod_3SY38JAtVTkBtSKmOPJ6rV`，分别为 USD 20 / 100 月付、SaaS、税费另计、无试用，返回地址为上述 qagentis.com 地址。Live 取消方式已保存为期末取消，目录没有 Product Bundle。创建商品不代表审核通过或网站已启用收款；Live 密钥、Webhook 和实际生产验收仍待完成。

`/terms`、`/privacy`、`/refunds`、`/pricing` 为无需登录的中英文上线前预览页，支持及隐私联系邮箱为 `koltenluca433@gmail.com`。正式运营主体、完整生产隐私事实与生效日期确认前，不得把预览声明移除或视为完成上线审核。

上线前还需商户审核、对外商户名称、支持邮箱、公开服务条款 / 隐私及退款说明、数据供应商授权、Live 商品 / 密钥 / HTTPS Webhook 和部署验证。未配置或未验证的外部事项不能据本地或 Test Mode 测试宣称已完成。

Pro 每月 $20，但按 $1.5 AI 日预算满额使用 30–32 个额度日对应 $45–48 配置成本；当前价格是用户已确认的补贴策略，不随支付实现调整。

Agent 的 `model-settlements` 持久卷保存已结束模型调用的待入账决定（预留 ID、实际金额或最终未知吸收），不保存模型内容。PostgreSQL 暂不可写时保留该记录并重试，恢复后先入账再接纳新调用；服务重启先重放已知费用，再吸收旧主机中断且最终未知的预留。备份/恢复 PostgreSQL 时也必须保留对应持久卷，禁止把该卷当缓存清理。容器固定使用 `/app/agent/state/model-settlements.sqlite`，运行用户为 node。

“正在确认付款”来自具体未完成命令或已请求的升级付款，不根据续费商品与当前权益的差额推断。全额退款或争议撤权后仍可查看账单、取消续费；重新应用已存在的同一商品不会产生付款，应用明确提示先处理该订阅的付款问题。对账每轮也更新失败或缺少第三方标识的旧命令的检查时间，避免阻塞其他用户的恢复。
