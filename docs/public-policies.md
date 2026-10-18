# QAgentis 公开政策

当前文案生效日期：2026-10-18。中英文公开正文统一维护在 [`content.ts`](../apps/web/src/legal/content.ts)，由 [`PolicyPage.tsx`](../apps/web/src/legal/PolicyPage.tsx) 展示。本文只记录资料依据和上线边界，不复制另一份正文。

| 地址 | 内容 |
| --- | --- |
| `/terms` | 服务条款，个人运营者、使用范围、计量、订阅和责任边界 |
| `/privacy` | 隐私说明，处理者、用途、服务商、跨境处理、保留和请求流程 |
| `/refunds` | 退款与取消，人工审核、付款渠道、权益及续费的关系 |
| `/pricing` | 套餐与额度，USD 月付、税费另计及 AI 用量参考 |

各页支持 `?lang=zh` 和 `?lang=en`，无需登录即可访问。首页底部、账单页和政策页导航提供入口。

## 已确认资料

- 个人运营者：朱城磊（英文展示 Zhu Chenglei），不虚构公司名称或注册信息。
- 支持及隐私邮箱：`support@qagentis.com`。
- 托管基础设施：Contabo EU（德国）；AI 上游：OpenAI，由运营者确认。Resend 和 Cloudflare Turnstile 分别用于验证码投递与登录防滥用，Cloudflare Email Routing 将域名支持邮件转发至 Google Gmail 收件箱。
- 研究与 AI 额度、订阅和退款规则以[支付契约](creem-billing.md)及唯一额度配置为依据；当前 Pro AI 每日配置额度为 $1.5。
- Auth 安全审计记录通常保留 180 天，到期会由现有清理任务删除。认证和验证记录按到期情况清理。其他数据依据服务需要、账户状态、会计义务和争议处理决定保留，不虚构统一删除时限或即时备份删除能力。
- 不承诺 OpenAI 在所有服务和账户设置下均零保留或不用于训练；对应服务的实际条款与设置仍需核对。

## 部署地区与上线边界

2026-10-18 在运营者登录后的 Contabo 控制台核实实例 `vmi3564117` 的 Region 为 `EU`。结合 [Contabo 官方 API 区域定义](https://api.contabo.com/)中 `regionSlug: EU` 对应 `European Union (Germany)`，将当前服务器和数据库托管地区披露为德国。这是实例地区与官方定义的对应结论，不是根据托管商总部推测；也不代表 OpenAI 等第三方的处理全部位于德国。

公开文案未虚构住宅或办公地址。Creem 审核所需的真实地址由运营者在平台填写；若适用规则要求公开送达地址，应另补可用的正式联系地址。个人商户的登记、税务及平台资格取决于适用规则和 Creem 审核结果；文案定稿不等于商户已获准收款。

政策版本与支付启用分别交付：正式文案进入 `main` 后仍需部署到 `qagentis.com`，让审核方访问公开 URL。Live 密钥、HTTPS Webhook、生产配置与真实付款验收仍按[部署说明](../deploy/README.md#payment-launch-preparation)完成；页面生效日期不能作为已部署或支付已启用的证据。

文案验证与浏览器入口见 [AGENTS.md](../AGENTS.md#testing)。

## 外部依据

- [Creem 商户条款](https://www.creem.io/terms)：支持自然人或法人商户，并划分 MoR 与产品运营者责任。
- [Creem 购买条款](https://www.creem.io/buyer-terms)与[隐私政策](https://www.creem.io/privacy)。
- [OpenAI 隐私政策](https://openai.com/policies/privacy-policy/)及[业务数据说明](https://openai.com/business-data/)。
- [Resend 隐私政策](https://resend.com/legal/privacy-policy/)。
- [Contabo API 区域定义](https://api.contabo.com/)与 [Google 隐私政策](https://policies.google.com/privacy)。

本文不声明所有目标地区的法律要求均已满足，也不替代实际部署、供应商授权或商户资格核验。
