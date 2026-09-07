# 单元 02 双轴审查

范围：1487bed 后的目录、工作区包、应用构建和路径迁移。
首次快照 /private/tmp/thesistrace-management-review-02-1c3lkeqq；最终快照 /private/tmp/thesistrace-management-review-02-z3tzvmmd。

## Standards

首次发现四项：Auth Fixture 容器内路径错误、MCP 镜像预检锁文件路径错误、双重测试归属断言失效、Benchmark 文档未选择迁移后的 Python 项目。均已修正。复审剩余 0 项，未发现新增代码气味。

## Spec

首次发现三项：Auth Fixture 容器内路径错误、MCP 镜像预检锁文件路径错误、Benchmark 命令缺少 Core 项目选择。均已修正。复审剩余 0 项；根 ESM、归属及版本断言修复符合迁移要求。

Standards 未解决 0 项；Spec 未解决 0 项。

## 验证

- 原有 274 个测试文件均存在且唯一归属；迁移前后 Python 测试函数均为 1165 个；集成层收集 430 项（确定性入口排除真实模型 1 项）。产品 E2E 78 项与基线标题/分组一致。
- 快速 Python 全组 1123 passed，发现一项 workspace 包版本断言遗漏后修正，相关 9 项复验通过；此前 19 项路径断言失败均已定向复验通过。Ruff、三应用 typecheck、跨应用 E2E typecheck 通过。
- Node 工具 20 passed；修复双重归属回归先失败后通过。Agent 单元 638、Auth 单元 196、Web 单元 345、Agent preflight 11 均通过；Auth runner 四项路径复验通过。
- 四个应用最终 Dockerfile 构建成功；最终 Agent 镜像四个 contracts 子路径及 Scripted Fixture 可加载；Core API/Worker 可加载。
- 在真实镜像复现 Auth 模块加载与 MCP 锁文件路径错误后修复：三个 Auth Fixture 加载及 HTTP 启动通过，MCP image preflight 通过。
- pnpm 外部 packages/snapshots 无新增、删除或版本变化；uv.lock 字节不变。实际 config:check 通过。完整 pnpm check 和 image-smoke 留待单元 04。
