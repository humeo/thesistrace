## rulers
- Do not preserve backward compatibility. Remove obsolete paths instead of adding compatibility layers, fallbacks, or migrations.
- ** 在开发过程中永远不要fallback，迁移和兼容 **

## Browser Operations

Prioritize the [`browser:control-in-app-browser`](/Users/koltenluca/.codex/plugins/cache/openai-bundled/browser/26.721.41059/skills/control-in-app-browser/SKILL.md) skill for browser operations.

## Frontend Design

Frontend design and implementation must follow the repository-root [`DESIGN.md`](DESIGN.md).

## Agent skills

### Issue tracker

Issues and specs are tracked as local Markdown files under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Triage uses the five default canonical label strings. See `docs/agents/triage-labels.md`.

### Domain docs

Domain documentation uses a single-context layout. See `docs/agents/domain.md`.

## Test Ruler

核心目标：让错误在最早、最便宜、最容易定位的阶段被可靠发现。

### Testing Principles

- 先识别系统最可能失败的位置，再选择能以最低成本可靠发现问题的测试；不要以测试数量或覆盖率为目标。
- 测试可观察行为和业务不变量，不依赖私有函数、调用次数等实现细节。
- 在最低且足够真实的层级测试：
  - 纯业务规则：单元测试
  - 数据库、事务、权限、队列、Worker：真实依赖的集成测试
  - HTTP、事件和 Schema 兼容性：契约测试
  - 关键用户闭环：少量 E2E
  - 容器、配置和运行依赖：Production Image Smoke Test
- 自有数据库、Redis、队列和 Worker 原则上不 Mock；第三方付费、远程或不确定服务使用 Stub、Replay、Fake 或 Sandbox。
- 测试必须快速、独立、可重复、自动判定，并与功能同时交付。
- 固定时间、时区、随机种子、UUID、测试数据和依赖版本；禁止依赖公网、执行顺序或真实模型。
- 禁止任意 `sleep`；使用有超时的条件轮询，失败时输出当前状态和相关日志。
- 每个测试独立准备数据和环境，不共享可变状态；使用最小合法 Factory 构造测试数据。
- 测试环境必须与开发和生产隔离；每次运行使用独立 Compose Project、网络、数据卷、数据库和账号，并在结束后清理。
- CI 流程必须能通过一个本地命令完整复现；关键流程不要只存在于 CI YAML。
- 每个关键流程同时覆盖成功、非法输入、无权限、超时、错误、重复、并发、部分成功、重试、取消和恢复。
- 所有异步、Webhook、支付及 Agent 任务必须验证幂等性、并发领取、崩溃恢复和重复投递。
- 每个线上 Bug：先添加能稳定复现问题的失败测试，再修复并保留为回归测试。
- 不接受“重跑后通过”的 Flaky Test；重试只用于收集证据，关键 Flaky Test 仍阻止发布。
- 测试失败必须自动保存足够的诊断信息，包括日志、退出码、请求响应、状态、Trace ID、随机种子、截图及镜像版本。
- 发布测试针对最终 Production Image，而不只是源码；构建后必须验证启动、健康检查、迁移、API 和 Worker 链路。

### Test Selection

根据变更范围选择测试：

- 业务逻辑：单元测试
- SQL/Repository：数据库集成测试
- API/事件：集成测试与契约测试
- Schema：迁移、前后版本兼容和回滚测试
- Worker：队列集成、幂等、并发、重试和恢复测试
- 权限：未授权、越权和租户隔离测试
- 前端关键流程：E2E
- Dockerfile/Compose：配置校验、全栈启动和镜像 Smoke Test
- 第三方接口：Stub 契约与 Sandbox 测试
- Agent Harness：Fake Model 确定性轨迹测试与独立模型 Eval
- 性能敏感代码：Benchmark 与性能回归测试
- 鉴权/Secret：安全测试和日志泄漏检查

### AI/Agent Testing

- 将确定性工程测试与概率性模型评估分开。
- 使用 Fake、Scripted Response 或 Replay 测试状态机、工具权限、审批、超时、重试、恢复、计费和审计。
- 断言任务完成、产物、权限、成本、时延等不变量，不断言模型输出的逐字内容。
- 真实模型 Eval 使用固定数据集，统计成功率、成本、P95 时延、工具错误率和多次运行方差。
