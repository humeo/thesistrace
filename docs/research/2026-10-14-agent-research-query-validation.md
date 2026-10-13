# MCP 研究记录查询实现与验收

2026-10-14。已实现查找、结构化过滤和全局指标排序；真实 Agent 在已命名的既有会话中，三次均正确返回前十。设计依据见[调研记录](2026-10-14-agent-research-query-mcp.md)，真实模型的机器可读证据见[验收报告](2026-10-14-agent-research-query-eval.json)。

## 实现

扩展现有 `list_research_runs`，没有增加同义查询工具。HTTP 列表和 MCP 复用 ResearchRun Module 的查询值、参数化筛选、数值排序、摘要投影和计数。HTTP 保留页码，MCP 使用绑定当前研究者和完整查询条件的不透明 keyset cursor。

- 文本查找覆盖名称、备注和 Formula 的字面子串；支持 Folder、研究类型、状态、精确回测区间、Universe 筛选。
- 复用六项现有指标、四种比较符及 AND 条件；百分比以小数表达，指标查询必须明确匹配的研究类型。
- 权限和所有过滤先于全体匹配记录的排序与 LIMIT。同分稳定排序，两个方向均 NULLS LAST；缺失值不作为有效名次。
- 返回有界摘要、Universe、精确 `total_count`、规范化 `applied_query` 和 `next_cursor`。计数与当页属于同一 SQL 快照；跨页仍是实时集合。
- 沿用 32 KiB 页预算，cursor 从实际保留的最后一条记录生成。改变条件或跨研究者复用 cursor 会明确拒绝。
- 内置 Agent 的工具发现逻辑保持原有入口，补充查询指导、指标单位和排名范围说明。MCP schema、工具描述及 Web 工具说明同步更新。

未新增数据库表、索引或迁移。当前数据投影已包含需要的字段。查询对象是策略回测 ResearchRun，包括 Batch 子记录；同名回测不会自动去重，DailyTrack 的表现不混入排名。

例如“全部成功策略中，夏普至少 1、回撤最多 20%，按夏普取前十”：

```json
{
  "research_kind": "strategy_backtest",
  "status": "succeeded",
  "metric_filters": [
    {"metric": "sharpe", "operator": "gte", "value": 1},
    {"metric": "maximum_drawdown", "operator": "lte", "value": 0.20}
  ],
  "sort_by": "sharpe",
  "sort_direction": "descending",
  "limit": 10
}
```

## 真实 Agent 前十验收

通过仓库现有隔离评估入口运行真实 Agent Host、动态 MCP discovery 和真实模型调用。运行版本为 `f2472b188541160e414c9d32108b7981fbbc3876`，启动时 tracked diff 为空；运行编号 `20261013t210440z-71128-a062c316`。镜像、初始化、运行及清理阶段均退出 0。

使用现有评估 profile `gpt-5.6-luna / high`，选择新增的 `global-strategy-top-ten` 案例，重复三次。此结果只覆盖该 profile 和查询场景，不代表生产默认模型或完整评估 corpus 已获得资格。

每次使用独立身份和已命名的自有会话，保留正常身份鉴权和每日额度。先完成一条真实策略模板回测，再在隔离数据库中建立 65 条明确标注的摘要查询样本，共 66 条。固定 Sharpe 包含正值、负值和 NULL；前十最高分记录的创建时间均早于其他 56 条，不能通过先取最新 50 条获得。固定摘要指标用于验证查询和呈现，与策略投资效果无关。

评分器核对完整查询条件、所有权、返回 ID 及顺序，并核对最终表格的名称、三项指标、单位和区间，或原生研究列表视图的有序 ID。禁止提交、重跑或启动追踪；不允许取得足够前十后继续遍历剩余集合。正确分页路径可以不同。

| 重复 | 结果 | 耗时 | 工具调用 | 工具错误 | 参考价格估算 |
| --- | --- | --- | --- | --- | --- |
| 1 | 通过 | 34.030 s | 2 | 0 | $0.040610 |
| 2 | 通过 | 28.850 s | 2 | 0 | $0.029312 |
| 3 | 通过 | 31.423 s | 2 | 0 | $0.018407 |

任务成功率 3/3，非法及禁止工具调用均为 0，所有权检查全部通过，token accounting 完整。总输入 230,672 tokens，输出 3,445 tokens，其中 reasoning 991；按现有 Standard 参考价格估算总额 $0.088329，并非代理服务的实际账单。报告 `qualified=true` 仅指所选单案例的三次评估。

## 工程验证

测试入口和选择原则继续以根 [AGENTS.md](../../AGENTS.md#testing) 为准。

| 验证范围 | 实测结果 |
| --- | --- |
| Core 受影响契约、MCP、Ownership、trajectory 单元检查 | 修复旧 fixture 后 118 passed |
| Agent 完整单元检查 | 693 passed / 54 files |
| 后续 eval 报告、排名评分及 stream 定向回归 | 89 passed |
| 当前 eval preflight（含 build） | 12 passed |
| Core lint，Agent/Auth/Web/E2E 类型检查，Web UI ownership | 通过 |
| 真实依赖 Ownership/查询集成 | 9 passed，包括旧页高分前十、全部筛选、数值排序、NULL、正反向 cursor，以及 stdio schema 发现与调用 |
| 同次 MCP Worker 验收 | 4 passed；另 1 条 Worker 重启用例失败，见下节 |
| Auth 单元检查 | 209 passed |
| Core bounded_process 检查 | 192 passed |

确定性工程检查没有依赖真实模型。真实模型验收单独记录，不以 Scripted/Replay 结果代替。

已快进合入本地 `main@a0b5d513`。在目标 checkout 复验查询/MCP/Ownership 契约为 107 passed，Agent 排名及报告回归为 89 passed，Agent 类型检查通过。该目标版本相较真实评估版本只增加验收文档，Core、Agent、Web 及测试运行代码完全相同。原有两个未跟踪研究目录保持原样；未推送或部署。

## 查询性能

运行 `20261013t200648z-41348-ad5253fc`，隔离 PostgreSQL 中共 100 用户、每人 1,000 条记录，共 100,000 条，冻结输入平均 3,660 bytes。复用现有性能入口；先核对原始/索引搜索结果相等，再以当前 Module 实际 SQL 验证指标查询的 ID、顺序、总数和计划。

| 指标查询 | Median | P95 |
| --- | --- | --- |
| 数值升序 | 33.410 ms | 46.284 ms |
| 数值降序 | 27.490 ms | 38.825 ms |
| 阈值过滤后排序 | 28.118 ms | 34.635 ms |

16 路并发关键词查询：现有索引实现 Median 85.502 ms、P95 146.396 ms，原始实现 1,256.918 / 2,972.409 ms。测量包含本机暖缓存下 SQL 执行、传输和连接池等待；不代表生产 SLA。本次没有增加索引，清理退出 0。

## 首次失败及尚未验证的边界

保留失败，不把补跑通过等同于所有问题已解决。

- 首次 Core 快速检查为 2,647 passed / 4 failed，原因是旧 fixture 缺少当前必填 Universe、旧 fake cursor 和旧方法签名。修正 fixture 后，受影响的 118 项检查通过。
- 真实依赖组总体为 13 passed / 1 failed。`test_stdio_research_runs_survive_disconnect_and_real_worker_restarts` 在策略 Worker 子进程超过原有 60 秒时限，发生在重连查询之前。该失败未通过增加时限或反复重跑消除；完整 Worker 重启场景仍未验证通过。证据保存在该次运行的 `pytest.xml`。
- 扩展 Web 单元检查出现 6 个失败（5 个超时及 DataPage 元素未就绪）；单 worker 定向检查为 32 passed / 1 failed，失败项为 DataPage 缓存场景。A2UI 和 Chat 生命周期检查通过。将本任务唯一 Web 改动的工具说明恢复为 main 内容后，DataPage 同文件基线为 3/3 通过；这不足以证明原失败已解决。完整快速检查未全绿。
- 早期两次真实评估在 Host 资源门禁拒绝，尚未调用回答模型：旧验收器要求 1 CPU/1 GiB，当前 Compose 为 2 CPU/4 GiB。下一次模板提交因缺少当前 `initial_cash_cny` 被 422 拒绝。更新验收器和完整框架 fixture 后，模板成功完成。
- 随后一次新会话回答在 `DAILY_MODEL_BUDGET_EXCEEDED` 门禁拒绝，尚未调用查询工具。原因是标题生成和主回答共用正常每日额度，按模型登记最大容量预留的金额存在冲突。本次使用合法的已命名既有会话验证查询，报告显式记为 `named-existing`；生产标题与预算逻辑没有在本任务中修改，新会话场景尚未验证通过。
- 同步修正当前 email OTP 测试 fixture 调用、评估异常变量作用域和最多十条 artifact 的报告约束；有界支出、缺失 accounting 时停止及隔离清理规则保持有效。

没有运行完整 E2E、发布资格门禁或全 corpus 真实模型评估，也未部署生产环境。此次交付结论是：当前 MCP 查询契约和已命名既有会话的全局前十场景有实测证据。

## 证据位置

原始阶段记录、pytest XML、性能 JSON、Web 失败及基线结果均保留在实施工作树的 `.local/test-runs/`：

- 集成：`20261013t195623z-36159-1d1bad26/evidence/pytest.xml`。
- 性能：`20261013t200648z-41348-ad5253fc/evidence/research-search.json`。
- 模型：`20261013t210440z-71128-a062c316/evidence/research-agent-eval.json` 及同次 `run.txt`。
- Web：`query-quick-continuation/web-targeted.json`、`web-main-baseline.json` 和阶段日志。

已将成功的真实模型报告原样保存为本文链接的 JSON；未保存模型文本、工具 payload 或凭证到该报告。
