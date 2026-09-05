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
- 容器、运行依赖或发布候选变更使用 `pnpm test:image-smoke`；只有明确进行发布资格验证时才使用 `pnpm check:release`。性能敏感变更需要相关基线和对比，普通改动无需跑 benchmark。
- 用户要求合并时，在目标版本复跑本次变更对应的必要检查。没有实测的链路不得声明通过；交付说明已验证范围、结果和仍被阻塞或未验证的部分。

### Agent 验证

使用 Scripted/Fake/Replay 模型验证任务状态、工具权限、超时和恢复等工程行为。模型效果评估独立进行：涉及提示词、模型或工具策略且需要评估效果时，使用固定案例，记录成功率、成本和时延。工程测试通过不等于真实模型效果已经验证。
