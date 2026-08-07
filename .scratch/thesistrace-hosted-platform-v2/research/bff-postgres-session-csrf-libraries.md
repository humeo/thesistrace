# BFF PostgreSQL Session 与 CSRF 方案调研

检查日期：2026-08-03

## 结论

对 ThesisTrace Hosted V2，推荐**不引入完整认证框架、通用 Session 中间件或现成 CSRF 包**，而是在 Control API 内实现一个边界很窄的 `AuthSession` 模块，并复用仓库已有技术栈：

- PostgreSQL + `psycopg`：保存可撤销的服务端会话；
- Python `secrets` / `hashlib` / `hmac.compare_digest`：生成 opaque session ID、只保存摘要并做常数时间比较；
- `cryptography` 的 Fernet/MultiFernet：加密 InsForge refresh token，并支持密钥轮换；
- `httpx`：以 `client_type=server` 调用 InsForge Auth；
- Starlette/FastAPI 原生 Cookie 与依赖注入接口：发 Cookie、加载会话、保护路由。

原因不是“没有成熟库”，而是成熟库解决的边界与这里不同：

1. 身份提供者已经确定为 InsForge，不能再引入一套用户注册、密码重置和身份模型；
2. 浏览器 Cookie 必须只是无意义的 opaque ID，完整会话和上游 token 必须留在 PostgreSQL；
3. CSRF 必须绑定到具体服务端 session，并同时执行严格 `Origin`/`Referer` 校验；
4. 登出、过期、会话轮换和加密后的 InsForge token 生命周期必须在一次本地事务中协调。

现有库至多能省掉少量 Cookie/middleware 胶水，却仍要自定义 PostgreSQL store、session ID 摘要、token 加密、InsForge 刷新、CSRF 绑定和严格 Origin；引入后反而形成两套生命周期模型。

## 当前项目约束

仓库当前锁定：

- Python `>=3.12`；
- FastAPI `0.141.1`；
- Starlette `1.3.1`；
- Pydantic `2.13.4`；
- `psycopg` `3.3.4`；
- `httpx` `0.28.1`；
- `PyJWT[crypto]`，其依赖树已包含 `cryptography`。

依据：`pyproject.toml` 与 `uv.lock`。如果代码直接 import `cryptography`，应把它提升为 `pyproject.toml` 中的显式直接依赖，而不是依赖传递安装。

本仓库内固定的 InsForge v2.2.9 源码还表明：

- 非 Web 客户端可用 `client_type=server`，refresh token 通过响应体返回、刷新时通过请求体提交；
- access token 有效期 15 分钟，refresh token 有效期 7 天；
- refresh 会返回新的 refresh token，但旧 token 没有服务端撤销记录；
- `client_type=server` 的 logout 没有可撤销的上游服务端会话，实际语义是客户端丢弃 token。

依据：

- `.hosted/insforge-v2.2.9/backend/src/api/routes/auth/index.routes.ts`
- `.hosted/insforge-v2.2.9/backend/src/infra/security/token.manager.ts`

因此 ThesisTrace 的 PostgreSQL session 才是浏览器会话的即时撤销边界。登出时应撤销本地 session、删除其 token ciphertext 并清 Cookie；已签发的 InsForge token 无法被当前上游接口即时吊销，只能等待其自身到期。这个限制需要写入威胁模型和运维文档。

## 候选方案比较

| 候选 | 维护状态 / 当前兼容线索 | PostgreSQL opaque session / 撤销 | 会话绑定 CSRF + strict Origin | 与 InsForge 集成成本 | 判断 |
|---|---|---|---|---|---|
| Starlette `SessionMiddleware` | 官方维护，当然兼容当前 Starlette | 否。官方定义为**签名 Cookie 会话**；内容在客户端，可读不可篡改，不是 PostgreSQL 服务端会话 | 不提供 | 仍需另写全部服务端状态 | 不采用 |
| FastAPI Users + DB strategy | PyPI 15.0.5（2026-03-27）；项目明确处于 maintenance mode，只做安全和依赖维护 | 有数据库 token strategy 和 destroy，但官方 SQLAlchemy adapter 以**原始 token 为主键**，并引入 SQLAlchemy async；数据模型不覆盖本项目 token 加密和 CSRF | Cookie transport 文档明确提醒 CSRF 风险，但不实现本项目要求的同步 token + strict Origin | 高；它还拥有 user manager、注册、验证、重置等身份流程，会与 InsForge 重叠 | 不采用 |
| Starsessions | stable 2.2.1（2024-10-23）；2.3.0a1（2026-03-16）仍是预发布；metadata 对 Starlette 无严格上限，但没有证明已针对 1.3.1 验证 | 内建 memory/cookie/Redis，无 PostgreSQL；可写自定义 store，支持 session regenerate | 不提供本项目 CSRF/Origin 组合 | 中高；关键 store 和安全语义仍需自行实现 | 可作通用 Session 抽象备选，但不推荐 |
| fastapi-sessions | GitHub 于 2023-12-06 archived，README 明示不再维护 | 可扩展 backend，但没有值得依赖的维护线 | 不解决 | 不应新增归档依赖 | 排除 |
| `asgi-csrf` | 0.11（2024-11-15）；仍有公开源码和发布包 | 不负责 session | 实现的是签名 double-submit token，不绑定 PostgreSQL session；不做 strict Origin；默认还会对“无 Cookie”请求及 Bearer Authorization 请求跳过检查 | 需要大量配置和例外审计，仍与目标模型不同 | 不采用 |
| `fastapi-csrf-protect` | stable 1.0.7（2025-09-16）；支持 Pydantic 2；Starlette metadata 约束过宽，不能视为对 1.3.1 的明确验证 | 不负责 session | stateless double-submit，不绑定服务端 session，也不负责 strict Origin | 仍需另写核心逻辑和全局配置/DI | 不采用 |
| Authlib | 1.7.2（2026-05-06）；活跃 OAuth/OIDC 库 | 不负责应用 session | 不负责本项目 CSRF | InsForge 当前供 BFF 使用的是直接 Auth HTTP API，而不是本范围内已验证的标准 OIDC provider contract；Authlib 解决不了核心问题 | 不采用 |

### 为什么不用 Starlette `SessionMiddleware`

Starlette 官方文档明确称其为 “signed cookie-based HTTP sessions”，并说明数据对客户端可读但不可修改。它适合低敏感度的小型 Cookie session，不符合“浏览器只持 opaque ID、服务端 PostgreSQL 保存状态、支持即时吊销”的约束。`HttpOnly`、`Secure` 和 `SameSite` 只是 Cookie 属性，不能把客户端会话变成服务端会话。

来源：[Starlette Middleware - SessionMiddleware](https://www.starlette.io/middleware/#sessionmiddleware)

### 为什么不用 FastAPI Users

FastAPI Users 的数据库策略确实提供 token 创建、读取和删除，Cookie transport 也能设置 `Secure`、`HttpOnly`、`SameSite`、path/domain。但它的抽象中心是“FastAPI Users 自己的用户和认证后端”，不是“InsForge 为唯一 IdP，BFF 只维护代理会话”。官方 SQLAlchemy access-token adapter 直接以 token 字符串作为主键查询，既不满足数据库中只留 session 摘要，也不覆盖：

- InsForge refresh token 加密；
- refresh rotation 的原子替换；
- idle + absolute expiry；
- session-bound CSRF；
- strict Origin；
- BFF 本地撤销与上游 token 到期差异。

为了补齐这些内容，需要改写其核心 adapter/strategy，收益小于直接实现窄模块；同时项目已进入 maintenance mode，不宜把 Hosted V2 的核心身份边界建立在它的扩展面上。

来源：

- [FastAPI Users authentication](https://fastapi-users.github.io/fastapi-users/latest/configuration/authentication/)
- [FastAPI Users cookie transport](https://fastapi-users.github.io/fastapi-users/latest/configuration/authentication/transports/cookie/)
- [FastAPI Users database strategy](https://fastapi-users.github.io/fastapi-users/latest/configuration/authentication/strategies/database/)
- [FastAPI Users repository](https://github.com/fastapi-users/fastapi-users)
- [FastAPI Users SQLAlchemy access-token adapter](https://github.com/fastapi-users/fastapi-users-db-sqlalchemy/blob/main/fastapi_users_db_sqlalchemy/access_token.py)
- [FastAPI Users on PyPI](https://pypi.org/project/fastapi-users/)

### 为什么不用 Starsessions

Starsessions 是候选中最接近“通用服务端 Session middleware”的库：它支持自定义 SessionStore、Cookie 属性、rolling session 和 session regeneration。但内建 store 没有 PostgreSQL。写完项目需要的 psycopg store 后，仍要额外实现：ID 摘要、token 加密、CSRF 摘要、Origin、InsForge refresh 事务和撤销语义。也就是说，它留下的仅是 request/session 字典和 Cookie 胶水；这不足以抵消新增依赖与隐藏 middleware 生命周期的成本。

若后续出现多个 ASGI 应用共享同一种 session store 的明确需求，可以重新评估 Starsessions；当前单 Control API 不需要先抽象这个层。

来源：

- [Starsessions repository](https://github.com/alex-oleshkevich/starsessions)
- [Starsessions on PyPI](https://pypi.org/project/starsessions/)

### 为什么不用现成 CSRF 包

OWASP 对有服务端状态的软件首推 synchronizer token pattern：token 由服务端生成、保存在 session 中，并在每个改变状态的请求上比较。double-submit cookie 主要用于无状态场景；若采用 signed double-submit，也必须明确绑定用户 session。

`asgi-csrf` 与 `fastapi-csrf-protect` 的主要模型都是 stateless double-submit。它们不是“不安全”，但和已经选择的 PostgreSQL stateful session 不同；再加 strict Origin 后，仍需写一层项目级保护逻辑。直接实现 synchronizer token 更短、更容易证明每条约束成立。

来源：

- [OWASP Cross-Site Request Forgery Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- [`asgi-csrf` repository](https://github.com/simonw/asgi-csrf)
- [`asgi-csrf` on PyPI](https://pypi.org/project/asgi-csrf/0.11/)
- [`fastapi-csrf-protect` repository](https://github.com/aekasitt/fastapi-csrf-protect)
- [`fastapi-csrf-protect` on PyPI](https://pypi.org/project/fastapi-csrf-protect/)

## 推荐的窄实现

### 1. PostgreSQL 会话记录

建议一条 session 至少包含：

```text
session_id_hash             primary key
user_id                     ThesisTrace 用户标识
insforge_subject            上游身份标识
insforge_refresh_ciphertext 加密后的 refresh token
csrf_token_hash             当前 session 的 CSRF 摘要
created_at
last_seen_at
idle_expires_at
absolute_expires_at
revoked_at                  nullable
```

可把短期 access token 作为进程内缓存或加密的短期字段处理；不要明文持久化。关键不变量是：数据库中没有可直接放进浏览器 Cookie 的原始 session ID，也没有明文上游 refresh token。

### 2. Session ID 与 Cookie

- 使用 `secrets.token_urlsafe(32)` 生成至少 256 bit 随机输入；
- 浏览器持有原始 ID，数据库只存其 SHA-256/HMAC 摘要；
- 生产 Cookie 名使用 `__Host-...` 前缀，设置 `Secure; HttpOnly; Path=/` 且不设置 `Domain`；
- 明确设置 `SameSite=Lax`（若产品流程验证可接受，Strict 可更强，但不能替代 CSRF）；
- 登录成功或身份/权限发生变化时必须生成新 session，不能沿用登录前 ID；
- logout、idle expiry、absolute expiry、管理员撤销都在服务端使记录失效，并清除浏览器 Cookie。

OWASP 建议 session ID 至少具备 64 bit 熵、无业务含义，并由 CSPRNG 生成；自定义 ID 建议至少 128 bit。Python `secrets` 专门提供适用于密码学用途的安全随机 token。

来源：

- [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
- [Python `secrets`](https://docs.python.org/3/library/secrets.html)

### 3. 上游 token 加密与 refresh rotation

- 用 Fernet 加密 refresh token，密钥只来自部署 secret，不放在数据库；
- 使用 MultiFernet 支持“新密钥加密、旧密钥解密”的渐进轮换；
- 调用 InsForge refresh 成功后，在同一数据库事务中用新 ciphertext 替换旧 ciphertext；失败时不能先删除旧 token；
- 并发刷新应通过行锁或 compare-and-swap 串行化，避免两个请求互相覆盖；
- 日志不得记录 Cookie、session ID、CSRF token、access/refresh token 或 ciphertext；需要关联时只记录带独立日志盐的摘要。

Fernet 为小型消息提供认证加密，MultiFernet 是官方提供的密钥轮换机制，适合这里的 refresh token 尺寸和生命周期。

来源：[Cryptography Fernet / MultiFernet](https://cryptography.io/en/latest/fernet/)

### 4. Session-bound CSRF

在创建 session 时同时生成独立随机 CSRF token：

- 明文只在登录/获取当前 session 的 JSON 响应中交给 SPA，不放入 HttpOnly session Cookie；
- 数据库仅在该 session 行保存 CSRF 摘要；
- SPA 对 `POST`、`PUT`、`PATCH`、`DELETE` 等 unsafe method 发送 `X-CSRF-Token`；
- 服务端先加载 session，再比较该行绑定的 token 摘要；不同 session 的 token 必须失败；
- 比较使用 `hmac.compare_digest` / `secrets.compare_digest`；
- session rotate、logout 或到期后，旧 CSRF token 自动失效。

这就是 OWASP 的 synchronizer token pattern，和 PostgreSQL stateful session 一一对应。

### 5. Strict Origin / Referer

对所有 unsafe request（包括登录、注册、恢复、logout）执行：

1. 若有 `Origin`，必须与配置中的 public origin 做 scheme + host + port 的**精确匹配**；
2. 若没有 `Origin`，才使用 `Referer` 的 origin 做同样精确匹配；
3. 两者都没有或不匹配，一律 `403`；
4. 目标 origin 使用部署配置值，不根据 `Host`、`X-Forwarded-Host` 动态推断；Caddy 反代场景下，错误或未受信任的 forwarded header 不应改变安全判断。

Cookie-based BFF 的 SameSite 只是纵深防御，不能替代 CSRF token 或 Origin 检查。登录前没有正式 session 时，至少仍要严格 Origin + JSON/custom header；如果威胁模型要求防御更强的 login CSRF，可增加短期 pre-session token，登录成功后必须丢弃并轮换成正式 session。

来源：[OWASP CSRF Prevention Cheat Sheet - Verifying the origin](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html#verifying-the-origin-with-standard-headers)

## 最小公开接口

为了避免“自研认证框架”，内部模块只需要少量明确操作：

```python
create_session(identity, encrypted_upstream_tokens) -> SessionCookieAndCsrf
load_active_session(raw_cookie) -> AuthSession | None
require_csrf(session, request) -> None
rotate_upstream_tokens(session, new_tokens) -> None
revoke_session(session) -> None
revoke_all_user_sessions(user_id) -> int
```

路由层不应直接查询 session 表或自行解析 Cookie；InsForge client 也不应接触浏览器响应。这样能把三条边界保持清楚：

- Browser ↔ Control API：opaque Cookie + session-bound CSRF；
- Control API ↔ PostgreSQL：摘要、过期、撤销和 ciphertext；
- Control API ↔ InsForge：server client token exchange，token 永不下发给浏览器。

## 验收门槛

实现前应把以下测试列为不可删减的安全契约：

1. 生产和 local Cookie 属性分别准确，生产为 `__Host-` + `Secure` + `HttpOnly` + `Path=/` + 无 `Domain`；
2. 原始 session ID 和 refresh token 不出现在数据库、响应体、日志或错误信息中；
3. 仅有 session 表泄漏内容不能伪造 Cookie；
4. logout、revoked、idle expired、absolute expired 的 Cookie 均不可恢复会话；
5. 登录/权限变化后旧 session ID 失效；
6. unsafe request 对缺失/错误/cross-session/已撤销 CSRF token 全部 `403`；
7. 错误 Origin、缺失 Origin+Referer、相似后缀域名、错误端口全部 `403`；
8. refresh rotation 并发时只产生一个可提交的新状态，失败不会丢失仍有效的旧 token；
9. InsForge 不可用时不意外撤销本地会话，也不把上游错误或 token 暴露给浏览器；
10. 本地 session 已撤销但尚未到期的 InsForge JWT/refresh token 风险被测试和文档明确标注。

## 最终决策

**采用窄内部实现；不新增 auth/session/CSRF 框架。**

唯一建议新增的直接依赖是 `cryptography`（实际上已由 `PyJWT[crypto]` 传递安装），用于 refresh token 的认证加密和密钥轮换。其余所需能力已经存在于 Python 标准库、FastAPI/Starlette、`psycopg` 与 `httpx` 中。

如果未来出现“多个独立 ASGI 服务必须共享统一 session middleware/store”的真实需求，再以 Starsessions + 自定义 PostgreSQL store 为首个重新评估对象；不要为当前单 Control API 提前引入这一层。
