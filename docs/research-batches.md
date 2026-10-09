# 编写和使用研究 Batch

Batch 把共享研究区间和股票池的研究放在一次执行中。平台在受理时固定同一 Data Generation；每个研究仍有独立的 ResearchRun、状态、结果和账户。

当前通过 Agent/MCP 的 `submit_research_batch` 提交。网页提供批次列表、详情、刷新、取消和子研究结果入口，不提供批次创建表单。手动编写 Python 的方式见 [Python 策略编写指南](python-strategy.md)，与是否使用 Batch 无关。

## 选择哪一种

| `batch_kind` | 输入场景 | 共享什么 |
| --- | --- | --- |
| `factor_evaluation` | 多个 Alpha，使用相同评估配置 | 数据分片、股票池和未来收益标签；各 Alpha 分别计算 |
| `strategy_sweep` | 一个公式 Alpha，使用多套策略配置 | 一次 Alpha/中性化计算形成的共享结果；各账户独立模拟 |
| `independent_strategies` | 同一区间、同一股票池的多条完整策略 | 有界数据窗口；公式与中性化设置相同的研究还共享 Alpha 计算 |

`independent_strategies` 可以混用不同公式、Python 程序、Framework 和 Direct 模式。每项携带自己的完整配置，以及适用的中性化设置。不同研究区间或股票池应分别提交。

当前 `strategy_sweep` 契约也接受全部 Direct 或全部 Python Alpha 的配置项，但这些项没有可共享的公式 Alpha 产物。提交多个独立 Python 程序时，使用 `independent_strategies`，让它们在同一数据窗口内推进并复用输入。

不提供“多个 Alpha × 多套配置”的自动展开参数。例如 3 个 Alpha 各测 4 套配置，分别提交 3 个单 Alpha 的 `strategy_sweep` 即可。不要为了使用 Batch 把已有公式改写成 Python。

## 两个公式策略的完整提交例子

先用 `get_research_context` 确认可用日期、股票池和数据就绪状态；以下日期仅作结构示例。`diagnose_research_spec` 验证每条完整策略，`submit_research_batch` 最后对整批原子受理。

```json
{
  "request_id": "momentum-and-reversal-001",
  "batch_kind": "independent_strategies",
  "start_date": "2024-01-02",
  "end_date": "2024-12-31",
  "universe": "top300",
  "strategies": [
    {
      "item_key": "momentum",
      "name": "60 日动量",
      "formula": "pct_change(close, 60)",
      "neutralization": "industry",
      "initial_cash_cny": "1000000",
      "holdings_count": 30,
      "selection_every_sessions": 5
    },
    {
      "item_key": "reversal",
      "name": "5 日反转",
      "formula": "-pct_change(close, 5)",
      "neutralization": "none",
      "initial_cash_cny": "1000000",
      "holdings_count": 20,
      "selection_every_sessions": 5
    }
  ]
}
```

每项使用普通策略回测的配置字段；只把 `request_id`、研究区间和 `universe` 提到批次顶层，用 `item_key` 标识各项。各项不传 `research_kind`、`folder_id` 或单独的日期；平台将它们组织到“批量研究”文件夹。

- Framework 公式项：`formula`、`neutralization`、资金、持仓数、调仓间隔；可选普通回测支持的权重、仓位、模块、费用等配置。
- Framework Python 项：通过 `modules` 选择 Python 阶段，其 `program.source` 使用普通策略接口。使用 Python Alpha 时不填写公式和中性化；公式 Alpha 与其他 Python 阶段可以同时使用。
- Direct Python 项：`strategy_mode: "direct"`、`initial_cash_cny`、`program: {"source": "..."}`，以及可选费用和描述。不填写 Framework 专属字段。

费用省略时使用普通回测的当前默认值。资金和费用的十进制数值字段使用字符串。完整机器可读约束来自 MCP 工具的当前 JSON Schema；`get_authoring_reference(topic="workflow", symbol="batches")` 提供相同的用法说明。

每批 1–20 项，`item_key` 必须唯一。重复的计算配置会被拒绝，名称不同不构成不同研究。任意一项不合法时整批拒绝，错误包含对应项和字段路径，不会只创建其中几条。网络结果不确定时，用相同 `request_id` 和完全相同的参数重试；修改参数后使用新的 ID。

## 执行、读取和取消

MCP 受理返回 `outcome: "accepted"`、`batch_id` 和 `next_tool: "get_research_batch"`。使用该 ID 调用 `get_research_batch`，获得按提交顺序排列的子 Run ID 和状态，按返回的 `retry_after_seconds` 轮询；结果通过各子 Run 的 `get_research_run_result` 读取。Batch 自身没有合并收益率或合成账户。

独立策略在同一数据窗口内分别推进账户，然后进入下一窗口。多个账户显示“运行中”不代表多个不受限的 Python 进程同时执行。每项的进度和状态分别记录。

某条策略程序发生确定性错误时，该项失败，其余研究继续。行业或财务等可选依赖读取失败时，只停止使用该依赖的研究。基础设施中断后保留已完整发布的结果，未完成的策略从该完整任务的起点重试；分片账户状态用于本次执行，并不作为持久恢复检查点。最多三次任务尝试。共同必需的行情无法读取、资源超限等批次级故障可能影响所有未完成项。

`cancel_research_batch(batch_id, request_id)` 取消整批尚未完成的任务，保留已经完成的结果。网页取消按钮使用同一语义；取消后重新查询，直到看到终态。删除聊天不会取消批次。

## 公式与 Python 混合提交

下面将行业中性化的动量策略与 Python 编写的等权股票池策略放进一批。Python 程序一次返回当前数据块的多日目标组合；这里的选股逻辑是“全部可交易的股票”，每五个研究交易日调整一次。

```json
{
  "request_id": "mixed-strategies-001",
  "batch_kind": "independent_strategies",
  "start_date": "2024-01-02",
  "end_date": "2024-12-31",
  "universe": "top300",
  "strategies": [
    {
      "item_key": "momentum",
      "formula": "pct_change(close, 60)",
      "neutralization": "industry",
      "initial_cash_cny": "1000000",
      "holdings_count": 30,
      "selection_every_sessions": 5
    },
    {
      "item_key": "equal_weight",
      "strategy_mode": "direct",
      "initial_cash_cny": "1000000",
      "program": {
        "source": "from quantgrove import Targets\n\ndef compute(data, state):\n    return Targets.equal_weight(\n        data.eligible,\n        update=(data.session_index % 5 == 0) & data.eligible.any(axis=0),\n        reason='Equal-weight eligible universe',\n    )\n"
      }
    }
  ]
}
```

## 拒绝、单项失败与取消示例

以下使用上述示例说明操作顺序；Batch 和 Run ID 以实际工具返回为准。

| 情况 | 返回与后续操作 |
| --- | --- |
| 将第一个例子中的反转公式改成 `unknown_field` | 提交返回 `outcome: "rejected"`，错误包含 `item_key: "reversal"`、`field: "strategies[1].formula"`；两条研究都不会创建。修正公式，使用新的 `request_id` 提交。 |
| 混合示例的 Python `compute` 在运行时抛出 `ValueError` | 受理仍已成功。持续调用 `get_research_batch`，最终得到 `completed_with_failures`；动量项为 `succeeded`，Python 项为 `failed`，该项 `diagnostic` 给出失败分类与信息。用成功项的 `research_run_id` 读取结果。 |
| 运行期间要求停止剩余工作 | 调用 `cancel_research_batch`，传入返回的 `batch_id` 和新的取消 `request_id`（例如 `stop-mixed-001`）。收到 `cancelling` 后按提示继续查询，直到 `cancelled`；已成功项仍保留成功结果。重复同一次取消使用相同 ID。 |

字段拼写、类型或互斥条件不满足 MCP JSON Schema 时，工具参数校验会在受理前拒绝；它与上表的业务校验拒绝一样不会创建部分研究。不要把“已受理”解释成“已运行成功”。

## 能节省哪些时间

独立策略 Batch 每个分片只准备一份共同输入，各账户消费同一窗口。同公式、同中性化的策略还可复用公式结果。Python 历史读取使用有界的批次内数据读取路径；缓存被预算淘汰、不同历史窗口或额外字段仍可能触发读取，不能保证全部历史只读取一次。

账户记账、手续费、成交、策略状态和 Python 程序本身仍分别执行。数值计算适合放在 `compute(data, state)` 中使用 NumPy 数组；需要真实账户状态的决策放在 `decide(data, account, state)`。Batch 不会自动把逐日 Python 循环变成向量计算，也不在不同 Batch 之间承诺共享缓存。

实际加速取决于重复数据读取和相同计算在总耗时中的占比，不能保证策略数翻倍就加速两倍。分片上限和内存预算由平台规划；同时保留的账户状态也计入预算，必要时减小分片或在受理阶段拒绝。固定 128 天本身不是内存永不超限的保证；运行期仍有进程内存保护。

实现边界和取舍见 [ADR 0259](adr/0259-group-independent-strategies-within-a-research-batch.md)。验证入口统一维护在 [AGENTS.md](../AGENTS.md#testing)。
