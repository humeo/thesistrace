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

`/terms`、`/privacy`、`/refunds`、`/pricing` 为无需登录的中英文公开政策页，当前文案生效日期为 2026-10-18，个人运营者为朱城磊，支持及隐私联系邮箱为 `support@qagentis.com`。已确认的服务商、保留依据和 Contabo EU（德国）实例地区见[公开政策资料](public-policies.md)。正式文案进入 `main` 不代表已部署或已完成商户审核。

上线前还需商户审核、对外商户名称、支持邮箱、公开服务条款 / 隐私及退款说明、数据供应商授权、Live 商品 / 密钥 / HTTPS Webhook 和部署验证。未配置或未验证的外部事项不能据本地或 Test Mode 测试宣称已完成。

Pro 每月 $20，但按 $1.5 AI 日预算满额使用 30–32 个额度日对应 $45–48 配置成本；当前价格是用户已确认的补贴策略，不随支付实现调整。

Agent 的 `model-settlements` 持久卷保存已结束模型调用的待入账决定（预留 ID、实际金额或最终未知吸收），不保存模型内容。PostgreSQL 暂不可写时保留该记录并重试，恢复后先入账再接纳新调用；服务重启先重放已知费用，再吸收旧主机中断且最终未知的预留。备份/恢复 PostgreSQL 时也必须保留对应持久卷，禁止把该卷当缓存清理。容器固定使用 `/app/agent/state/model-settlements.sqlite`，运行用户为 node。

“正在确认付款”来自具体未完成命令或已请求的升级付款，不根据续费商品与当前权益的差额推断。全额退款或争议撤权后仍可查看账单、取消续费；重新应用已存在的同一商品不会产生付款，应用明确提示先处理该订阅的付款问题。对账每轮也更新失败或缺少第三方标识的旧命令的检查时间，避免阻塞其他用户的恢复。

## 商户审核访问与支持

公开支持与隐私邮箱统一为 `support@qagentis.com`，显示在首页、政策页和账单页。Cloudflare Email Routing 转发至运营者的已验证 Gmail 收件箱；Resend 的已验证域名支持以该地址发信。2026-10-18 已在 Gmail 完成该发件身份的地址验证，使用 `smtp.resend.com:587` / TLS 和仅限 qagentis.com 发信的独立凭据，回复设置为使用收件时的相同地址。Gmail 发件身份测试邮件已进入运营者自己的收件箱。[Google 已公告](https://support.google.com/mail/answer/22370) 2027 年 1 月起停止第三方地址的 Send as，需在此前改用支持 SMTP 的邮件客户端或其他邮箱服务。

审核人员可在 `https://qagentis.com/login` 使用自己的邮箱接收验证码并注册；无需共享运营者账户或密码。Free 与付费档包含同样的研究工具，可体验研究、历史回测、AI 辅助分析和模拟跟踪；配额较低。外部 Agent 的 MCP 连接同样只提供研究能力。实际权限和用量以登录后的账单页为准。

Creem 可能使用一次性 100% 折扣进行有限审核。零金额账期仍需官方验签及服务端交易、客户、商品、币种、模式和账期校验，不能通过跳转或 Checkout 完成直接发放权益。Auth 0004 显式迁移见[数据库迁移](database-migrations.md#auth-0004-verified-zero-value-subscription-periods)。生产支付在商户审批及 Live 配置完成前保持关闭；隔离 Fake、真实 Test Mode 与生产支付的验证结果必须分别记录。工程验证入口统一见 [AGENTS.md](../AGENTS.md#testing)。

自动聊天标题在主轮次形成终态后才异步生成；标题请求仍计入 AI 预算，但其预留不得与该轮主回复争抢额度或延迟终态。主回复期间不会为了标题另行预留费用。

## 发给 Creem 的类别确认说明（待运营者发送）

Subject: Product eligibility pre-check — QAgentis quantitative research SaaS

Hello Creem team,

I operate QAgentis as an individual and would like to confirm product eligibility before submitting the account review.

Store: qagentis (`sto_2fDr2Uer3O1oFbsJB0acKa`)
Website: https://qagentis.com
Contact: support@qagentis.com

QAgentis is a self-service quantitative research SaaS. Users inspect historical market data, evaluate factor expressions, run historical strategy backtests, and track simulated portfolios over subsequent trading days. Results include research statistics, simulated holdings and performance, with the relevant formulas and assumptions.

OpenAI powers text-based research assistance, including drafting research code and explaining results. Users may also connect an external AI agent through MCP to run research and read results. QAgentis has no broker or exchange account connections, does not route or execute live orders, does not automate real-money trading, and does not hold investment funds or promise returns. It does not provide image/video generation. Subscriptions purchase software access; we do not sell trading courses or community memberships.

Free provides limited daily access to the same research tools. Pro costs USD 20/month and Max USD 100/month, with applicable taxes added at checkout; paid tiers increase research, tracking and metered AI allowances. This is a new business without prior paid-customer processing history; I cannot provide an established chargeback/refund track record.

Could you confirm whether this research-only product is eligible as SaaS, is restricted, or is unsupported under your trading/investment and generative-AI rules? If restricted, what additional evidence is required from a first-time merchant?

Terms, privacy, refunds and pricing are publicly linked from the website. Reviewers can register with their own email and use Free. Live checkout remains disabled pending approval and final Live integration. Please also confirm the access you require before approval, and how your one-time 100% discount test should be arranged if live checkout cannot yet be enabled. In Test Mode, creating a one-use 100% Pro discount in the dashboard returned a generic save error and no discount was created; please advise whether this is supported for a pending-review store.

Thank you,
QAgentis

### 中文版本

主题：QAgentis 量化研究 SaaS 的产品准入类别确认

Creem 团队您好：

我是 QAgentis 的个人运营者，希望在提交账户审核前确认产品是否符合准入要求。商店名称为 qagentis，商店 ID 为 `sto_2fDr2Uer3O1oFbsJB0acKa`，网站为 https://qagentis.com，联系邮箱为 support@qagentis.com。

QAgentis 是自助式量化研究软件。用户可以查看历史市场数据、评估因子表达式、运行历史策略回测，并在后续交易日跟踪模拟组合。研究结果包含统计指标、模拟持仓与表现，以及相关公式和假设。

产品使用 OpenAI 提供文字研究辅助，包括协助编写研究代码和解释结果；用户也可以通过 MCP 连接外部 AI Agent，执行研究并读取结果。产品没有券商或交易所账户连接，不路由或执行实盘订单，不提供真实资金交易自动化，不托管投资资金，也不承诺收益。产品不提供图片或视频生成。订阅购买的是软件使用权限，我们不出售交易课程或社群会员。

Free 提供相同研究工具的有限每日额度；Pro 为每月 20 美元，Max 为每月 100 美元，适用税费在结账时另计。付费套餐增加研究次数、模拟跟踪名额和按用量计量的 AI 额度。这是一项新业务，目前没有过往付费客户的收款、拒付或退款记录可供提交。

请确认：此类仅用于研究的软件是否可按 SaaS 接入，属于受限类别，还是不受支持？如果属于受限类别，首次申请的个人商户需要提供哪些额外材料？我们希望明确了解其在交易／投资工具和生成式 AI 规则下的分类。

网站已经公开服务条款、隐私说明、退款与取消说明及套餐页。审核人员可以用自己的邮箱注册并体验 Free。正式结账将在商户获批并完成 Live 配置后启用。请同时说明审核前需要怎样的访问权限，以及在尚未开放 Live 结账时，如何安排一次性 100% 折扣审核体验。我们曾在 Test Mode 尝试创建仅限 Pro、最多使用一次的 100% 折扣，但控制台返回通用保存错误，未创建成功；请告知待审核商店是否支持这一操作。

谢谢！
QAgentis

以上中英文说明均为草稿，尚未发送，不代表 Creem 已认可产品类别。
