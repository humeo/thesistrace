# 工程结构与运行管理重构
Status: ready-for-agent

经用户批准，在独立工作树完成以下四个单元，每个单元验证、双轴审查、单独提交。最后运行 pnpm check 和 pnpm test:image-smoke，并使用隔离环境做浏览器验收。

## 约束
- 不修改业务逻辑、数据库 Schema、HTTP/MCP 契约、依赖和基础镜像版本。
- 硬切换旧目录和管理入口，不留兼容包装、fallback 或迁移。
- 不修改、重置或删除 thesistrace-dev 容器、卷、Canonical/Benchmark 数据和 Dataset Head；不修改其他工作树。
- 保留生产环境根目录外、root 所有、0600 的非符号链接配置文件。统一管理工具使用 Node 24 ESM。
- 保留现有 pnpm 入口与测试分层，增加 pnpm prod <validate|up|down|status|logs|run>。

## 01 配置与生命周期
单一字段定义包含类型、默认值、必填条件和敏感标识，驱动模板、初始化、校验、私有 CLI、开发与生产入口。文件权威，清除环境同名及派生变量，Compose 使用 --env-file /dev/null。拒绝重复、未知、非法字面值，错误仅代码和字段。PUBLIC_ORIGIN 派生 DEV_WEB_PORT、MCP_ISSUER_URL、MCP_RESOURCE_URL、MCP_ALLOWED_HOSTS、MCP_ALLOWED_ORIGINS。接纳并校验所有 Worker CPU/内存/执行预算/线程参数。生产安全约束保持。stop/status/logs/down 根据精确项目标签操作现有资源，不依赖配置或外部密钥；down 保留卷。启动和执行校验配置。保留项目、服务、卷名。

## 02 目录与共享包
apps/{core,web,auth,agent} 各自拥有源码、配置、测试和 Dockerfile；Core 拥有 pyproject/uv.lock/benchmarks，内部 module-first 不变，API/Worker 共用镜像。packages/contracts 显式工作区包和四个子路径导出，Agent/Web 用 workspace:* 引用。deploy 下 base/dev/test/prod overlays、caddy、postgres。tooling/{config,dev,test,patches} 管理工程工具。tests 仅跨应用 E2E、最终镜像测试和共享 Fixture。Agent Scripted Provider Fixture 随应用打包且不复制。更新所有路径与文档/构建引用，不搬运缓存或私有旧数据。

## 03 测试工具
迁移前记录测试文件归属和实际收集清单；每项仍被唯一测试入口收集。测试工具拆分资源管理、阶段执行、证据和清理，复用既有行为及 Fixture，保留并发容量、E2E 分组和镜像复用。验证并发、超时、信号与清理失败传播。确定性测试不调用真实模型或 Tushare。

## 04 部署与验收
Compose 运行与构建分层，最终 Dockerfile 位于应用。5180 等非默认端口发布到 Caddy 实际监听端口。Watch 覆盖共享包、patches、Caddy 以及构建输入；配置和模型变更由 dev:up 应用。现有本机构建模式不变，镜像证据记录实际 image ID。完善入口、目录、环境变量和部署运行说明。跑完整 pnpm check、pnpm test:image-smoke 及隔离浏览器验收；无实测不得声称通过。
