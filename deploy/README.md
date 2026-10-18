# Production deployment

Run repository commands with the versions in `.mise.toml`. Verification selection and
entrypoints are documented in [AGENTS.md](../AGENTS.md#testing).

The canonical production origin is `https://qagentis.com`, with MCP at
`https://qagentis.com/mcp` and the model gateway at `https://api.qagentis.com/v1`.
Production mail is sent as `QAgentis <noreply@qagentis.com>` after Resend verifies
its DNS records. `www.qagentis.com` and the former `thesistrace.com` website redirect
to the canonical origin; clients must use the canonical MCP URL and authorize again.

`THESISTRACE_PUBLIC_ORIGIN` is the single source for the public origin, Auth base URL,
trusted origins, MCP issuer/resource and host/origin allowlists. Change the private
production configuration, not derived variables. The Turnstile widget must authorize
`qagentis.com`; the Auth service also verifies that exact hostname. Keep the primary
site, `www` and `api` DNS records proxied, mail validation records DNS-only, and use
Cloudflare Full (strict) once Caddy has obtained valid origin certificates.

Production reads one authoritative, root-owned, mode-600 configuration file outside
this checkout. It does not merge the development `.env` with a production file.
Initialize a new deployment on the server as root:

```sh
install -d -m 700 /etc/thesistrace /etc/thesistrace/caddy
THESISTRACE_ENV_FILE=/etc/thesistrace/production.env pnpm config:init --production
```

Fill the public HTTPS origin, immutable release image tags/build revision, external
service credentials, verified sender and model HTTPS base URL in that file. The
initializer generates independent database, storage and signing secrets, refuses to
overwrite an existing file, and leaves deployment-specific inputs empty. Preserve
these secrets on subsequent deployments. Never commit or bake this file into images.

```sh
THESISTRACE_ENV_FILE=/etc/thesistrace/production.env pnpm prod validate
THESISTRACE_ENV_FILE=/etc/thesistrace/production.env pnpm prod up
pnpm prod status
```

The production Compose overlay fixes three ordinary Research Workers and two
Batch Research Workers for the 6-vCPU, 12-GB server. Each worker retains the
configured CPU, memory, and execution limits; development keeps one of each.
Publication cleanup runs in one separate `publication-maintenance-worker`, capped
at 0.5 CPU and 256 MiB, without Dataset mounts. PostgreSQL coordinates duplicate
instances. It drains at most ten explicit deletions per step and scans at most one
1,000-object page per minute, resting at least fifteen minutes after a full sweep.
Product Workers do not list objects while idle. Structured maintenance events
report counts, duration, backoff, full-sweep age and oldest queued-deletion age.
The heartbeat health check proves the loop is alive; inspect failed step events
separately for storage access or backlog problems. This release requires
[explicit migration 0002](../docs/database-migrations.md#0002-bounded-publication-maintenance).

The production web container publishes ports 80 and 443 and persists Caddy's public
origin certificates in `caddy-data`. With Cloudflare DNS proxying enabled, use
Full (strict) after the origin certificate is issued. Only Cloudflare's documented
IPv4/IPv6 ranges are trusted to supply `CF-Connecting-IP`; direct requests cannot
replace their source address with that header. Update the range list from
[Cloudflare](https://www.cloudflare.com/ips/) when Cloudflare changes it.

Additional operator-owned Caddy sites can be placed in `/etc/thesistrace/caddy/*.caddy`.
This directory is mounted read-only; keep it root-owned. For this Contabo deployment,
`api.qagentis.com` routes only model API paths to an independently deployed
CLIProxyAPI container on the `thesistrace_default` network. The gateway has no
published ports; its API key and model account files live outside the checkout.
Stop the gateway before `pnpm prod down`, because it also uses that network. Restart
it after the product network is recreated. Normal product container updates preserve
the network.

Paid model calls reserve the configured context-window input ceiling plus the
requested output allowance before dispatch. They settle against the provider's
actual token usage, including configured cache prices. No token-count endpoint is
required: gateway estimates can omit provider-added input. The configured model
capacity must bound provider usage. A small remaining daily budget can reject a
call whose eventual cost would be lower; interrupted calls without final usage
retain their reservation. The GPT-6 Sol and Luna prices in
`apps/agent/config/model-registry.json` use the published Standard short-context
rates. Their configured input ceilings stay below the 272K-token long-context
pricing threshold, and each maximum reservation fits the ordinary $1 daily
model budget. Subscription calls are not treated as free.

For an existing local research dataset, copy a consistent Canonical and benchmark
snapshot into the server's new data volumes before starting data updates. Verify the
archive checksum and mounted Dataset Head on the destination. Initialize the server's
product databases independently; research data transfer does not require copying
local accounts, sessions or user results. Never overwrite an active Dataset Head or
copy a live PostgreSQL data directory.

Publication 孤儿维护每分钟最多检查一页 1,000 个对象，一轮完成后休息 60 分钟；明确删除队列仍独立运行。延长休息时间会推迟遗留对象的回收，不延迟研究结果发布。

邮箱登录的发码入口必须通过 Cloudflare Turnstile。创建 Managed widget 并添加实际访问域名，把站点密钥和服务端密钥分别写入私有部署配置的 `THESISTRACE_TURNSTILE_SITE_KEY`、`THESISTRACE_TURNSTILE_SECRET_KEY`；服务端密钥不能进入 Git 或前端构建。服务端严格校验当前 `THESISTRACE_PUBLIC_ORIGIN` 的 hostname 和 `sign-in-code` action。生产环境只允许官方 Siteverify 地址，不接受测试密钥或本地验证服务。

每个邮箱使用独立的固定窗口：60 秒内 1 封、每小时 5 封、每天 10 封；IP 每分钟 5 次请求，IPv6 按 `/64` 合并。全站发码默认为每小时 25 封、每天 100 封，分别由 `THESISTRACE_EMAIL_CODE_GLOBAL_HOURLY_LIMIT` 和 `THESISTRACE_EMAIL_CODE_GLOBAL_DAILY_LIMIT` 配置。达到全站上限记录 `auth_email_code_budget_reached` 日志，可接入运维告警。额度在数据库中原子预留，重启仍有效；发送失败也保留预留，限制失败重试产生的消耗。拒绝请求不会刷新验证码或延长邮箱冷却，验证失败只消耗 IP 请求额度。Operator 证明码仍走独立的已认证流程。相关验证入口见仓库根 [AGENTS.md](../AGENTS.md#testing)。

## Payment launch preparation

The `/terms`, `/privacy`, `/refunds` and `/pricing` pages contain the current bilingual
service policies and must remain accessible without a login or a working Auth API.
The operator is Zhu Chenglei (朱城磊); support and privacy requests go to
`koltenluca433@gmail.com`. Before merchant review, deploy the policy version so these
URLs are accessible at `https://qagentis.com`. Policy metadata is not proof of
production deployment or payment eligibility. The current Contabo instance is in
EU (Germany); confirm any required correspondence address. See [policy facts and remaining
boundaries](../docs/public-policies.md).

While merchant verification is pending, retain the payment-disabled values in
[payment-disabled.env.example](payment-disabled.env.example). This is a reference
fragment, not a replacement for the existing private production file. Disabled mode
requires all Creem credentials, product IDs and API override fields to be empty.
Do not copy Test Mode credentials into a live deployment.

Prepare a candidate from `main`, validate the applicable boundaries using
[AGENTS.md](../AGENTS.md#testing), then merge `main` into `codex/contabo-deployment`.
Record the deployed revision and immutable image references. Before any required
schema change, identify the actual source version, take and verify backups, stop
writers and follow the exact [versioned migration](../docs/database-migrations.md).
Preserve the Agent model-settlements volume with database backups. A rollback must
restore a matching schema and images; payment disabling is not a schema rollback.

Once the merchant is eligible for live payments, configure its separate Live Pro
and Max products using the [billing contract](../docs/creem-billing.md#商户配置).
Set the restricted configuration to `THESISTRACE_CREEM_MODE=live` with the Live API
key, Live webhook signing secret and the two distinct Live product IDs. Keep
`THESISTRACE_CREEM_API_ORIGIN` empty to select the official API. The receiver is
`https://qagentis.com/api/auth/billing/webhook`; the return URL is
`https://qagentis.com/billing?payment_return=1`. Merchant cancellation must end at
the period boundary, and Product Bundle self-service upgrades/downgrades must be off.

Use `THESISTRACE_ENV_FILE=/etc/thesistrace/production.env pnpm prod validate`
before applying the deployment. Auth also checks payment settings at startup and
validates products when used; configuration validation alone is not live-payment
qualification. Keep the webhook reachable without login or a browser challenge,
while retaining signature verification. Do not exempt unrelated site routes from
security checks or rely on source-IP allowlists for webhook authentication.

Before opening paid checkout, retain evidence of the candidate revision, migration
receipts, verified policy/contact links, webhook delivery and a user-operated real
payment that becomes the expected entitlement. Observe failed callback processing,
reconciliation errors, unresolved financial commands and the model-settlement backlog;
record who receives alerts and handles support. Replay failed inbox events only via
the existing [billing maintenance commands](../docs/creem-billing.md#维护与恢复).
Never retry an unknown-outcome financial mutation with a new request ID.

For a payment incident, close new financial requests without discarding events or
credentials needed to reconcile existing subscribers; investigate the documented
billing state before choosing containment. `disabled` is the pre-launch state, not
a blanket operational rollback for a store with active subscriptions.
