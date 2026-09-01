# 01 — Authenticated Chat shell and model catalog

**What to build:** 让登录后的 Researcher 可以从 ThesisTrace 主导航进入独立 Chat 页面，在符合现有设计语言的 Session 型侧边栏中看到 New Chat、位于顶部的 Workspace 链接，以及由私有 Agent Host 提供的系统注册模型与推理强度；该切片建立最终 Agent 服务和路由边界，但尚不创建 Chat Session 或运行模型。

**Blocked by:** None — can start immediately

**Status:** complete

## Implementation Plan

1. Add a private `agent` Node 24/pnpm package with one fail-closed startup
   configuration boundary. Parse and validate the complete model Registry before
   serving traffic, resolve required Provider Secrets only inside the process,
   and expose a safe in-memory Catalog that contains model keys, display names,
   supported reasoning efforts, the default model, and each model's default
   reasoning effort—never Provider identifiers, Secret values, or Secret
   environment-variable names.
2. Implement the Agent Host's first public boundary as a same-origin,
   authenticated Catalog endpoint plus private liveness/readiness endpoints.
   Enforce the exact configured public Origin, verify every browser request by
   forwarding only its Login Session Cookie to Auth's existing private Session
   adapter with a fixed timeout, map invalid/inactive Sessions to 401, and map
   malformed or unavailable Auth responses to a safe fail-closed 503.
3. Add the Agent Host image and service to the existing Compose topology. Give
   it only its public/Auth origins, model Registry, Provider Secrets, and normal
   process configuration; publish no host port. Route the exact Agent API prefix
   through Caddy before the generic Core API matcher, keep `/chat` on the SPA
   fallback, and add Agent build/watch/test configuration without introducing a
   database or Agent execution dependency in this issue.
4. Make `/chat` a protected product route and lazy-loaded standalone page. Add
   Chat to the ordinary product navigation, then build a separate session-style
   Chat shell whose top area is ordered ThesisTrace, New Chat, Data, Research,
   Research Runs, Daily Tracks; whose empty Session region remains distinct from
   Research state; and whose account control stays at the bottom. Fetch the safe
   Catalog, constrain reasoning choices to the selected model, expose no other
   model knobs, and implement the repository design system's desktop collapse
   and mobile drawer as accessible React state rather than a parallel visual
   theme.
5. Add deterministic public-boundary tests for every Registry rejection,
   Session/Origin failure mapping, safe Catalog schema and redaction, route
   recognition/return-to behavior, model-selection constraints, sidebar order,
   desktop collapse, mobile drawer, Caddy route order, private Compose networking,
   and credential isolation. Run the smallest relevant TypeScript and Python
   suites first, then the repository checks required by the touched boundaries
   and a real-browser Caddy acceptance flow.
6. Review the completed diff serially on the repository Standards and this
   ticket's Spec axes, fix every finding, rerun affected acceptance checks,
   re-review to zero findings, mark this ticket complete, and create one
   independent conventional commit containing only Issue 01.

- [x] Chat 成为受现有 SessionGate 保护的一级产品路由；匿名访问保留安全 `returnTo` 后进入登录，登录成功无需整页刷新即可回到 Chat。
- [x] 普通产品侧边栏加入 Chat；Chat 页面使用独立 Session 侧边栏骨架，顶部依次保留 ThesisTrace、New Chat、Data、Research、Research Runs、Daily Tracks，Session 区域位于其下，账号入口位于底部。
- [x] 页面严格使用现有近黑画布、炭灰 Surface、Hairline、紧凑字体、薰衣草焦点与语义状态色，不复制原型的临时 CSS，不保留浅色或第二套 Chat 视觉路径。
- [x] 新增一个私有 Node 24/pnpm Agent Host，并由 Caddy 在通用 Core API 之前代理同源 Agent API；Agent Host 不发布 Host 端口，Caddy 仍是唯一公共监听者。
- [x] Agent Host 在每个浏览器请求上通过现有 Auth 私有 Session 验证获得 Researcher 身份；无效、过期、撤销、Inactive、Auth 超时和错误 Origin 全部失败关闭。
- [x] Agent Host 启动时一次性读取模型 Registry；每项包含稳定 Key、显示名、Provider Adapter、Provider Model ID、支持的推理强度、默认推理强度及所需 Secret 引用。
- [x] Registry 对重复 Key、歧义显示身份、未知 Adapter、空模型 ID、禁用默认项、不支持或空推理集合、非法默认推理强度及缺失 Secret 启动失败，不产生部分 Catalog。
- [x] 受认证的 Catalog 只返回安全模型字段和支持的推理强度；浏览器、响应、静态资源和日志均不包含 Provider Credential、Secret 值或 Secret 环境变量名。
- [x] Chat 空状态允许选择模型与推理强度，并只展示当前模型支持的选项；本切片不出现 Temperature、Top-p、Token Budget、Endpoint 或 BYOK 控件。
- [x] Agent Host 只有 Provider Secret 和自身运行配置；架构测试证明这一切片没有 Core/Auth 数据库、RustFS、Worker、Queue 或 Canonical Data Credential。
- [x] 模型 Registry、Auth 边界、路由、Catalog Schema、无 Secret 输出、桌面折叠和移动抽屉有确定性测试；最终行为通过真实浏览器从 Caddy 验收。

## Verification and Review

- Standards review fixed generated-artifact exclusions, responsive sidebar sizing,
  mobile drawer focus/inert/touch behavior, unsafe Unicode Catalog text, lifecycle
  topology assertions, and the Caddy/upstream keep-alive race found during browser
  acceptance. Standards re-review: zero findings.
- Spec review checked every acceptance item above against the implementation and
  tests. Spec re-review: zero findings.
- `env CI=true pnpm test`: Ruff passed; Python `874 passed`; Agent `40 passed`;
  Auth `143 passed`; Web `108 passed`; all TypeScript typechecks passed.
- `./scripts/test-runtime e2e`: `16 passed`; Caddy config validation, same-origin
  probes, isolated Compose lifecycle, runtime Secret cleanup, and cleanup all passed.
  Evidence run: `20260829t155648z-55285-c7d66f6f`.
- `git diff --check`: passed.
