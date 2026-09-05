# 当前可见 Skills 与 AGENTS.md 审阅

> 本文为有日期的历史审阅记录；下文的“当前”和建议仅对应当时快照，不代表本次领域文档审查的代码事实。失效来源仅保留历史位置文本。

日期：2026-09-05。以本轮提供的 **45 个技能入口** 和当前磁盘中的用户级、项目级 AGENTS.md 为准。旧报告里的删除建议、数量和问题状态不再直接沿用；首次完整盘点保留在 [历史快照](initial-audit.md)。

## 结论

用户级规则没有发现明显的核心矛盾。浏览器规则和 CopilotKit 版本基准已按本轮要求修复；仍需处理的是 CopilotKit 指南内容冲突、codebase-design 的测试替代建议、diagnosing-bugs 的复现前置限制，以及两个初始化技能的执行假设。

本轮修改项目浏览器规则、Agent/Web 依赖、pnpm 锁文件和版本契约测试，并执行应用验证。验证范围及既有失败见文末。

## 逐项状态

### 1. 项目浏览器规则（已修复）

[项目 AGENTS.md:7](../../AGENTS.md) 已改为：交互式浏览器检查与验收优先使用当前可用的应用内浏览器工具；可重复的浏览器回归使用仓库 Playwright 测试。

规则已去掉失效的技能名称。

### 2. CopilotKit 指南仍有内容冲突（版本已对齐）

- [runtime:85](../../.agents/skills/runtime/SKILL.md) 要求 fetch primitive，并强烈反对 Hono/Express handlers；[develop:28](../../.agents/skills/copilotkit-develop/SKILL.md)、[setup:99](../../.agents/skills/copilotkit-setup/SKILL.md)、[integrations:121](../../.agents/skills/copilotkit-integrations/SKILL.md)、[upgrade:99](../../.agents/skills/copilotkit-upgrade/SKILL.md) 却推荐这些 handlers。
- [react-core:100](../../.agents/skills/react-core/SKILL.md) 写 `useAgent` 返回 `{ agent, isReady }`；[integrations:125](../../.agents/skills/copilotkit-integrations/SKILL.md) 写 only `{ agent }`。
- 版本差异已修复：react-core/runtime/a2ui-renderer 的 `library_version` 与 [agent/package.json:26](../../agent/package.json)、[web/package.json:21](../../web/package.json) 均为 **1.70.0**，与 [官方发布](https://github.com/CopilotKit/CopilotKit/releases/tag/v1.70.0) 对应。项目直接引用的 AG-UI client/core/encoder 同步到新版依赖的 **0.0.59**。

已核对安装包的类型声明，并验证项目现用的 `createCopilotRuntimeHandler`、`useAgent({ agentId, runtimeAgentId, threadId })` 和 `{ agent, isReady }` 用法。上面的指南内容分歧仍需单独修正。其他技能 frontmatter 中的 `version` 是技能自身版本，不是 CopilotKit 库版本，应保留其原有含义。

### 3. codebase-design 的辅助文档仍与新测试规则相冲突

[DEEPENING.md:34](/Users/koltenluca/.agents/skills/codebase-design/DEEPENING.md:34) 要求深层接口测试建立后直接删除旧单元测试。项目 [AGENTS.md:47](../../AGENTS.md) 则要求覆盖已被等价替代且旧测试无独立价值，后者应作为删除条件。

同文档 [15 行](/Users/koltenluca/.agents/skills/codebase-design/DEEPENING.md:15)、[19 行](/Users/koltenluca/.agents/skills/codebase-design/DEEPENING.md:19) 把数据库替身、内部服务的内存 adapter 描述成完整测试方案，未区分纯规则测试与真实存储/传输语义。替身可用于纯规则测试，但不能替代所声称验证的事务、权限、交付和 Worker 集成证据。

建议补上这两个边界，保留模块设计技能。TDD 的主文件与 mocking/tests 辅助文档已经修正，不应再把旧问题归到 TDD。

### 4. diagnosing-bugs 的硬前置条件阻碍诊断

[diagnosing-bugs:55](/Users/koltenluca/.agents/skills/diagnosing-bugs/SKILL.md:55) 要求没有可运行的失败循环就停止假设分析；[66 行](/Users/koltenluca/.agents/skills/diagnosing-bugs/SKILL.md:66) 甚至禁止在该命令建立前读代码形成解释。这与项目 [AGENTS.md:46](../../AGENTS.md) 的“诊断和读代码不必等待测试写完”正面冲突。

很多环境、配置或低复现率问题，需要先看代码、日志和配置才能构造复现。建议允许先做有证据的分析，同时清楚区分待验证假设与已复现结论；修复完成仍应有有效验证。

[90 行](/Users/koltenluca/.agents/skills/diagnosing-bugs/SKILL.md:90) 固定要求 3–5 个假设也应降为按实际不确定性决定。51 行的延迟注入可作为受控故障实验，不应简单等同于项目禁止的任意 sleep。

### 5. create-auth 有互相打架的问答规则和工具假设

[create-auth:26](../../.agents/skills/create-auth/SKILL.md) 要求跳过已经确定的问题；46、64、69、77 行又写 always ask，107 行再要求确认计划。

[30 行](../../.agents/skills/create-auth/SKILL.md) 指定 `AskQuestion`，当前没有该同名工具。建议按当前可用的问答能力，仅收集尚未确定且影响实现的选择，并识别用户已给出的授权。

233 行以后还包含通用迁移示例，不能直接作为当前硬切换项目的操作要求。按照用户决定保留 create-auth，修正适用边界即可，不再建议删除。

### 6. shadcn 把未执行的命令当成已提供的上下文

[shadcn:17](/Users/koltenluca/.agents/skills/shadcn/SKILL.md:17) 是代码块里的字面量命令；20、179 行却声称项目 JSON 已注入。文件读取并不会执行该命令。

建议写成：优先读取实际提供的 JSON；没有时再用项目 runner 执行 info。12 行已经要求遵循项目包管理器，无需将 npx 示例本身再列作硬冲突。

## 次要问题与表述改进

本轮实际执行还发现测试分层没有完全落实到脚本：`pnpm test:image-smoke` 会通过 [production_image_smoke.py:864](../../tests/production_image_smoke.py) 调用批量研究性能资格验证，固定执行 1 轮预热和 4 轮测量（[80 行](../../tests/production_image_smoke.py)）。因此普通运行依赖升级也会触发完整计算性能矩阵；后续宜将这部分归到性能或发布资格入口，使日常镜像检查聚焦启动、健康与受影响运行链路。

| 对象 | 当前判断 |
|---|---|
| [code-review:76](/Users/koltenluca/.agents/skills/code-review/SKILL.md:76)、82 行 | 审阅范围已修复，但完整发现仍被每轴 400 words 限制；大改动宜限制摘要长度，完整 findings 另存。这是输出丢失风险，不是已经漏审的证据 |
| [项目 AGENTS.md:47](../../AGENTS.md) | “不绑定调用次数”宜限定为内部协作调用次数；重复扣费、重复投递等可观察副作用次数仍可能是合法业务不变量 |
| [用户 AGENTS.md:14](/Users/koltenluca/.codex/AGENTS.md:14) | `rulers`、`commonfunctionality` 拼写；成熟依赖相关两条可合并。“简单”与“长期维护”不构成硬冲突 |
| 用户 AGENTS.md 最后一条 | 研究成熟产品适合重要设计决策，不应将小修都变成竞品研究 |
| 项目 AGENTS.md 开头 | 中英文硬切换禁令重复，合并即可；不擅自放宽禁止兼容/迁移的政策 |
| [domain.md:7](../../docs/agents/domain.md)、[triage-labels.md:15](../../docs/agents/triage-labels.md) | single-context 项目仍保留多 context 模板；标签文档还有安装提示。属于文档残留 |
| frontend-design 与 design-taste-frontend | 有功能重叠，但不是必须二删一。后者正文已排除产品工作台，建议把排除范围写进 description；本项目 DESIGN.md 优先 |
| codebase-design 的术语规则 | 只用于讨论模块设计，避免把“不说 component/service/API”扩散到技术 API 名称或项目领域术语 |

## 宿主适配问题，优先服从运行环境

- [visualize:22](/Users/koltenluca/.codex/plugins/cache/openai-bundled/visualize/1.0.29/skills/visualize/SKILL.md:22) 禁止进度消息及技能声明，与当前宿主通讯要求冲突，应服从更高层规则。
- openai-docs 的 docs-first 与宿主处理本机状态时的本地优先要求有张力；当前安装事实仍应读取本机。
- plugin-management 指定的 `search_plugins` / `suggest_plugins` 当前没有同名工具，需要能力适配。
- deep-research 提到 `update_plan`，但正文已允许规划能力不可用时继续，不应列为必然阻塞。

这些是维护问题，不意味着要删除相应能力，也不意味着技能可以越过用户或宿主约束。

## 不再沿用的旧问题

- code-review 已覆盖 commit range、staged、working tree、untracked、无首次提交、版本一致性和捕获快照；不再列为范围漏审问题。
- TDD 已按风险选择层级、不重复确认，并恢复 red–green–refactor；mocking/tests 辅助文档也承认必要的真实数据库断言。
- 两级 AGENTS.md 不再要求强制开发迁移/跨版本测试；用户级也已明确必须隔离时不可原地继续。
- 当前可见目录没有 worktree、Product Design、Context7、logging-best-practices、vercel-react-best-practices、resolving-merge-conflicts、Hallmark，不把旧缓存或已删入口当作本轮活动问题。
- `to-tickets`、`to-spec` 与本地 `build-test-data` 仍为手动调用。本次没有把它们当作可自动触发的 45 个入口；按用户决定保留，不主动加入普通任务。
- Channels 三件套、copilotkit-upgrade、create-auth 均恢复且继续保留，不因尚未使用再提出删除建议。

## 当前安装与检查边界

本次读取当前可见的 45 个 SKILL.md，与前次内容比较，回读变更正文、冲突规则及必要的辅助文档；检查普通 Markdown 本地引用，没有发现缺失文件。这个检查不等于所有字符串式技能路由、外部网页和代码示例均经过运行验证。

项目规范目录当前有 19 个技能、18 条安装记录，自定义 build-test-data 不在安装锁中。所有锁条目都有对应 SKILL.md。最终检查时项目 `.claude/skills` 目录已不存在；此前报告的“18 个有效软链接”不再描述当前状态，但 Codex 的规范技能目录仍在。本轮未操作该目录。

45 个技能的审阅结论来自上一轮盘点；本轮随后按用户要求修复浏览器规则并升级应用依赖，应用验证使用项目现有运行入口。

## 本轮 45 个可见技能逐项结论

“保留”表示没有发现需要整体删除的理由，不表示每个外部 API 示例都已执行验证。下表只包含当前可见入口。

| 技能 | 当前结论 |
|---|---|
| [imagegen](/Users/koltenluca/.codex/skills/.system/imagegen/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [openai-docs](/Users/koltenluca/.codex/skills/.system/openai-docs/SKILL.md) | 保留；本机事实与官方产品文档各用合适来源 |
| [plugin-creator](/Users/koltenluca/.codex/skills/.system/plugin-creator/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [skill-creator](/Users/koltenluca/.codex/skills/.system/skill-creator/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [skill-installer](/Users/koltenluca/.codex/skills/.system/skill-installer/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [a2ui-renderer](../../.agents/skills/a2ui-renderer/SKILL.md) | 保留；库版本与项目依赖已统一为 1.70.0 |
| [better-auth-best-practices](../../.agents/skills/better-auth-best-practices/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [better-auth-security-best-practices](../../.agents/skills/better-auth-security-best-practices/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [channels-setup](../../.agents/skills/channels-setup/SKILL.md) | 按用户要求保留；Channels 初次接入入口 |
| [copilotkit-agui](../../.agents/skills/copilotkit-agui/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [copilotkit-channels](../../.agents/skills/copilotkit-channels/SKILL.md) | 按用户要求保留；Channels 代码部分 |
| [copilotkit-debug](../../.agents/skills/copilotkit-debug/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [copilotkit-develop](../../.agents/skills/copilotkit-develop/SKILL.md) | 保留；统一 handler 指南 |
| [copilotkit-integrations](../../.agents/skills/copilotkit-integrations/SKILL.md) | 保留；统一 handler 与 useAgent 指南 |
| [copilotkit-setup](../../.agents/skills/copilotkit-setup/SKILL.md) | 保留；统一 handler 指南 |
| [copilotkit-upgrade](../../.agents/skills/copilotkit-upgrade/SKILL.md) | 按用户要求保留；统一 handler 指南，仅在升级任务适用 |
| [create-auth](../../.agents/skills/create-auth/SKILL.md) | 按用户要求保留；修正已知问题仍必问及工具假设 |
| [email-and-password-best-practices](../../.agents/skills/email-and-password-best-practices/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [organization-best-practices](../../.agents/skills/organization-best-practices/SKILL.md) | 保留；有对应组织权限任务时使用 |
| [react-core](../../.agents/skills/react-core/SKILL.md) | 保留；库版本已统一为 1.70.0，现用 useAgent 类型与应用验证通过 |
| [runtime](../../.agents/skills/runtime/SKILL.md) | 保留；库版本已统一为 1.70.0，指南之间的 handler 选择仍需统一 |
| [setup-slack-channel](../../.agents/skills/setup-slack-channel/SKILL.md) | 按用户要求保留；说明已有 OpenTag 范围，勿误用到任意项目 |
| [two-factor-authentication-best-practices](../../.agents/skills/two-factor-authentication-best-practices/SKILL.md) | 保留；有 MFA 任务时使用 |
| [code-review](/Users/koltenluca/.agents/skills/code-review/SKILL.md) | 范围问题已修复；调整完整 findings 的字数限制 |
| [codebase-design](/Users/koltenluca/.agents/skills/codebase-design/SKILL.md) | 修正 DEEPENING 的测试替代/删除规则，收窄术语约束 |
| [design-taste-frontend](/Users/koltenluca/.agents/skills/design-taste-frontend/SKILL.md) | 保留；在描述中明确排除产品工作台 |
| [diagnosing-bugs](/Users/koltenluca/.agents/skills/diagnosing-bugs/SKILL.md) | 保留诊断能力；允许复现前基于证据读代码分析 |
| [domain-modeling](/Users/koltenluca/.agents/skills/domain-modeling/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [frontend-design](/Users/koltenluca/.agents/skills/frontend-design/SKILL.md) | 保留；已有项目按 DESIGN.md，避免叠加另一套默认风格 |
| [git-commit](/Users/koltenluca/.agents/skills/git-commit/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [grilling](/Users/koltenluca/.agents/skills/grilling/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [obsidian-cli](/Users/koltenluca/.agents/skills/obsidian-cli/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [obsidian-markdown](/Users/koltenluca/.agents/skills/obsidian-markdown/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [pdf](/Users/koltenluca/.agents/skills/pdf/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [prototype](/Users/koltenluca/.agents/skills/prototype/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [research](/Users/koltenluca/.agents/skills/research/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [shadcn](/Users/koltenluca/.agents/skills/shadcn/SKILL.md) | 保留；修正“上下文已注入”的假设 |
| [tdd](/Users/koltenluca/.agents/skills/tdd/SKILL.md) | 原主要冲突已修复；保留 |
| [tushare](/Users/koltenluca/.agents/skills/tushare/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [linear](/Users/koltenluca/.codex/skills/linear/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [playwright](/Users/koltenluca/.codex/skills/playwright/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [screenshot](/Users/koltenluca/.codex/skills/screenshot/SKILL.md) | 保留；未发现需要整体删除的规则冲突 |
| [deep-research](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/deep-research-work/0.1.14/skills/deep-research/SKILL.md) | 保留；只在明确深度研究时使用，规划能力缺失不阻塞 |
| [plugin-management](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/plugin-management/0.1.0/skills/plugin-management/SKILL.md) | 保留；按当前工具能力适配 |
| [visualize](/Users/koltenluca/.codex/plugins/cache/openai-bundled/visualize/1.0.29/skills/visualize/SKILL.md) | 保留；通讯规则服从宿主 |

## CopilotKit 版本对齐验证

日期：2026-09-05。应用直接依赖 `@copilotkit/runtime`、`@copilotkit/react-core`、`@copilotkit/a2ui-renderer` 均为 **1.70.0**；AG-UI client/core/encoder 为 **0.0.59**。已检查 manifest、pnpm 锁文件和实际 node_modules 版本，Runtime、React Core、Mastra adapter 与应用解析到相同的 AG-UI client/core 实例。

| 验证 | 结果 |
|---|---|
| Agent/Web typecheck | 通过 |
| Agent 单元测试 | 526 通过 |
| Agent eval-preflight | 11 通过；离线验证，没有真实模型调用 |
| Web test:shell | 310 通过 |
| Agent/Web 构建 | 通过，产品 bundle budget 通过 |
| 版本契约测试及该文件 Ruff 检查 | 更新旧版本断言后，9 通过 |
| Agent 真实 PostgreSQL 集成 | 67 通过，临时 Compose 环境已清理 |
| 最终产品镜像 smoke | 未全部通过：镜像构建、健康、计算矩阵、Worker 中断恢复通过；第二次数据库重启后的 Auth 请求返回 503 |
| Agent/Auth/Caddy 组件镜像 smoke | 三项独立检查均通过 |
| 关键聊天浏览器流程 | 4 通过：流式首轮及刷新回放、人工确认后继续、Stop/Continue、A2UI 表格渲染及回放 |

`pnpm check` 的首次运行在 Python 阶段得到 1076 通过、3 失败。其中一项是本次升级需要同步的版本断言，已更新并通过上述 9 项契约测试。另两项在未修改的 HEAD `b54560efc05c35e22d2cc2eccce8f4defe7e81f9` 源码快照上均可复现：

- [test_core_runtime_boundaries.py:193](../../tests/architecture/test_core_runtime_boundaries.py)：adapters 引入 `operational_events`，超出测试声明的允许依赖。
- [test_core_runtime_boundaries.py:494](../../tests/architecture/test_core_runtime_boundaries.py)：资源路由检测连同 import 一起扫描，命中 `handleWorkspaceNavigation` 里的 `workspace`。

因此不能将本次结果写为完整 `pnpm check` 通过；直接涉及 CopilotKit 的检查已独立执行。原锁文件中已有的 Zod、Vitest、Express 类型 peer 警告在升级前后保持相同依赖组合。

产品镜像失败发生在 `image-smoke-persisted`：读取 ResearchRun 时返回 `503 {"detail":"Authentication unavailable"}`；同一轮 Auth 日志在数据库重启时记录 `AUTH_DATABASE_UNAVAILABLE / 57P01`。Auth 的直接依赖版本未变化；这条恢复链路的失败尚未验证到根因，不能据此声称镜像全套通过。详见 失败堆栈（历史位置：`.local/test-runs/20260905t080914z-44138-eeca6af3/evidence/smoke-persisted.stderr.log`） 和 运行记录（历史位置：`.local/test-runs/20260905t080914z-44138-eeca6af3/run.txt`）。该轮测试资源与运行密钥已成功清理（`cleanup_status=0`、`runtime_secret_cleanup_status=0`）。

聊天浏览器验收使用现有 `pnpm test:e2e` 入口，并通过 `THESISTRACE_TEST_PLAYWRIGHT_GREP` 选择上述 4 条流程。运行记录（历史位置：`.local/test-runs/20260905t083316z-54565-20ba6009/run.txt`） 显示 `e2e-playwright status=0`、整体 `status=0`，测试资源和运行密钥均已清理。组件镜像分别运行 `pnpm --dir agent test:image-smoke`、`pnpm --dir auth test:image-smoke` 和 `pnpm test:caddy-image-smoke`，三条命令均返回 0。
