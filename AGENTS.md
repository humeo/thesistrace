## rulers
- Do not preserve backward compatibility. Remove obsolete paths instead of adding compatibility layers, fallbacks, or migrations.
- ** 在开发过程中永远不要fallback，迁移和兼容 **

## Browser Operations

For interactive browser inspection and acceptance, prefer the available in-app browser tools. Use the repository's Playwright tests for repeatable browser regression checks.

## Frontend Design

Frontend design and implementation must follow the repository-root [`DESIGN.md`](DESIGN.md).

## Agent skills

### Issue tracker

Issues and specs are tracked as local Markdown files under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Triage uses the five default canonical label strings. See `docs/agents/triage-labels.md`.

### Domain docs

Domain documentation uses a single-context layout. See `docs/agents/domain.md`.

## Testing

当前项目处于开发阶段，采用硬切换。验证当前实现和契约，不为尚未存在的线上存量状态增加迁移、旧版本兼容或回滚流程。

### 选择验证

先识别本次改变的行为和最可能失败的边界，再选择成本最低且足够真实的验证。复用已有测试、Fixture 和运行入口；不以测试数量、覆盖率或固定检查清单代替判断。已有需求和项目约束足够明确时，自行决定验证范围，不重复请求确认。

| 变更 | 优先验证 |
|---|---|
| 文档、注释、纯样式 | 内容、链接、格式或实际渲染；不为低风险改动新增重复测试 |
| 业务规则、计算、状态转换 | 通过公开接口验证行为和业务不变量的单元测试 |
| 数据库、事务、权限、Worker | 真实依赖的集成测试；针对受影响边界选择隔离、并发、幂等、重试或恢复场景 |
| HTTP、MCP、事件、Schema | 当前契约的成功/拒绝行为、约束和初始化；不添加旧版本兼容路径 |
| 关键用户流程 | 相关组件测试与真实浏览器验收；核心闭环使用少量可重复 E2E |
| 容器、启动配置、运行依赖 | 构建最终镜像，验证启动、健康检查及受影响的 API/Worker 链路 |

### 入口与成本

测试用途、选择和运行说明只维护在本节；其他文档链接到这里，不另建 runbook。
命令使用 `.mise.toml` 固定的工具版本，可加 `mise exec --` 前缀。以下耗时是本机历史参考，包含启动和清理成本；首次构建、缓存和机器负载会改变耗时，不是超时预算。

| 入口 | 验证内容与使用时机 | 已有耗时参考 |
|---|---|---|
| `pnpm test` | Python/Node/各应用的快速测试、lint 和类型检查；涉及多个模块的日常快速检查 | 约 4 分 10 秒 |
| `pnpm test:browser` | Web 组件在真实浏览器中的交互；组件行为变化时运行 | 约 17 秒 |
| `pnpm test:integration` | Core、Auth、Agent 的真实依赖验证，含事务、权限和故障恢复；跨服务或依赖边界变化时运行 | 上轮累计约 22 分钟，含失败后的补跑，不是单次基线 |
| `pnpm test:e2e` | 浏览器驱动的产品闭环，含分组隔离环境；关键流程或全面回归时运行 | 约 21 分 50 秒 |
| `pnpm test:image-smoke` | 构建镜像、初始化和服务健康、Caddy 路由、一条真实 API → Research Worker → Result 链路；容器和启动配置变化时运行 | 2026-09-08 实测约 4 分 04 秒，含缓存构建 41 秒、清理 23 秒 |
| `pnpm test:image:qualification` | 完整镜像验收：故障注入、重启恢复、Operator 流程、日志与凭证边界，以及 Auth、Agent 和 Caddy 独立镜像检查；恢复、安全部署边界变化或发布资格验证时运行 | 拆分前同一完整覆盖约 14 分钟 |
| `pnpm check` | 快速检查、浏览器组件、集成和 E2E 的完整产品回归；跨模块交付或明确要求全面验证时运行 | 各阶段串行累加 |
| `pnpm check:release` | `check` 加完整镜像验收；仅明确进行发布资格验证时运行 | 各阶段串行累加，不重复跑短镜像检查 |

镜像测试复用确定性 Replay 和测试 OAuth Harness，不访问真实模型或数据供应商。短检查不证明故障恢复、完整 Agent 推理流程或生产 HTTPS 配置正确；这些边界由完整镜像验收负责。组件交互、数据库权限与网关认证虽涉及同一功能，但验证边界不同，不按测试名称相似就删除覆盖。

### 定向运行

先运行受影响的现有测试。例如（将路径或用例名称替换为本次涉及的对象）：

```sh
# Core 纯单元测试，无需 Compose
uv run --project apps/core pytest -c apps/core/pyproject.toml --rootdir . apps/core/tests/kernel/test_alpha_expression_contract.py
# Auth / Agent 的定向真实依赖测试：保留现有隔离运行器
pnpm --dir apps/auth test:integration <test_file>
pnpm --dir apps/agent test:integration <test_file>
# E2E 按用例名称选择，仍使用隔离拓扑
THESISTRACE_TEST_PLAYWRIGHT_GREP='用例名称' pnpm test:e2e
```

Core 完整集成入口会执行普通集成及专门的依赖重启阶段；不能用一次普通 pytest 执行声称重启阶段已验证。性能敏感改动使用 `pnpm check:performance`，在空闲机器上保留基线和对比；普通改动不运行该项。`pnpm test:codex-mcp`、`pnpm check:live-tushare` 和应用的真实模型评估是专用检查，按涉及的外部边界和授权选择，不属于确定性日常门禁。

测试运行器在 `.local/test-runs/` 保存阶段命令、耗时、退出码和诊断证据，E2E 分组汇总在 `.local/e2e-runs/`。失败先读该次证据，再修复和复跑受影响范围；报告区分首次失败、修复后的通过以及未运行的链路。

### 执行原则

- 可稳定复现的行为缺陷先补失败回归测试，再修复；仅能在运行环境复现时，先保留复现步骤和证据，再建立可靠的验证方式。诊断和读代码不必等待测试写完。
- 测试断言可观察结果和业务不变量，不绑定私有函数、调用次数或模型输出原文；预期值不能照抄实现计算。旧测试只在行为覆盖已被等价替代且失去独立价值时删除。
- 使用最小合法数据；控制影响结果的时间、时区和随机性，避免依赖执行顺序或共享可变状态。等待异步结果使用有超时的条件轮询，不用任意 sleep。
- 当结论依赖数据库事务、权限、队列或 Worker 行为时，用真实依赖验证；第三方远程、付费或不确定服务使用 Stub、Replay、Fake 或 Sandbox。确定性工程测试不依赖公网和真实模型。
- 集成、E2E 和镜像测试使用仓库现有隔离运行入口，使用独立的测试身份和数据，并清理本次创建的资源。纯单元测试无需启动 Compose。不得重置或删除 `thesistrace-dev` 的容器数据、数据卷或 Dataset Head。
- 失败时保留足够定位问题的命令、退出码和相关状态/日志；按问题补充请求、trace、截图等证据。不得把不稳定测试“重跑后通过”当作问题已解决。

### 完成标准

- 迭代时先跑受影响测试及相应 lint/typecheck；通过后不重复跑无关检查。跨模块影响、失败或未解决疑点出现时再扩大范围。
- 使用当前 `package.json` 中的入口：`pnpm test` 为快速检查集合；真实依赖和用户闭环分别使用 `pnpm test:integration`、`pnpm test:e2e`。完整产品回归使用 `pnpm check`，在跨模块交付或用户要求全面验证时运行，不要求每个小改动都跑全套。
- 容器和启动变更先跑 `pnpm test:image-smoke`；恢复或安全部署边界变化再选择完整镜像验收。只有明确进行发布资格验证时才使用 `pnpm check:release`。
- 用户要求合并时，在目标版本复跑本次变更对应的必要检查；合并本身不触发 `pnpm check` 或发布全套，也不重复已验证且未变化的无关阶段。没有实测的链路不得声明通过；交付说明已验证范围、结果和仍被阻塞或未验证的部分。

### Agent 验证

使用 Scripted/Fake/Replay 模型验证任务状态、工具权限、超时和恢复等工程行为。模型效果评估独立进行：涉及提示词、模型或工具策略且需要评估效果时，使用固定案例，记录成功率、成本和时延。工程测试通过不等于真实模型效果已经验证。
