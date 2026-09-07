# 测试体系整理交付记录

Status: complete

## 最终版本与门禁

2026-09-07，在独立工作区 `.worktrees/test-suite-final-acceptance` 验证固定提交
`3e3e723613fc549439f6189e61f90eff5cfd5b27`。该提交包含本轮所有测试修复，
以及并行任务合入的 DailyTrack 改动。两道门禁串行执行，均实际退出 0。
随后只补充本记录与断言迁移表，没有改变已测试代码。

| 命令 | 结果 | 范围 |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/thesistrace-uv-cache mise exec -- pnpm check` | 0 | 归属检查、7 项运行器检查、Python 1144、Agent 638、Eval preflight 11、Auth 196、Web 345、轻量浏览器 17；Core 集成 426 加 6 个重启场景、Auth 集成 138、Agent 集成 91；E2E 78 |
| `UV_CACHE_DIR=/tmp/thesistrace-uv-cache mise exec -- pnpm test:image-smoke` | 0 | Core 启动、健康、依赖中断、研究与跟踪、重启恢复、生产 MCP、Operator 浏览器；Auth、Agent、Caddy 独立镜像验收 |

Core 集成中的 8 个 deselected 是运行器明确分流的重启及真实 Codex 场景，
不是失败后跳过；6 个重启场景随后单独执行并通过。真实 Codex／真实模型效果、
性能采样和发布资格门禁不属于本轮范围，没有声称通过。

本机保留的完整日志：

- [完整产品门禁](../../.worktrees/test-suite-final-acceptance/.local/test-suite-restructure/check.log)
- [完整镜像门禁](../../.worktrees/test-suite-final-acceptance/.local/test-suite-restructure/image-smoke.log)
- [反向顺序验收](../../.worktrees/test-suite-final-acceptance/.local/test-suite-restructure/reverse-e2e.log)

日志和原始运行证据位于忽略目录，未提交大体积产物或敏感原文。

## 隔离与耗时证据

完整 E2E：普通集合 71 项共用一个新环境，另 7 项分别使用新环境，全部成功。
所有环境独立项目名、端口和卷；构建一次，后续复用同一批镜像。
每组环境清理和最终 9 个源镜像标签清理均返回 0。

以下单位为秒，来自各环境 `run.txt`。初始化列合计基础设施、初始化、
基线准备和应用就绪阶段；清理列只计资源清理，日志收集等未硬凑入测试耗时。

| 集合 | 构建／复用 | 初始化 | 测试执行 | 清理 |
| --- | ---: | ---: | ---: | ---: |
| 普通 71 项 | 32 | 24 | 412 | 14 |
| Financial catalog | 1 | 24 | 30 | 13 |
| Draft／Folder | 1 | 23 | 34 | 14 |
| Operator 访问控制 | 1 | 24 | 14 | 13 |
| Operator 研究员／邀请 | 1 | 22 | 15 | 12 |
| Operator Market | 1 | 30 | 35 | 12 |
| Operator Financial／Industry | 0 | 22 | 42 | 14 |
| Operator Dataset／Worker | 2 | 25 | 29 | 13 |

因此新增的独立环境成本可以单独观察，不能把它直接算成业务用例变慢。
没有在不同机器负载或不同版本之间宣称性能提升。

固定版本工作区内的证据索引：

- `.local/e2e-runs/1788767092565-82855/results.json`、`cleanup.json`
- `.local/test-runs/20260907t072801z-62159-b359e2ae/`：Core 集成与重启 XML
- `.local/test-runs/20260907t080128z-231-450e6fb3/`：完整 Core 镜像阶段和证据

反向实测使用 `THESISTRACE_TEST_E2E_GROUP_ORDER=reverse` 配合筛选，依次运行
Operator Financial／Industry → Financial catalog → 普通 MCP 恢复场景，全部退出 0。
原主工作区证据为 `.local/e2e-runs/1788764589512-21448/`。
此外，先前普通组失败后，后续 7 个独立场景仍全部从固定基线成功运行并清理，
证据为原主工作区 `.local/e2e-runs/1788762712283-93608/`。
取消策略保持停止调度后续组、清理当前自有资源；没有声明另做过真实中途取消演练。

## 发现、修复与复核

- RustFS 3 项和 ModelPicker 4 项进入正常集合；Web 自动发现测试文件。
  归属检查拒绝未归属、同层重复和错误命名归属，且与 Vitest 实际列表核对。
  在新建顶层目录放置临时测试的真实探针被拒绝，清除探针后检查通过。
- 聊天终态绑定提交返回的 Turn；Continue 和 Answer 分别使用正确身份。
  5 项确定性浏览器辅助函数测试验证旧终态、URL 延迟、失败及同 Turn 恢复。
  MCP 工具详情的最终检查移到匹配 Turn 完成之后，避免完成时自动收起与展开竞争。
- Operator 按独立目标拆分；Financial／Industry 自行准备 Market 前置数据。
  轮询移到受控时钟组件测试，保留同一操作由 accepted 到 succeeded 的断言，
  不用空列表代替完成状态。原始覆盖去向见[断言迁移表](assertion-migration.md)。
- Agent 单测限制最多 4 个 Worker，解决同时加载大上下文／Mastra 的资源争用；
  不增加重试，不修改单测全局超时。打包 MCP 启动失败检查由 10 秒改为同类
  启动契约的 20 秒，保留退出码与错误断言，8 项定向入口测试通过。
- 删除重复 `test:benchmark` 别名，保留 `check:performance`，路由／启动契约
  已经由架构检查验证；保留有定向价值的 Caddy 入口，完整镜像门禁包含它。
- 一轮完整门禁在运行期间遇到其他任务合并 `main`，旧父进程与新子进程混用
  DailyTrack 状态契约，产生 19 项失败。保留 `/tmp/test-restructure-full-check-r4.log`，
  改为固定提交的独立工作区后，完整集合通过；未通过修改业务逻辑处理混合版本。

此前的失败未以“重跑变绿”结案：工具展示竞态、资源并行度、启动预算均有具体修复；
版本混用则通过隔离工作区消除原因。最终成功记录只对应上述固定提交。

### Standards review

复核过测试断言、最小合法夹具、身份绑定、清理错误传播及文档。
审查发现的空列表终态替代、清理查询失败被吞掉、过大共享夹具和等待诊断问题均已修复，
复核无遗留问题；后续 MCP 等待顺序和反向分组改动也通过复核。

### Spec review

复核测试收集、按身份等待、全局数据隔离、镜像复用、浏览器分层和 Operator 覆盖迁移。
已有关键业务断言保留；未证明无用的测试没有删除。最终验收以真实退出记录为准。

## 提交与范围

| 提交 | 内容 |
| --- | --- |
| `85848e0` | 收集归属与重复性能入口整理 |
| `a45af08` | 聊天权威 Turn 等待 |
| `fce8b88` | 全局数据场景隔离及镜像复用 |
| `94f5bbe` | 浏览器分层、Operator 拆分及断言迁移 |
| `d0132c1` | 限制 Agent 单测资源并行度 |
| `bcdb7be` | 收集边界及打包进程启动预算 |
| `b7cba35` | MCP 终态展示竞态及反向环境顺序验收 |
| `f2550e8` | 记录资源清理耗时 |

本任务的修改限于测试、夹具、运行入口和文档。没有删除或重置
`thesistrace-dev` 容器数据、卷或 Dataset Head，也没有增加兼容、迁移或 fallback。
测试命令归属见[本地生命周期文档](../../docs/runbook/local-lifecycle.md)。
