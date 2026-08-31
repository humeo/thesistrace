# 01 — Authenticated Chat shell and model catalog

**What to build:** 让登录后的 Researcher 可以从 ThesisTrace 主导航进入独立 Chat 页面，在符合现有设计语言的 Session 型侧边栏中看到 New Chat、位于顶部的 Workspace 链接，以及由私有 Agent Host 提供的系统注册模型与推理强度；该切片建立最终 Agent 服务和路由边界，但尚不创建 Chat Session 或运行模型。

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] Chat 成为受现有 SessionGate 保护的一级产品路由；匿名访问保留安全 `returnTo` 后进入登录，登录成功无需整页刷新即可回到 Chat。
- [ ] 普通产品侧边栏加入 Chat；Chat 页面使用独立 Session 侧边栏骨架，顶部依次保留 ThesisTrace、New Chat、Data、Research、Research Runs、Daily Tracks，Session 区域位于其下，账号入口位于底部。
- [ ] 页面严格使用现有近黑画布、炭灰 Surface、Hairline、紧凑字体、薰衣草焦点与语义状态色，不复制原型的临时 CSS，不保留浅色或第二套 Chat 视觉路径。
- [ ] 新增一个私有 Node 24/pnpm Agent Host，并由 Caddy 在通用 Core API 之前代理同源 Agent API；Agent Host 不发布 Host 端口，Caddy 仍是唯一公共监听者。
- [ ] Agent Host 在每个浏览器请求上通过现有 Auth 私有 Session 验证获得 Researcher 身份；无效、过期、撤销、Inactive、Auth 超时和错误 Origin 全部失败关闭。
- [ ] Agent Host 启动时一次性读取模型 Registry；每项包含稳定 Key、显示名、Provider Adapter、Provider Model ID、支持的推理强度、默认推理强度及所需 Secret 引用。
- [ ] Registry 对重复 Key、歧义显示身份、未知 Adapter、空模型 ID、禁用默认项、不支持或空推理集合、非法默认推理强度及缺失 Secret 启动失败，不产生部分 Catalog。
- [ ] 受认证的 Catalog 只返回安全模型字段和支持的推理强度；浏览器、响应、静态资源和日志均不包含 Provider Credential、Secret 值或 Secret 环境变量名。
- [ ] Chat 空状态允许选择模型与推理强度，并只展示当前模型支持的选项；V1 不出现 Temperature、Top-p、Token Budget、Endpoint 或 BYOK 控件。
- [ ] Agent Host 只有 Provider Secret 和自身运行配置；架构测试证明这一切片没有 Core/Auth 数据库、RustFS、Worker、Queue 或 Canonical Data Credential。
- [ ] 模型 Registry、Auth 边界、路由、Catalog Schema、无 Secret 输出、桌面折叠和移动抽屉有确定性测试；最终行为通过真实浏览器从 Caddy 验收。
