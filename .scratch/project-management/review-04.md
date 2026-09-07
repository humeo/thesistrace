# 单元 04 双轴审查与最终验收

范围：daa2d3c 后的 Compose Watch、环境与部署文档、最终验收。

## 双轴审查

首次快照 `/private/tmp/thesistrace-management-review-04-75259g70`。
Standards 发现生产文档混淆启动前配置拒绝与运行期 Worker 不可用；Spec 发现 Eval 示例的四项控制会被私有配置入口清除。已分别修正文档和显式环境注入顺序。

复审快照 `/private/tmp/thesistrace-management-review-04-46vp0tu3`：Standards、Spec 各 0 项，smell 建议 0 项。凭据封装通过无模型调用的本地探针验证；没有进行付费 Eval。

完整集成测试随后发现真实命名卷测试仍引用已删除的旧入口。独立真实卷测试先复现 FileNotFoundError，再将调用改为 `product-state-volumes.mjs`，1 项通过；保留数据及清理断言未改。增量快照 `/private/tmp/thesistrace-management-review-04-kya5sji2` 再审：Standards、Spec 各 0 项。

完整 E2E 又暴露两类既有测试时序问题，均未修改业务源码：

- 登录成功响应耗时 7233ms，旧页面断言在请求完成前耗尽 5000ms。真实应用加临时 6500ms 延迟稳定复现；登录 helper 注册并等待对应 POST 响应后，同样延迟下完整账户生命周期 1 项通过（15s）。原失败密码、权限和跳转断言保留；全局超时未变。
- 返回已有 Chat 时，历史加载后的自动滚动关闭已打开菜单，Batch 和 DailyTrack 两个用例因此等待删除菜单直到超时。真实历史请求 gate 复现先开菜单后加载的失败；等待最后回复进入视口再开菜单，1 项通过（3.9s）。等待仅加在两个返回历史页面的位置，原删除和数据存续断言保留。

临时诊断文件已删除。登录复审快照 `/private/tmp/thesistrace-management-review-04-zps2pcvm`、最终菜单复审快照 `/private/tmp/thesistrace-management-review-04-rabto7uw`：Standards、Spec 均 0 项。

严格镜像检查又暴露三项测试环境契约问题，已用实际依赖定位并修复：

- 镜像环境的 PostgreSQL/RustFS 仅连接 internal 网络，声明的宿主端口实际不可用。两项测试基础设施加入已有 edge 网络，继续仅发布到 127.0.0.1；业务服务的内部网络边界保持。真实最小探针连接 PostgreSQL 并创建、读取 S3 bucket 通过。
- 镜像环境 RustFS 使用观测 canary 凭据，宿主检查仍使用普通测试凭据。hostEnvironment 按既有 image overlay 选择匹配凭据，四种测试命令的回归先失败后通过；全部 Node 工具测试现为 28 项通过。
- 镜像 MCP harness 固定 resource 为 `https://core.test/mcp`，Caddy 检查误用普通 E2E origin。调用方显式传入各自当前 resource，保持业务 MCP 配置不变；fake curl 同步真实 harness。原发布资格模拟先失败，修复后完整生命周期 82 项通过。

镜像网络/凭据快照 `/private/tmp/thesistrace-management-review-04-suz2z0gr` 与最终 MCP 检查快照 `/private/tmp/thesistrace-management-review-04-mtcuk_ss`：Standards、Spec 各 0 项。

## 已完成验证

- 配置校验、Watch 相关 3 项测试、Compose 实际渲染与差异格式检查通过。
- 使用私有临时配置验证 5180 的发布端口、Caddy 目标端口及 MCP identity 一致；未输出凭据。
- 最终全量快速检查通过：Python 1126、Node 工具 27、Agent 638、Auth 196、Web 345，类型检查及 Ruff 通过；组件浏览器 17 项通过。
- 首轮 Core 集成 421 通过、1 失败；入口修复后完整 Core 集成 422 通过，另 6 项真实依赖重启恢复通过。Auth 138、Agent 91 项真实 PostgreSQL 集成通过。
- E2E 三个受影响文件的独立 TypeScript 检查通过。
- 全量 `pnpm check` 的 E2E 共 78 项：初次 75 通过、上述 3 项失败，七个独立状态分组全部通过；该次命令退出 1。修复后使用 `THESISTRACE_TEST_PLAYWRIGHT_GREP` 经原 `pnpm test:e2e` 入口在全新环境复验登录、Batch 两模式和 DailyTrack，4 项全通过（2.1 分钟），命令及清理退出 0。未重跑未受影响的快速与真实依赖检查，也不将原失败命令记为退出 0。

## 最终镜像证据

主流程运行 `20260907t111820z-76354-16425474`：构建、启动健康、容量拒绝、子进程 cgroup OOM、Caddy 路由和后端独立性、依赖故障恢复、Operator 生命周期、研究计算、Worker 中断恢复、数据库重启持久化、对象存储重试恢复、观测日志、MCP HTTP/stdio、Operator 浏览器场景及秘密扫描均通过。主流程与清理退出 0。

该次实际 Docker image ID（由 `docker image inspect` 记录）：

| 镜像 | image ID |
| --- | --- |
| Core / API / Workers | `sha256:129de023fb4a616501dd7f9f25937d552b6c02d03db294ec73e292f3bd1c1382` |
| Auth | `sha256:7abc94985ef3b92f4afe71b4cd877aeb30dd53f63253fc4e2089244bc1d7a52b` |
| Agent | `sha256:268c2dc180eaf57c0278117a914f6df20cc88680f2f0b85b0139bb86ccb24f55` |
| Web | `sha256:08cb6bca776abc5331ed7b16e6b5edf375d522fb24a26c86f6e49376041f0ebf` |

后续 Auth、Agent 独立镜像和 Caddy HTTPS 镜像检查均通过，根命令 `pnpm test:image-smoke` 退出 0。完整输出保存在忽略目录 `.local/project-management/final-image-smoke-complete.txt`。

## 浏览器与环境保护

- 使用原 E2E 启动阶段创建独立 5180 项目，应用内浏览器实测登录、Data overview、Research workspace、Scripted Chat 和刷新后的登录态保持通过；所有导航均保持 `http://127.0.0.1:5180`。该端口的 Caddy 发布/监听及 MCP metadata identity 也通过原检查入口。未调用真实模型。
- 浏览器环境及清理退出 0；页面证据位于忽略目录 `.local/project-management/browser-5180-data.png`、`browser-5180-chat.txt`、`browser-5180.json`。
- Development 前后快照严格比较：13 个容器的 ID、镜像、运行状态、挂载完全一致；`data.current_dataset_state` 完全一致。未重置或删除开发数据。
- 从本任务日志和运行元数据提取 48 个精确测试项目及 1 个 Caddy 镜像测试前缀，实际 Docker 清单核对没有遗留容器、卷或网络。证据为 `.local/project-management/cleanup-audit.json`。
- 本单元最终源码双轴审查无未解决项。所有四个单元完成后仅提交隔离分支；未合并、推送或操作真实生产环境，也未执行付费模型评估。
