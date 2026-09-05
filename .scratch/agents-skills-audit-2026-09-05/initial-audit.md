# AGENTS.md 与 Skills 审阅

> 本文为有日期的历史审阅记录；下文的“当前”和建议仅对应当时快照，不代表本次领域文档审查的代码事实。失效来源仅保留历史位置文本。

> 第一轮清理已于 2026-09-05 按用户圈选执行：删除项目 `copilotkit-contribute`、`inspector-docs`、`inspector-workbench`、`channels-setup`、`copilotkit-channels`、`setup-slack-channel`、`copilotkit-upgrade`、`create-auth`、`copilotkit-self-update`，删除旧 `.codex/skills/build-test-data`，删除全局 `hallmark`；同步两个安装锁文件及对应软链接。项目规范技能由 23 个减至 14 个。保留规范 `build-test-data` 和手动 `to-tickets`；两级 AGENTS.md、其他技能、插件缓存及业务代码未改。已独立检查目标删除、保留技能、锁文件和软链接一致性。下文保留清理前审阅快照，已删除技能的来源位置仅作为历史文本保留。

日期：2026-09-05。项目：ThesisTrace。此次只审阅，新增本报告；没有改动或删除 AGENTS.md、skills、配置、依赖和业务代码。

## 结论

用户级 AGENTS.md 基本健康，项目级测试规范存在内部矛盾。主要混乱来自技能之间重复定义工作流、技能适用范围过宽，以及不同版本的 CopilotKit 指南同时安装。

建议先修规则再删技能。最值得处理的五件事：

1. 统一项目的硬切换政策与测试要求，删除 `to-tickets` 对本项目不适用的新旧并存流程。
2. 修复 `code-review` 的审阅范围和 `ask-matt` 对执行流程的失实描述。
3. 修复 worktree 创建失败后原地继续、合并时全部暂存这两条危险指令。
4. 合并 CopilotKit 的重复入口；保留与当前安装版本核对过的用法。
5. 设计技能保留一个默认入口；Hallmark 与 Anti-Slop 的强制美学规则、步骤和产物不宜叠加。

## 范围与证据口径

检查了用户级 `/Users/koltenluca/.codex/AGENTS.md`、项目根 AGENTS.md、三个 `docs/agents` 路由文档、DESIGN.md、skill 配置、锁文件、软链接，以及相关依赖和使用点。

技能盘点包括：

| 范围 | SKILL.md 数量 | 本轮初始可用列表中数量 | 说明 |
|---|---:|---:|---|
| 用户共享 `.agents/skills` | 35 | 21 | 13 个显式调用技能；另有 `weread-skills` 在磁盘上但未出现在本轮初始目录中 |
| 用户 `.codex/skills`，含 `.system` | 10 | 8 | `review-agent` 为显式调用；`chronicle` 在配置中禁用 |
| 项目 `.agents/skills` | 23 | 22 | `build-test-data` 为显式调用 |
| 本轮提供技能的五组插件 | 27 | 9 | Product Design 10 个、Superpowers 14 个，其余三组各 1 个 |
| 主要审阅小计 | 95 | 60 | 磁盘存在、可隐式调用、显式调用、禁用是不同状态 |
| 额外插件缓存 | 119 | 0 | 只按本轮初始目录统计可见性，详细清单见附录 |
| 规范 SKILL.md 总计 | 214 | 60 | 不重复计算软链接；不包含旧小写 skill.md |

95 个入口均纳入元数据、适用范围、流程和强制规则扫描；重点问题回读原文，并核对必要的引用文件与本项目代码。没有逐个执行技能、运行外部操作，也没有把所有代码示例和全部 references 当作第三方 API 正确性审计。另对未在本轮目录出现的 119 个缓存入口做元数据和强制规则筛查，完整名称见附录；不据此断言插件正在启用或可以安全卸载。

官方文档确认：AGENTS.md 从用户级到项目级叠加，较近的项目规则覆盖更早的指导；skills 初始加载名称、描述和路径，选中后才读正文。因此，大技能主要增加调用时成本，不能把磁盘总字数当作每次请求都会注入的上下文。[AGENTS.md 加载规则](https://learn.chatgpt.com/docs/agent-configuration/agents-md)、[Skills 加载与调用策略](https://learn.chatgpt.com/docs/build-skills)。

显式调用技能不是坏掉或被禁用。`agents/openai.yaml` 中的 `allow_implicit_invocation: false` 仍允许用户明确调用；其正文也可能被其他技能引用。[官方说明](https://learn.chatgpt.com/docs/build-skills)。

## 优先修复：明确冲突或会造成错误行为的规则

### 1. 项目禁止迁移，却要求迁移和跨版本兼容测试

证据：[AGENTS.md:2](../../AGENTS.md) 禁止 compatibility、fallback、migration；[AGENTS.md:53](../../AGENTS.md) 要求镜像验证迁移；[AGENTS.md:62](../../AGENTS.md) 要求 Schema 的迁移、前后版本兼容和回滚测试。

影响：同一次 schema 变更会收到相反要求，还可能为了满足测试条款创建本来禁止的迁移路径。

建议：保留硬切换原则，删除重复的第二条；测试改为当前 schema 初始化、约束、契约拒绝、隔离环境启动。若“迁移”只是泛指初始化，应直接改用“初始化”。不要在本次清理中擅自把禁止迁移改成允许迁移。

“fallback”需要明确指向产品/数据/协议的静默降级或旧实现保留，避免扩散为禁止字体后备栈、工具替代路径等完全不同的概念。

### 2. `to-tickets` 强制 expand–contract，与项目硬切换正面冲突

证据：[to-tickets:40](/Users/koltenluca/.agents/skills/to-tickets/SKILL.md:40) 要求宽重构先把新旧实现并存，再分批迁移调用方，最后删除旧实现。

影响：按该技能拆出来的票据，从计划阶段就违反项目约束。

建议：全局技能把它降为“项目允许并行版本时的一种策略”；本项目采用一次完整可验证的硬切换，必要时使用隔离集成分支，不把旧路径作为兼容层留下。

### 3. 测试层级被三套规则争夺

证据：项目 [AGENTS.md:33](../../AGENTS.md) 要求最低且足够真实的层级；[to-spec:15](/Users/koltenluca/.agents/skills/to-spec/SKILL.md:15) 要求尽可能高的测试边界，并把单一边界作为理想状态（不是只写一个测试）；[tdd:22](/Users/koltenluca/.agents/skills/tdd/SKILL.md:22) 禁止在未经用户确认的边界写任何测试。

影响：纯业务规则可能被迫从大范围集成或 E2E 验证；明确的 bug 修复也可能停下来询问已由项目测试规范决定的边界。

建议：保留项目的风险驱动规则。现有公开接口、已批准 spec 和项目测试规范已足够明确时直接选择；只有新增重要公共契约或取舍影响产品时才询问。

另有两处应降为建议：`tdd:38` 将 refactor 排除在循环外，但其描述又包括 red-green-refactor；[codebase-design/DEEPENING.md:34](/Users/koltenluca/.agents/skills/codebase-design/DEEPENING.md:34) 要求深层测试建立后删除旧单元测试。旧测试只有在覆盖已被等价替代且失去独立价值时才删除，不应按层级批量删除。

### 4. `code-review` 的命令不能完整覆盖它声称支持的未提交工作

证据：[code-review:19](/Users/koltenluca/.agents/skills/code-review/SKILL.md:19) 只定义固定引用的三点 diff 和 staged；没有明确的 unstaged、完整 working tree、untracked 文件模式。即便选择 `staged`，后续又统一要求 `git rev-parse <fixed-point>`。

影响：审阅“当前修改”时可能漏掉未暂存和新增文件；`staged` 也不应被当成 Git ref 解析。

建议：明确 commit/branch、staged、working tree 三种模式；先冻结 SHA 和审阅文件清单，再给两个 reviewer 同一个范围。保留 Standards/Spec 两个视角，删去没有 spec 时强制反复追问的流程；若任务本身就是要求，可将用户需求作为审阅依据。

另：[code-review:66](/Users/koltenluca/.agents/skills/code-review/SKILL.md:66) 与 72 行要求报告全部问题，又限制每轴 400 words。大变更应限制摘要长度，完整 findings 另存文件，不应截断真实问题。代码异味已声明为启发式，不能把它们全部提升成阻塞缺陷。

### 5. worktree 技能包含会破坏隔离约定的自动行为

证据：using-git-worktrees:86（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/superpowers/6.3.0/skills/using-git-worktrees/SKILL.md:86`） 在创建隔离目录前先修改并提交当前 checkout 的 `.gitignore`；同文件:100（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/superpowers/6.3.0/skills/using-git-worktrees/SKILL.md:100`） 遇到 sandbox 拒绝就改为当前目录继续；108–115 行仅按文件类型选择 npm/pip/poetry 安装，没有检查项目包管理器约定。

影响：用户要求必须隔离时可能在原 checkout 动手；同时与用户级 uv、pnpm 约定冲突。

建议：隔离是必要条件时，创建失败就保留阻塞并处理权限，不能自动原地继续；忽略规则和初始化命令应服从项目约定。若只需要这个技能提供的简单 worktree 检查，可停用它，将简短的隔离规则放到用户级 AGENTS.md。不要直接编辑插件缓存作为长期修复。

### 6. 合并技能要求“Stage everything”

证据：resolving-merge-conflicts:14（历史位置：`/Users/koltenluca/.agents/skills/resolving-merge-conflicts/SKILL.md:14`）。

影响：本仓库当前存在多组并行修改，全部暂存可能把无关工作纳入合并提交。`Always resolve; never --abort` 也没有为用户明确取消或误入 merge 留出正确出口。

建议：只暂存当前 merge/rebase 必需的冲突解决文件；保留其他未暂存、未跟踪工作。完成或中止应遵循用户明确目标，技能不能自行扩展提交范围。

### 7. CopilotKit 指南内部存在相反 API 建议和版本漂移

证据：[runtime:85](../../.agents/skills/runtime/SKILL.md) 要求避免 `createCopilotHonoHandler` / `createCopilotExpressHandler`，使用 `createCopilotRuntimeHandler`；[copilotkit-develop:28](../../.agents/skills/copilotkit-develop/SKILL.md)、[copilotkit-integrations:92](../../.agents/skills/copilotkit-integrations/SKILL.md)、[copilotkit-setup:97](../../.agents/skills/copilotkit-setup/SKILL.md) 则将前两者作为常规入口。

`react-core:100` 写 `useAgent` 返回 `{ agent, isReady }`，`copilotkit-integrations:125` 却写“only `{ agent }`”。本项目 [ChatConversation.tsx:47](../../web/src/chat/ChatConversation.tsx) 已在使用 `isReady`。

`react-core`、`runtime`、`a2ui-renderer` 的元数据标注 library_version 1.70.0；项目 [agent/package.json:26](../../agent/package.json) 和 [web/package.json:21](../../web/package.json) 固定 1.69.3。版本差异本身不证明全部 API 都错，但证明不能直接把技能当作当前版本的权威。当前 [research-runtime.ts:336](../../agent/src/research-runtime.ts) 已使用 fetch handler。

建议：保留 `react-core`、`runtime`、`a2ui-renderer`、`copilotkit-agui`、`copilotkit-debug` 为主体；把 develop/setup/integrations 收敛为指向这些参考的薄入口，或移除其重复流程。使用前核对当前安装版本和类型，不能为匹配 skill 擅自升级依赖。

`runtime`、`react-core` 的 description 很长、名称又泛，建议缩短描述并增加明确的 CopilotKit 前缀。改名需要同步引用与安装清单，避免产生旧名字残留。

## 混乱、冗余与不必要的流程

### 8. `ask-matt` 对 `implement` 的描述与实际内容不符

ask-matt:26（历史位置：`/Users/koltenluca/.agents/skills/ask-matt/SKILL.md:26`） 承诺按依赖并行、隔离写入面、每票规划、最多三轮 review 等；implement（历史位置：`/Users/koltenluca/.agents/skills/implement/SKILL.md:7`） 实际只有实现、TDD、检查、一次 code-review、提交当前分支，没有上述调度与循环。

`ask-matt:83` 还路由到本次盘点不存在的 `/wizard`；它称 prototype 在独立目录，`prototype:21` 则要求靠近实际模块放置。

建议：router 只写“什么时候用哪个技能”，不要重复承诺另一个技能未实现的细节。执行/审阅完成条件只保留一个权威来源。先修这个 router，再决定是否保留它；不要靠多加解释来维持两套文本。

### 9. 三个全局设计技能不应同时默认触发

| 技能 | 正文大小 | 主要定位 | 建议 |
|---|---:|---|---|
| `frontend-design` | 约 8 KB / 55 行 | 通用设计判断、尊重 brief | 可作为唯一默认设计入口 |
| `design-taste-frontend` | 约 87 KB / 1206 行 | 营销页、作品集、Anti-Slop 清单 | 改为明确调用或删去；不用于产品工作台 |
| `hallmark` | 约 67 KB / 558 行 | 完整主题/结构/导出/审美检查工作流 | 与上两者二选一；若不用这套流程可删除 |

真正相反的默认：Anti-Slop [267–274 附近](/Users/koltenluca/.agents/skills/design-taste-frontend/SKILL.md:267) 要求生成图片、纯文字页面视为未完成；Hallmark 395–401 附近（历史位置：`/Users/koltenluca/.agents/skills/hallmark/SKILL.md:395`） 默认 typography-only，CSS/SVG 优先。Anti-Slop 179 行鼓励同字体斜体强调；Hallmark 56 行禁止标题斜体。

需要纠正容易过度判断的一点：Anti-Slop [8 行](/Users/koltenluca/.agents/skills/design-taste-frontend/SKILL.md:8) 和 [896 行](/Users/koltenluca/.agents/skills/design-taste-frontend/SKILL.md:896) 已明确排除 dense product UI；532 行也允许用户指定单主题。因此它不是必须覆盖本项目深色主题的合法规则。问题是 description 没把排除范围说清，后面“每项必须检查、双主题都必须看”的清单又没有重申豁免，容易误触发和误执行。

Hallmark 153 行（历史位置：`/Users/koltenluca/.agents/skills/hallmark/SKILL.md:153`） 明确 DESIGN.md 优先；不能据其主题轮换默认就断言它必然要求每页改主题。

本项目已有明确的 Linear 深色工作台规范。一般组件实现应读 DESIGN.md；视觉探索时选择一个设计技能；Product Design 仅用于明确的图像探索、临摹或产品体验审计，不叠加进日常小修。

### 10. Hallmark 自身存在流程死结和额外产物膨胀

- 381 行（历史位置：`/Users/koltenluca/.agents/skills/hallmark/SKILL.md:381`） 禁止 Step 7 前加载 slop test；407 行要求代码前输出 preview；430 行却要求这个 preview 已跑完 Step 7 并列出结果。应将 preview 与最终 QA 结果分开。
- 211–228 附近（历史位置：`/Users/koltenluca/.agents/skills/hallmark/SKILL.md:211`） 要求即使用户已给齐受众、用途、风格也照问。这与避免重复询问的协作目标冲突。
- 463–465 附近（历史位置：`/Users/koltenluca/.agents/skills/hallmark/SKILL.md:463`） 把现有全局 CSS 设为 append-only，并要求额外 tokens.css 与四套导出。普通组件修复不需要这些；append-only 还会让旧规则难以清除。
- 282 行（历史位置：`/Users/koltenluca/.agents/skills/hallmark/SKILL.md:282`） 引用的 `../../site/css/tokens.css` 在当前安装中不存在。390–391 行两个 human-only 文档也缺失，但后者不阻塞正常调用。

若保留 Hallmark，先修上述问题，不能仅因“有 DESIGN.md 优先”就认为整套流程没有冲突。

### 11. 安装技能过于宽泛，容易装回刚清理掉的内容

copilotkit-self-update:3（历史位置：`.agents/skills/copilotkit-self-update/SKILL.md`） 把一般的 “update skills” 也列为触发词；13 行（历史位置：`.agents/skills/copilotkit-self-update/SKILL.md`） 命令没有选定 skill 清单，而是 `npx skills add copilotkit/CopilotKit --full-depth -y`。

建议：仅在明确更新 CopilotKit skills 时触发，并保留选定安装集合。否则通用“更新技能”可能变成重装整套 CopilotKit，重新引入 upstream/Channels 技能。

context7-cli:10（历史位置：`/Users/koltenluca/.agents/skills/context7-cli/SKILL.md:10`） 要求使用前保证 latest，示范全局安装；其 description 又覆盖任何 library docs 和 skills 管理。建议只在调用 ctx7/Context7 或明确选择该文档来源时触发；已有工具能读文档时不必先全局升级。与用户级包管理器约定统一。

### 12. `shadcn` 假设存在动态注入的上下文

[shadcn:16](/Users/koltenluca/.agents/skills/shadcn/SKILL.md:16) 是字面量 `!` 命令占位，后文却说 JSON 已经注入。此次通过文件读取没有执行它，也没有获得 JSON。

建议：写成“若实际上下文尚未提供，运行项目包管理器对应的 shadcn info 并读取结果”。其 12 行已经说明 npx 只是示例、应换成项目 runner，这一点无需重复修复。

本项目没有 shadcn 依赖/根 components.json，不应因写 React 组件就初始化 shadcn。全局保留给使用 shadcn 的其他项目。

### 13. 项目 AGENTS.md 有通用模板残留，用户级则可以小幅压缩

项目：

- [浏览器规则:7](../../AGENTS.md) 指向当前不存在的 `browser:control-in-app-browser` 技能。建议写实际意图：“人工浏览器验收优先当前可用的 in-app browser；可重复回归使用仓库 Playwright 测试”。不要把工具或插件旧名称当永久依赖。
- 测试 Principles 与 Selection 两次列出相同层级映射，合并保留一处。
- “每个关键流程同时覆盖”全部异常类别应改成覆盖与该流程相关的风险；纯测试不需要独立 Compose，只有访问真实依赖的测试需要。
- “禁止依赖真实模型”限定到确定性工程测试；真实模型 Eval 本来是独立验证，不应被上一条一并禁止。
- root AGENTS.md 可以保留约 10 条稳定约束，把详细矩阵集中到一个测试文档并明确触发读取。不要为了精简把硬约束藏进无人读取的参考里。
- [domain.md:7](../../docs/agents/domain.md) 仍保留多 context 通用结构；本项目已指定 single-context，可删除 multi-context 分支与示例。
- [triage-labels.md:15](../../docs/agents/triage-labels.md) 的“编辑右列”是安装模板提示，可删除；五标签本身和 `complete` 作为交付状态的区分值得保留。

用户级：

- uv / node / pnpm 和子代理调度规则保留。
- “优先成熟依赖”和“先检查现有依赖”可合并为一条。
- “长期架构”和“最小实现、分层交付”不是硬冲突。可以改成“在当前需求下选择可长期维护的最简单方案”，避免诱导过度设计。
- “研究成熟产品再设计”仅在非平凡的新交互或架构决策时要求，不应把每个小修都变成竞品研究。
- `rulers`、`Test Ruler` 改为 `Rules`、`Testing`；修复 `commonfunctionality` 拼写。

### 14. 内置/插件适配问题，不建议手改缓存

- `openai-docs` 的 docs-first 硬顺序与本轮宿主的本地环境优先指导有张力。当前安装审计应先盘点本机事实，官方文档用于核对加载语义。保留该技能，服从更高层运行规则。
- [visualize:23](/Users/koltenluca/.codex/plugins/cache/openai-bundled/visualize/1.0.29/skills/visualize/SKILL.md:23) 禁止 commentary，且禁止宣布技能；宿主要求开始前说明技能并持续提供进度。属于通讯规则冲突，不能让低层技能覆盖宿主。
- Product Design [critical-overrides:38](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/product-design/0.1.53/references/critical-overrides.md:38) 要求每隔一条用户可见消息重读，增加重复 I/O；工作流已加载时应仅在丢失上下文或规则变更后重读。
- `deep-research` 强制 `update_plan`；`plugin-management` 指向 `search_plugins` / `suggest_plugins`；`create-auth` 指向 `AskQuestion`。本轮未暴露这些同名工具，技能应该按实际可用能力适配，不能假定读取 SKILL 就安装了工具。

以上大多是宿主/插件版本适配问题。停用确实不用的插件可以减少误路由；直接改缓存可能被更新覆盖。

### 15. `weread-skills` 远端升级指令缺乏边界

[weread-skills:86](/Users/koltenluca/.agents/skills/weread-skills/SKILL.md:86) 要求收到 `upgrade_info` 后立即按远端 message 完成升级。API 返回值只能提供版本信息，不能自动获得执行任意命令或更新本机软件的授权。

建议：保留微信读书查询能力；升级消息只作为提示，核对官方更新方式和用户授权后处理。它未在本轮初始 skills 列表出现，原因尚未确认，不把这个现象当作“已禁用”证据。

## 建议删除、合并与保留

### 可以从 ThesisTrace 项目级删除

以下三项明确面向 CopilotKit 上游源码仓库，当前项目是消费者：

- `copilotkit-contribute`
- `inspector-docs`
- `inspector-workbench`

以下五项当前没有对应业务需求，适合需要时再装；这是收缩项目工具箱的建议，不是断言它们本身有害：

- `channels-setup`
- `copilotkit-channels`
- `setup-slack-channel`
- `copilotkit-upgrade`（当前已使用 v2，不需要长期保留 v1→v2 专用流程）
- `create-auth`（已有独立 Auth 实现，初始化向导的边际价值较低）

`organization-best-practices`、`two-factor-authentication-best-practices`：当前未见相关插件启用；如果没有近期计划，也可从本项目移除。保留通用 Better Auth、安全、邮箱密码三个参考。

`copilotkit-develop`、`copilotkit-integrations`、`copilotkit-setup`：应先合并有用内容及路由，再删除重复入口；保留前要修正第 7 项冲突。

`copilotkit-self-update`：建议删除或改为仅更新选中技能，避免清理后整套装回。

删除项目安装时同步维护 `skills-lock.json` 和相应 `.claude/skills` 软链接。当前 16 个 CopilotKit 目录为未跟踪新增，锁文件也已有改动，不能用批量 reset/clean 清理。

### 可直接清理的历史残留

- `/Users/koltenluca/.codex/skills/codex-primary-runtime/`：空目录。
- `/Users/koltenluca/code-github/thesistrace/.codex/skills/build-test-data/skill.md`：旧小写文件，与当前 `.agents/skills/build-test-data/SKILL.md` 的短指令基本重复；保留规范路径的一份。
- `grill-me`：只是调用 `grilling` 的别名，可删但收益很小；`grill-with-docs` 额外组合 domain-modeling，仍有独立快捷用途。
- 已禁用的 `chronicle` 可以保持禁用，若确定不再用可移除；不要因磁盘存在就认为它当前在窥看屏幕。

### 不应当作重复直接删除

- `.claude/skills`：22 个有效软链接，目标都是项目 `.agents/skills`，不是双份正文。是否保留取决于是否仍使用 Claude Code。
- `obsidian-cli` 与 `obsidian-markdown`：一个操作 Obsidian，一个负责语法；互补。
- `playwright` 与 `screenshot`：一个浏览器自动化，一个系统截图；互补。
- `codebase-design` 与 `domain-modeling`：模块设计和领域语言，职责不同。
- `research` 与 `deep-research`：轻量后台调查和显式深度研究，触发边界不同。
- `skill-creator`、`skill-installer`、`plugin-creator`：编写、安装、打包，职责不同。
- Better Auth 与 CopilotKit 技术参考：项目确实使用这两类依赖，不能因为数量多就整套删掉。
- 未安装的 recommended plugins 列表不属于已安装 skills，不是清理目标。

## 推荐的收敛结构

用户级 AGENTS.md 只保留运行环境、协作/授权偏好、简单可维护的设计原则、并行写入与 worktree 边界。项目级 AGENTS.md 只保留硬切换、领域/设计/票据入口、关键验证和开发数据保护约束。

技能各自只负责自己的流程：设计入口一个，规划入口一套，测试原则一个权威来源，审阅范围一个明确契约。技能先读取项目约束；不重复定义项目的 schema、测试层级、UI 风格或部署模式。

若按建议精简，项目 23 个技能可收敛到 9 个左右：`build-test-data`、三个 Better Auth 参考、`a2ui-renderer`、`copilotkit-agui`、`copilotkit-debug`、`react-core`、`runtime`。这不是追求固定数量，新增对应功能时再加入专用技能。

## 逐项盘点

下表区分入口可见性与建议；“保留”代表没有发现需要整体删除的理由，不代表所有第三方示例都经过运行验证。

### /Users/koltenluca/.agents/skills

| 技能 | 状态 | 建议 | 理由 |
|---|---|---|---|
| ask-matt（历史位置：`/Users/koltenluca/.agents/skills/ask-matt/SKILL.md`） | 显式调用 | 修正后保留 | 路由承诺与 implement 不一致，引用缺失 wizard；见第 8 项 |
| [code-review](/Users/koltenluca/.agents/skills/code-review/SKILL.md) | 本轮可见 | 修正后保留 | 补 working tree/untracked 范围，保留双轴审阅；见第 4 项 |
| [codebase-design](/Users/koltenluca/.agents/skills/codebase-design/SKILL.md) | 本轮可见 | 保留并收窄绝对规则 | 模块边界词汇有用；删除旧测试须先证明等价替代 |
| context7-cli（历史位置：`/Users/koltenluca/.agents/skills/context7-cli/SKILL.md`） | 本轮可见 | 收窄触发 | 避免任何文档任务都触发全局升级；见第 11 项 |
| [design-taste-frontend](/Users/koltenluca/.agents/skills/design-taste-frontend/SKILL.md) | 本轮可见 | 手动或删除 | 与其他设计入口重叠；产品工作台不在其正文范围 |
| [diagnosing-bugs](/Users/koltenluca/.agents/skills/diagnosing-bugs/SKILL.md) | 本轮可见 | 保留 | 诊断流程独立；故障注入延迟应与任意 sleep 区分 |
| [domain-modeling](/Users/koltenluca/.agents/skills/domain-modeling/SKILL.md) | 本轮可见 | 保留 | 领域语言和 ADR，区别于模块接口设计 |
| [frontend-design](/Users/koltenluca/.agents/skills/frontend-design/SKILL.md) | 本轮可见 | 保留为默认入口 | 三个全局设计入口中最简；仍服从 DESIGN.md |
| [git-commit](/Users/koltenluca/.agents/skills/git-commit/SKILL.md) | 本轮可见 | 保留 | 提交专用；范围必须排除并行无关改动 |
| grill-me（历史位置：`/Users/koltenluca/.agents/skills/grill-me/SKILL.md`） | 显式调用 | 可删除 | grilling 的快捷别名，收益很小 |
| [grill-with-docs](/Users/koltenluca/.agents/skills/grill-with-docs/SKILL.md) | 显式调用 | 保留 | 组合 grilling 与领域文档，有独立快捷用途 |
| [grilling](/Users/koltenluca/.agents/skills/grilling/SKILL.md) | 本轮可见 | 保留为明确选择的流程 | 压力测试与逐项澄清；不用于普通明确实现任务 |
| hallmark（历史位置：`/Users/koltenluca/.agents/skills/hallmark/SKILL.md`） | 本轮可见 | 手动或删除 | 大流程与设计入口重复，且有步骤死结；见第 10 项 |
| [handoff](/Users/koltenluca/.agents/skills/handoff/SKILL.md) | 显式调用 | 保留 | 会话交接产物；与执行或设计技能不重复 |
| implement（历史位置：`/Users/koltenluca/.agents/skills/implement/SKILL.md`） | 显式调用 | 保留并统一契约 | 实际流程短；router 不能承诺它没有的调度与循环 |
| [improve-codebase-architecture](/Users/koltenluca/.agents/skills/improve-codebase-architecture/SKILL.md) | 显式调用 | 保留为手动 | 架构机会发现；不应成为每个小改动的前置步骤 |
| logging-best-practices（历史位置：`/Users/koltenluca/.agents/skills/logging-best-practices/SKILL.md`） | 本轮可见 | 保留 | 日志专用；示例脱敏不是完整生产脱敏策略 |
| [obsidian-cli](/Users/koltenluca/.agents/skills/obsidian-cli/SKILL.md) | 本轮可见 | 保留 | 操作 Obsidian，与 Markdown 语法互补 |
| [obsidian-markdown](/Users/koltenluca/.agents/skills/obsidian-markdown/SKILL.md) | 本轮可见 | 保留 | Obsidian 方言语法，与 CLI 互补 |
| [pdf](/Users/koltenluca/.agents/skills/pdf/SKILL.md) | 本轮可见 | 保留 | 用户级 PDF 能力；缓存中另有未列出的官方 PDF 包 |
| [prototype](/Users/koltenluca/.agents/skills/prototype/SKILL.md) | 本轮可见 | 保留为明确选择的流程 | 用于回答设计问题；不以临时实现替代正式交付 |
| [research](/Users/koltenluca/.agents/skills/research/SKILL.md) | 本轮可见 | 保留 | 轻量研究并落文件；与显式 Deep research 分工不同 |
| resolving-merge-conflicts（历史位置：`/Users/koltenluca/.agents/skills/resolving-merge-conflicts/SKILL.md`） | 本轮可见 | 优先修正 | 去掉全部暂存、永不 abort 的绝对规则；见第 6 项 |
| [setup-matt-pocock-skills](/Users/koltenluca/.agents/skills/setup-matt-pocock-skills/SKILL.md) | 显式调用 | 可移除或保持手动 | 一次性安装向导；避免重新覆盖已定制的项目文档 |
| [shadcn](/Users/koltenluca/.agents/skills/shadcn/SKILL.md) | 本轮可见 | 保留并修正上下文获取 | 动态命令未执行时不可声称已注入 JSON；见第 12 项 |
| [tdd](/Users/koltenluca/.agents/skills/tdd/SKILL.md) | 本轮可见 | 修正后保留 | 测试层级与反复确认约束应服从项目；见第 3 项 |
| [teach](/Users/koltenluca/.agents/skills/teach/SKILL.md) | 显式调用 | 保留为手动 | 教学目标独立，不叠加到普通交付流程 |
| tickets-review（历史位置：`/Users/koltenluca/.agents/skills/tickets-review/SKILL.md`） | 显式调用 | 保留为手动 | 票据质量审阅，不等同代码审阅 |
| [to-spec](/Users/koltenluca/.agents/skills/to-spec/SKILL.md) | 显式调用 | 修正后保留 | 将最高测试边界、单一边界偏好改为服从项目的风险和层级规则 |
| [to-tickets](/Users/koltenluca/.agents/skills/to-tickets/SKILL.md) | 显式调用 | 优先修正 | expand–contract 不适用于本项目；见第 2 项 |
| [triage](/Users/koltenluca/.agents/skills/triage/SKILL.md) | 显式调用 | 保留为手动 | 外部待分类问题入口；已生成 ready 票据不再 triage |
| [tushare](/Users/koltenluca/.agents/skills/tushare/SKILL.md) | 本轮可见 | 保留 | 行情和财务数据来源能力，与项目开发规范不同 |
| vercel-react-best-practices（历史位置：`/Users/koltenluca/.agents/skills/vercel-react-best-practices/SKILL.md`） | 本轮可见 | 保留 | 性能参考；按当前 Vite/React 环境选择条目 |
| [wayfinder](/Users/koltenluca/.agents/skills/wayfinder/SKILL.md) | 显式调用 | 保留为手动 | 跨会话决策探索；不用作所有任务前置流程 |
| [weread-skills](/Users/koltenluca/.agents/skills/weread-skills/SKILL.md) | 磁盘有；本轮未列出 | 修正升级边界 | 远端升级消息不能授予执行权限；见第 15 项 |

### /Users/koltenluca/.codex/skills

| 技能 | 状态 | 建议 | 理由 |
|---|---|---|---|
| [imagegen](/Users/koltenluca/.codex/skills/.system/imagegen/SKILL.md) | 本轮可见 | 保留 | 图像资产工具入口；不规定所有页面都要生成图片 |
| [openai-docs](/Users/koltenluca/.codex/skills/.system/openai-docs/SKILL.md) | 本轮可见 | 保留 | 核对官方产品行为；本机安装状态优先本机证据 |
| [plugin-creator](/Users/koltenluca/.codex/skills/.system/plugin-creator/SKILL.md) | 本轮可见 | 保留 | 插件打包和清单，区别于技能编写与安装 |
| [review-agent](/Users/koltenluca/.codex/skills/.system/review-agent/SKILL.md) | 显式调用 | 保留为手动 | 系统审阅支持，不因名称近似就认定和双轴 review 重复 |
| [skill-creator](/Users/koltenluca/.codex/skills/.system/skill-creator/SKILL.md) | 本轮可见 | 保留 | 编写技能 |
| [skill-installer](/Users/koltenluca/.codex/skills/.system/skill-installer/SKILL.md) | 本轮可见 | 保留 | 安装技能 |
| [chronicle](/Users/koltenluca/.codex/skills/chronicle/SKILL.md) | 配置禁用 | 保持禁用；不用可移除 | 已显式禁用，不属于当前活动冲突 |
| [linear](/Users/koltenluca/.codex/skills/linear/SKILL.md) | 本轮可见 | 保留全局 | 用于明确 Linear 任务；本项目默认仍为本地 Markdown tracker |
| [playwright](/Users/koltenluca/.codex/skills/playwright/SKILL.md) | 本轮可见 | 保留 | 浏览器自动化；与系统截图不同 |
| [screenshot](/Users/koltenluca/.codex/skills/screenshot/SKILL.md) | 本轮可见 | 保留 | 系统/桌面截图；与浏览器自动化不同 |

### /Users/koltenluca/code-github/thesistrace/.agents/skills

| 技能 | 状态 | 建议 | 理由 |
|---|---|---|---|
| [a2ui-renderer](../../.agents/skills/a2ui-renderer/SKILL.md) | 本轮可见 | 保留并核对版本 | 当前项目使用；指南 1.70.0、依赖 1.69.3 |
| [better-auth-best-practices](../../.agents/skills/better-auth-best-practices/SKILL.md) | 本轮可见 | 保留 | 当前项目认证基础 |
| [better-auth-security-best-practices](../../.agents/skills/better-auth-security-best-practices/SKILL.md) | 本轮可见 | 保留 | 认证安全参考，与普通配置互补 |
| [build-test-data](../../.agents/skills/build-test-data/SKILL.md) | 显式调用 | 完善后保留 | 补隔离环境、最小数据、成功判据和清理；删除旧小写副本 |
| [channels-setup](../../.agents/skills/channels-setup/SKILL.md) | 本轮可见 | 项目可删除 | 当前无 Slack/Teams Channel 需求 |
| [copilotkit-agui](../../.agents/skills/copilotkit-agui/SKILL.md) | 本轮可见 | 保留 | 协议和自定义后端，符合本项目用途 |
| [copilotkit-channels](../../.agents/skills/copilotkit-channels/SKILL.md) | 本轮可见 | 项目可删除 | 当前无 Slack/Teams Channel 需求 |
| copilotkit-contribute（历史位置：`.agents/skills/copilotkit-contribute/SKILL.md`） | 本轮可见 | 项目可删除 | 面向 CopilotKit 上游贡献者 |
| [copilotkit-debug](../../.agents/skills/copilotkit-debug/SKILL.md) | 本轮可见 | 保留 | 当前依赖的专门故障诊断 |
| [copilotkit-develop](../../.agents/skills/copilotkit-develop/SKILL.md) | 本轮可见 | 合并后删除重复入口 | 与 runtime/react-core 重叠且 handler 建议冲突 |
| [copilotkit-integrations](../../.agents/skills/copilotkit-integrations/SKILL.md) | 本轮可见 | 合并后删除重复入口 | 框架对接内容按需保留；handler/useAgent 指南不一致 |
| copilotkit-self-update（历史位置：`.agents/skills/copilotkit-self-update/SKILL.md`） | 本轮可见 | 删除或改选定更新 | 通用触发词和整套安装会恢复冗余技能 |
| [copilotkit-setup](../../.agents/skills/copilotkit-setup/SKILL.md) | 本轮可见 | 合并后删除重复入口 | 已集成；旧 handler 指南需要修正 |
| [copilotkit-upgrade](../../.agents/skills/copilotkit-upgrade/SKILL.md) | 本轮可见 | 项目可删除 | 当前已使用 v2，专门迁移流程无需常驻 |
| [create-auth](../../.agents/skills/create-auth/SKILL.md) | 本轮可见 | 项目可删除 | 已有 Auth；新建向导价值低且依赖未提供的问答工具 |
| [email-and-password-best-practices](../../.agents/skills/email-and-password-best-practices/SKILL.md) | 本轮可见 | 保留 | 现有邮件密码认证功能 |
| inspector-docs（历史位置：`.agents/skills/inspector-docs/SKILL.md`） | 本轮可见 | 项目可删除 | 面向上游 Inspector 文档维护 |
| inspector-workbench（历史位置：`.agents/skills/inspector-workbench/SKILL.md`） | 本轮可见 | 项目可删除 | 面向上游独立 Inspector 开发环境 |
| [organization-best-practices](../../.agents/skills/organization-best-practices/SKILL.md) | 本轮可见 | 无近期计划可删除 | 当前未启用 organization 插件 |
| [react-core](../../.agents/skills/react-core/SKILL.md) | 本轮可见 | 保留并核对版本 | 当前 React 接口主体；建议增加 CopilotKit 名称前缀 |
| [runtime](../../.agents/skills/runtime/SKILL.md) | 本轮可见 | 保留并核对版本 | 当前 fetch handler 路径；建议增加 CopilotKit 名称前缀 |
| [setup-slack-channel](../../.agents/skills/setup-slack-channel/SKILL.md) | 本轮可见 | 项目可删除 | 当前无 Slack Channel 需求 |
| [two-factor-authentication-best-practices](../../.agents/skills/two-factor-authentication-best-practices/SKILL.md) | 本轮可见 | 无近期计划可删除 | 当前未启用 twoFactor 插件 |

### /Users/koltenluca/.codex/plugins/cache/openai-curated-remote/deep-research-work/0.1.14/skills

| 技能 | 状态 | 建议 | 理由 |
|---|---|---|---|
| [deep-research](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/deep-research-work/0.1.14/skills/deep-research/SKILL.md) | 本轮可见 | 保留 | 仅明确深度研究触发；需适配实际可用规划工具 |

### /Users/koltenluca/.codex/plugins/cache/openai-curated-remote/product-design/0.1.53/skills

| 技能 | 状态 | 建议 | 理由 |
|---|---|---|---|
| [audit](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/product-design/0.1.53/skills/audit/SKILL.md) | 本轮可见 | 保留 | 截图证据支持产品体验审计 |
| [design-qa](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/product-design/0.1.53/skills/design-qa/SKILL.md) | 显式调用 | 保留辅助入口 | Product Design 验收步骤，非重复默认入口 |
| [get-context](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/product-design/0.1.53/skills/get-context/SKILL.md) | 显式调用 | 保留辅助入口 | Product Design 上下文收集 |
| [ideate](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/product-design/0.1.53/skills/ideate/SKILL.md) | 本轮可见 | 保留 | 图像方案探索，和日常前端实现分开 |
| [image-to-code](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/product-design/0.1.53/skills/image-to-code/SKILL.md) | 本轮可见 | 保留 | 选定视觉参考的实现 |
| [index](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/product-design/0.1.53/skills/index/SKILL.md) | 本轮可见 | 保留路由 | Product Design 唯一协调入口；不要叠加普通组件修复 |
| [research](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/product-design/0.1.53/skills/research/SKILL.md) | 显式调用 | 保留辅助入口 | Product Design 的 UX 研究步骤，区别于通用 research |
| [share](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/product-design/0.1.53/skills/share/SKILL.md) | 显式调用 | 保留辅助入口 | 用户要求分享时的部署交付 |
| [url-to-code](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/product-design/0.1.53/skills/url-to-code/SKILL.md) | 本轮可见 | 保留 | 明确 URL 临摹 |
| [user-context](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/product-design/0.1.53/skills/user-context/SKILL.md) | 显式调用 | 保留辅助入口 | Product Design 用户上下文管理 |

### /Users/koltenluca/.codex/plugins/cache/openai-curated-remote/plugin-management/0.1.0/skills

| 技能 | 状态 | 建议 | 理由 |
|---|---|---|---|
| [plugin-management](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/plugin-management/0.1.0/skills/plugin-management/SKILL.md) | 本轮可见 | 保留并适配工具 | 插件管理专用；描述中的部分工具本轮不可用 |

### /Users/koltenluca/.codex/plugins/cache/openai-curated-remote/superpowers/6.3.0/skills

| 技能 | 状态 | 建议 | 理由 |
|---|---|---|---|
| brainstorming（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/superpowers/6.3.0/skills/brainstorming/SKILL.md`） | 配置禁用 | 保持禁用 | 与既有规划/澄清流程重叠，无当前隐式冲突 |
| dispatching-parallel-agents（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/superpowers/6.3.0/skills/dispatching-parallel-agents/SKILL.md`） | 配置禁用 | 保持禁用 | 宿主和用户调度规则已存在 |
| executing-plans（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/superpowers/6.3.0/skills/executing-plans/SKILL.md`） | 配置禁用 | 保持禁用 | 与 implement 等执行流程重叠 |
| finishing-a-development-branch（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/superpowers/6.3.0/skills/finishing-a-development-branch/SKILL.md`） | 配置禁用 | 保持禁用 | 不重新叠加另一套分支收尾协议 |
| receiving-code-review（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/superpowers/6.3.0/skills/receiving-code-review/SKILL.md`） | 配置禁用 | 保持禁用 | 当前未启用此反馈处理工作流 |
| requesting-code-review（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/superpowers/6.3.0/skills/requesting-code-review/SKILL.md`） | 配置禁用 | 保持禁用 | 保留现有 code-review 作为默认审阅入口 |
| subagent-driven-development（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/superpowers/6.3.0/skills/subagent-driven-development/SKILL.md`） | 配置禁用 | 保持禁用 | 与现有执行和宿主调度规则重叠 |
| systematic-debugging（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/superpowers/6.3.0/skills/systematic-debugging/SKILL.md`） | 配置禁用 | 保持禁用 | 已有 diagnosing-bugs |
| test-driven-development（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/superpowers/6.3.0/skills/test-driven-development/SKILL.md`） | 配置禁用 | 保持禁用 | 已有 tdd，避免两套默认流程 |
| using-git-worktrees（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/superpowers/6.3.0/skills/using-git-worktrees/SKILL.md`） | 本轮可见 | 优先修正或停用 | sandbox 原地继续、预先提交与包管理器默认冲突 |
| using-superpowers（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/superpowers/6.3.0/skills/using-superpowers/SKILL.md`） | 磁盘有；本轮未列出 | 不新增为默认入口 | 缓存中存在，本轮未列出；泛化触发会增加流程叠加 |
| verification-before-completion（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/superpowers/6.3.0/skills/verification-before-completion/SKILL.md`） | 配置禁用 | 保持禁用 | 项目/用户已有验证契约 |
| writing-plans（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/superpowers/6.3.0/skills/writing-plans/SKILL.md`） | 配置禁用 | 保持禁用 | 已有 to-spec/to-tickets |
| writing-skills（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/superpowers/6.3.0/skills/writing-skills/SKILL.md`） | 磁盘有；本轮未列出 | 不新增为默认入口 | 缓存中存在，本轮未列出；已有 skill-creator |

### /Users/koltenluca/.codex/plugins/cache/openai-bundled/visualize/1.0.29/skills

| 技能 | 状态 | 建议 | 理由 |
|---|---|---|---|
| [visualize](/Users/koltenluca/.codex/plugins/cache/openai-bundled/visualize/1.0.29/skills/visualize/SKILL.md) | 本轮可见 | 保留并修正通讯冲突 | 交互可视化有用；禁 commentary 不能覆盖宿主规则 |

## 额外缓存盘点：119 个未在本轮初始技能目录出现的入口

额外遍历了整个插件缓存，读取 119 个 SKILL.md 的元数据并筛查强制规则。加上上述 95 个，共找到 214 个规范命名的 SKILL.md；另有一份小写历史文件。这里的“未列出”不等于已卸载或已禁用，不能仅凭缓存目录判定当前可调用性。以下按插件/版本列全入口；这些包不列入本轮 60 个可见技能的活动冲突统计。

### openai-bundled/sites/0.1.57（2）

[sites-building](/Users/koltenluca/.codex/plugins/cache/openai-bundled/sites/0.1.57/skills/sites-building/SKILL.md)、[sites-hosting](/Users/koltenluca/.codex/plugins/cache/openai-bundled/sites/0.1.57/skills/sites-hosting/SKILL.md)。

配置明确禁用，保持禁用即可；它包含默认部署流程，不应重新用作当前仓库的一般前端入口。

### openai-curated-remote/cloudflare/0.1.2（9）

[agents-sdk](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/cloudflare/0.1.2/skills/agents-sdk/SKILL.md)、[building-ai-agent-on-cloudflare](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/cloudflare/0.1.2/skills/building-ai-agent-on-cloudflare/SKILL.md)、[building-mcp-server-on-cloudflare](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/cloudflare/0.1.2/skills/building-mcp-server-on-cloudflare/SKILL.md)、[cloudflare](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/cloudflare/0.1.2/skills/cloudflare/SKILL.md)、[durable-objects](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/cloudflare/0.1.2/skills/durable-objects/SKILL.md)、[sandbox-sdk](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/cloudflare/0.1.2/skills/sandbox-sdk/SKILL.md)、[web-perf](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/cloudflare/0.1.2/skills/web-perf/SKILL.md)、[workers-best-practices](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/cloudflare/0.1.2/skills/workers-best-practices/SKILL.md)、[wrangler](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/cloudflare/0.1.2/skills/wrangler/SKILL.md)。

Cloudflare 特定技术栈参考，不能因名字含 agent 就用于当前 Node/RustFS 架构。需要部署到该平台时再启用。

### openai-curated-remote/codex-security/0.1.23（15）

[assess-patch-risk](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/codex-security/0.1.23/skills/assess-patch-risk/SKILL.md)、[attack-path-analysis](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/codex-security/0.1.23/skills/attack-path-analysis/SKILL.md)、[deep-security-scan](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/codex-security/0.1.23/skills/deep-security-scan/SKILL.md)、[define-security-policy](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/codex-security/0.1.23/skills/define-security-policy/SKILL.md)、[finding-discovery](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/codex-security/0.1.23/skills/finding-discovery/SKILL.md)、[fix-finding](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/codex-security/0.1.23/skills/fix-finding/SKILL.md)、[propose-security-hardening](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/codex-security/0.1.23/skills/propose-security-hardening/SKILL.md)、[security-diff-scan](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/codex-security/0.1.23/skills/security-diff-scan/SKILL.md)、[security-scan](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/codex-security/0.1.23/skills/security-scan/SKILL.md)、[threat-model](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/codex-security/0.1.23/skills/threat-model/SKILL.md)、[track-findings](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/codex-security/0.1.23/skills/track-findings/SKILL.md)、[triage-finding](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/codex-security/0.1.23/skills/triage-finding/SKILL.md)、[validation](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/codex-security/0.1.23/skills/validation/SKILL.md)、[verify-fix](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/codex-security/0.1.23/skills/verify-fix/SKILL.md)、[vulnerability-writeup](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/codex-security/0.1.23/skills/vulnerability-writeup/SKILL.md)。

存在 openai-curated/d6169bef 与 openai-curated-remote/0.1.23 两个来源，工作流与数量不同。应由插件管理统一来源/版本；目前没有证据证明两套入口同时注入。

### openai-curated-remote/investment-banking/0.1.29（23）

[buyer-investor-list](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/buyer-investor-list/SKILL.md)、[capital-markets-issuance](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/capital-markets-issuance/SKILL.md)、[cim-builder](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/cim-builder/SKILL.md)、[cim-teardown](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/cim-teardown/SKILL.md)、[company-tearsheet](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/company-tearsheet/SKILL.md)、[comps-valuation](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/comps-valuation/SKILL.md)、[covenant-package-analyzer](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/covenant-package-analyzer/SKILL.md)、[dcf-model-builder](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/dcf-model-builder/SKILL.md)、[deal-process-tracker](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/deal-process-tracker/SKILL.md)、[distressed-recovery-waterfall](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/distressed-recovery-waterfall/SKILL.md)、[financials-normalizer](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/financials-normalizer/SKILL.md)、[ib-deck-qc](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/ib-deck-qc/SKILL.md)、[investment-banking](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/investment-banking/SKILL.md)、[lbo-model-build](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/lbo-model-build/SKILL.md)、[meeting-prep](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/meeting-prep/SKILL.md)、[memo-builder](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/memo-builder/SKILL.md)、[merger-model-builder](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/merger-model-builder/SKILL.md)、[model-audit-tieout](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/model-audit-tieout/SKILL.md)、[pitch-deck-builder](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/pitch-deck-builder/SKILL.md)、[private-credit-underwriting](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/private-credit-underwriting/SKILL.md)、[scenario-sensitivity-generator](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/scenario-sensitivity-generator/SKILL.md)、[three-statement-model-builder](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/three-statement-model-builder/SKILL.md)、[user-context](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/investment-banking/0.1.29/skills/user-context/SKILL.md)。

两套包含多个同名建模/备忘录技能，但分别针对交易融资与公开市场研究；保留插件命名空间和路由区分，不按短名称批量去重。

### openai-curated-remote/openai-templates/0.1.1（20）

[artifact-template-analytics-dashboard](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-analytics-dashboard/SKILL.md)、[artifact-template-business-review](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-business-review/SKILL.md)、[artifact-template-design-report](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-design-report/SKILL.md)、[artifact-template-experiment-analysis](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-experiment-analysis/SKILL.md)、[artifact-template-financial-budget](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-financial-budget/SKILL.md)、[artifact-template-investment-committee-memo](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-investment-committee-memo/SKILL.md)、[artifact-template-legal-memorandum](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-legal-memorandum/SKILL.md)、[artifact-template-market-trends-report](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-market-trends-report/SKILL.md)、[artifact-template-minimal-letterhead](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-minimal-letterhead/SKILL.md)、[artifact-template-operating-calendar](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-operating-calendar/SKILL.md)、[artifact-template-operating-review](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-operating-review/SKILL.md)、[artifact-template-project-kickoff](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-project-kickoff/SKILL.md)、[artifact-template-project-tracker](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-project-tracker/SKILL.md)、[artifact-template-sales-pipeline](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-sales-pipeline/SKILL.md)、[artifact-template-simple-dark-mode](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-simple-dark-mode/SKILL.md)、[artifact-template-simple-light-mode](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-simple-light-mode/SKILL.md)、[artifact-template-strategy-memorandum](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-strategy-memorandum/SKILL.md)、[artifact-template-system-design](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-system-design/SKILL.md)、[artifact-template-team-alignment](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-team-alignment/SKILL.md)、[artifact-template-three-statement-forecast](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/openai-templates/0.1.1/skills/artifact-template-three-statement-forecast/SKILL.md)。

按明确模板名触发的 20 种产物模板，不是 20 个互相竞争的默认设计工作流；不用可停用整个模板插件。

### openai-curated-remote/public-equity-investing/0.1.31（23）

[catalyst-calendar](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/catalyst-calendar/SKILL.md)、[company-tearsheet](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/company-tearsheet/SKILL.md)、[comps-valuation](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/comps-valuation/SKILL.md)、[dcf-model-builder](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/dcf-model-builder/SKILL.md)、[deck-report-qc](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/deck-report-qc/SKILL.md)、[earnings-deep-dive](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/earnings-deep-dive/SKILL.md)、[earnings-preview](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/earnings-preview/SKILL.md)、[economic-impact-report](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/economic-impact-report/SKILL.md)、[equity-model-update](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/equity-model-update/SKILL.md)、[event-driven-analyzer](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/event-driven-analyzer/SKILL.md)、[financials-normalizer](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/financials-normalizer/SKILL.md)、[idea-generation](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/idea-generation/SKILL.md)、[initiating-coverage](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/initiating-coverage/SKILL.md)、[long-short-pitch](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/long-short-pitch/SKILL.md)、[meeting-prep](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/meeting-prep/SKILL.md)、[memo-builder](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/memo-builder/SKILL.md)、[model-audit-tieout](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/model-audit-tieout/SKILL.md)、[portfolio-risk-management](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/portfolio-risk-management/SKILL.md)、[public-equity-investing](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/public-equity-investing/SKILL.md)、[scenario-sensitivity-generator](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/scenario-sensitivity-generator/SKILL.md)、[thesis-tracker](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/thesis-tracker/SKILL.md)、[three-statement-model-builder](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/three-statement-model-builder/SKILL.md)、[user-context](/Users/koltenluca/.codex/plugins/cache/openai-curated-remote/public-equity-investing/0.1.31/skills/user-context/SKILL.md)。

两套包含多个同名建模/备忘录技能，但分别针对交易融资与公开市场研究；保留插件命名空间和路由区分，不按短名称批量去重。

### openai-curated/codex-security/d6169bef（10）

[attack-path-analysis](/Users/koltenluca/.codex/plugins/cache/openai-curated/codex-security/d6169bef/skills/attack-path-analysis/SKILL.md)、[deep-security-scan](/Users/koltenluca/.codex/plugins/cache/openai-curated/codex-security/d6169bef/skills/deep-security-scan/SKILL.md)、[finding-discovery](/Users/koltenluca/.codex/plugins/cache/openai-curated/codex-security/d6169bef/skills/finding-discovery/SKILL.md)、[fix-finding](/Users/koltenluca/.codex/plugins/cache/openai-curated/codex-security/d6169bef/skills/fix-finding/SKILL.md)、[security-diff-scan](/Users/koltenluca/.codex/plugins/cache/openai-curated/codex-security/d6169bef/skills/security-diff-scan/SKILL.md)、[security-scan](/Users/koltenluca/.codex/plugins/cache/openai-curated/codex-security/d6169bef/skills/security-scan/SKILL.md)、[threat-model](/Users/koltenluca/.codex/plugins/cache/openai-curated/codex-security/d6169bef/skills/threat-model/SKILL.md)、[track-findings](/Users/koltenluca/.codex/plugins/cache/openai-curated/codex-security/d6169bef/skills/track-findings/SKILL.md)、[triage-finding](/Users/koltenluca/.codex/plugins/cache/openai-curated/codex-security/d6169bef/skills/triage-finding/SKILL.md)、[validation](/Users/koltenluca/.codex/plugins/cache/openai-curated/codex-security/d6169bef/skills/validation/SKILL.md)。

存在 openai-curated/d6169bef 与 openai-curated-remote/0.1.23 两个来源，工作流与数量不同。应由插件管理统一来源/版本；目前没有证据证明两套入口同时注入。

### openai-curated/github/d6169bef（4）

[gh-address-comments](/Users/koltenluca/.codex/plugins/cache/openai-curated/github/d6169bef/skills/gh-address-comments/SKILL.md)、[gh-fix-ci](/Users/koltenluca/.codex/plugins/cache/openai-curated/github/d6169bef/skills/gh-fix-ci/SKILL.md)、[github](/Users/koltenluca/.codex/plugins/cache/openai-curated/github/d6169bef/skills/github/SKILL.md)、[yeet](/Users/koltenluca/.codex/plugins/cache/openai-curated/github/d6169bef/skills/yeet/SKILL.md)。

GitHub 能力独立；gh-fix-ci 仍要求修复前重新审批，若未来启用，应识别用户已明确授权的修复，避免重复确认。

### openai-curated/gmail/d6169bef（2）

[gmail-inbox-triage](/Users/koltenluca/.codex/plugins/cache/openai-curated/gmail/d6169bef/skills/gmail-inbox-triage/SKILL.md)、[gmail](/Users/koltenluca/.codex/plugins/cache/openai-curated/gmail/d6169bef/skills/gmail/SKILL.md)。

保留为按需插件；不因与当前项目无关就手删缓存。

### openai-curated/hyperframes/d6169bef（5）

[gsap](/Users/koltenluca/.codex/plugins/cache/openai-curated/hyperframes/d6169bef/skills/gsap/SKILL.md)、[hyperframes-cli](/Users/koltenluca/.codex/plugins/cache/openai-curated/hyperframes/d6169bef/skills/hyperframes-cli/SKILL.md)、[hyperframes-registry](/Users/koltenluca/.codex/plugins/cache/openai-curated/hyperframes/d6169bef/skills/hyperframes-registry/SKILL.md)、[hyperframes](/Users/koltenluca/.codex/plugins/cache/openai-curated/hyperframes/d6169bef/skills/hyperframes/SKILL.md)、[website-to-hyperframes](/Users/koltenluca/.codex/plugins/cache/openai-curated/hyperframes/d6169bef/skills/website-to-hyperframes/SKILL.md)。

保留为按需插件；不因与当前项目无关就手删缓存。

### openai-primary-runtime/documents/26.903.11726（1）

documents（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-primary-runtime/documents/26.903.11726/skills/documents/SKILL.md`）。

保留为按需插件；不因与当前项目无关就手删缓存。

### openai-primary-runtime/pdf/26.903.11726（1）

pdf（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-primary-runtime/pdf/26.903.11726/skills/pdf/SKILL.md`）。

与用户全局 pdf 功能重叠；若以后两者同时可见，选一个默认 PDF 入口。本轮只有用户级 pdf 出现在目录。

### openai-primary-runtime/presentations/26.903.11726（1）

presentations（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-primary-runtime/presentations/26.903.11726/skills/presentations/SKILL.md`）。

保留为按需插件；不因与当前项目无关就手删缓存。

### openai-primary-runtime/spreadsheets/26.903.11726（2）

excel-live-control（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-primary-runtime/spreadsheets/26.903.11726/skills/excel-live-control/SKILL.md`）、spreadsheets（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-primary-runtime/spreadsheets/26.903.11726/skills/spreadsheets/SKILL.md`）。

保留为按需插件；不因与当前项目无关就手删缓存。

### openai-primary-runtime/template-creator/26.903.11726（1）

template-creator（历史位置：`/Users/koltenluca/.codex/plugins/cache/openai-primary-runtime/template-creator/26.903.11726/skills/template-creator/SKILL.md`）。

保留为按需插件；不因与当前项目无关就手删缓存。

## 审阅边界

此次没有运行业务测试，因为没有修改业务实现；没有执行任何被审阅技能中的安装、升级、部署、提交或删除指令。建议落实时先处理硬冲突，再删无用途入口；项目技能、锁文件与软链接作为一组变更，用户技能与插件配置另行分组，保留现有并行工作。
