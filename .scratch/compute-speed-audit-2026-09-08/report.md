**因子评估、策略回测与 DailyTrack 计算速度调查 — 2026-09-08**

可以优化。当前最有价值的方向是把 DailyTrack 的逐坐标计算接到现有列式内核、消除标签准备中的重复处理，以及复用 Alpha 公式中的相同子表达式。三者都有当前代码和本地对照实验支持。

本轮检查的是本地 `main`，HEAD 为 `adc1007bf40308246e46c4e4deb3c31648b1c149`。完成了候选算法实验与定向验证；业务源码尚未修改，候选实现只在本目录的独立 Python 进程中生效。工作区已有其他开发改动。

**当前算法与主要开销**

| 链路 | 当前计算方式 | 已确认的优化机会 |
|---|---|---|
| 因子评估 | 按最多 64 个 Research Sessions 分块，读取 lookback/未成熟标签所需上下文；计算 Alpha，再计算 1、5、20 日标签、每日 Pearson IC、Spearman Rank IC、五分组收益及累计统计 | 标签准备重复解析同一缺失价格坐标；三个 horizon 重建同日股票索引与 Alpha 数组；Alpha 数组和 Python 行对象之间多次转换 |
| 策略回测 | 复用 Alpha/Factor 前缀，按日期串行推进账户；定期选择 Top-N，执行下一 Open 的交易，处理交易限制、手续费、现金、持仓和净值 | 共用前缀的优化也会提速回测；评分排序有额外 Decimal 转换，但单独修改它的整块收益较小 |
| DailyTrack | 显式 Refresh 后读取目标交易日和有界上下文，从原有持仓与指标状态继续；保留最多 21 个 pending Alpha sessions 和 504 个交易日的滚动因子观察 | 数据读取已经列式化，Alpha 和 Label 计算仍逐个读取 Arrow 坐标；缺少临时 continuation 时重建最多 504 日、每块 32 日，该路径也使用逐坐标计算 |

Factor 的标签是 `Open[t + 1 + horizon] / Open[t + 1] - 1`。每个 horizon 按自身可用标签过滤样本，再计算平均并列排名、IC 和分位组。Strategy 使用固定账务精度与明确的订单顺序，不能把日期之间的账户状态当作独立任务。

实现依据：

- [ResearchRun 分块执行](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_run/execution.py:445) 与 [Alpha/Factor/Strategy 共用前缀](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/research_chunks.py:423)。
- [因子标签准备](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/factor.py:109)、[按 horizon 计算因子](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/factor.py:38)。
- [DailyTrack 的列式读取和恢复](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/daily_track/calculation.py:100)、[实际 Alpha 计算入口](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/kernel_advance.py:388)、[增量标签入口](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/kernel_advance.py:427)。
- [Alpha 执行计划](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/series_plan.py:48)、[列式表达式执行](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/series_plan.py:240)、[策略账户循环](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:286)。

**本轮实测**

以下是每个方案 3 次串行执行的中位数，按轮次交替先后顺序。所有数据在内存中，通过当前 Arrow 数据类型和真实计算函数执行；表构造、输出比较及 cProfile 均在计时之外。每次新建 ColumnarResearchData 视图，避免前一方案的 Python 坐标缓存污染后一方案。

| 实验 | 当前实现 | 候选实现 | 观察到的收益 |
|---|---:|---:|---|
| DailyTrack Alpha，3000 股 × 22 日 | 405 ms | 129 ms | 约 3.13 倍；耗时减少 68% |
| DailyTrack 当天因子计算，3000 股、1 个新增交易日 | 194 ms | 55 ms | 约 3.50 倍；耗时减少 71% |
| 有两次相同子表达式的 Alpha，300 股 × 85 日 | 102 ms | 55 ms | 约 1.86 倍 |
| 8 次相同子表达式相加的压力样例，300 股 × 85 日 | 505 ms | 66 ms | 约 7.67 倍，仅代表这种重复公式 |
| 三个 horizon 复用坐标与 Alpha 数组，3000 股 × 64 日 | 427 ms | 338 ms | 因子统计局部耗时减少 21% |

DailyTrack 的两项对照分别替换 Alpha 计算入口，以及直接从列式 Labels 生成 Factor daily metrics。后者比较每个 horizon 的每日结果，不声称生成了相同的临时行式 Label artifact，也没有把两个局部倍率视为整个 DailyTrack Advance 的倍率。

两次子表达式样例为：

```text
rank(close / ts_mean(close, 20)) - rank(lag(close / ts_mean(close, 20), 5))
```

候选执行计划复用完全相同的节点，保留原始加减乘除顺序和中间数值语义。当前 `build_series_execution_plan` 为每次出现的子树都建立节点，尚未合并相同子表达式。

进一步使用仓库现有长周期资格测试的数据生成器，构造 **5541 个历史股票身份、每天 Top3000、跨 64 日分区更换股票池** 的 85 日窗口，得到：

| 实验 | 当前墙钟中位数 | 候选墙钟中位数 | 当前 CPU 中位数 | 候选 CPU 中位数 |
|---|---:|---:|---:|---:|
| 标签准备 | 2.310 s | 1.759 s | 2.036 s | 1.645 s |
| 完整 Factor Evaluation 计算块 | 3.748 s | 3.177 s | 3.010 s | 2.719 s |
| 完整 Strategy Backtest 计算块 | 5.062 s | 3.419 s | 3.447 s | 2.920 s |

候选标签算法将每个缺失价格坐标的状态只解析一次，再按三个 horizon 的矩阵切片处理 entry、exit 和异常状态。当前版本的单次 profile 在这个 85 日窗口中记录到 **640,332 次 trading-state 坐标访问**，是比相关系数公式本身更显著的热点。

这组完整计算块的墙钟耗时分别减少约 15% 和 32%，CPU 耗时分别减少约 10% 和 15%。主机有其他负载，墙钟波动明显，因此更适合据此确认优化方向，不能据此承诺多年真实任务稳定提速 32%。

两个小优化的整体收益应谨慎解释：坐标复用的最新整块对照为 `1.133 s → 1.135 s`，没有稳定的整块收益；评分排序改用 float 的策略块为 `1.505 s → 1.444 s`，CPU 为 `1.408 s → 1.374 s`，收益较小。早期短测的整体结果随主机负载变化，最终不把它们列为确定的主要收益。

**建议实施顺序**

1. **统一 DailyTrack 的列式 Alpha/Factor 执行。** 复用现有 columnar 内核，覆盖普通 Advance 和临时 continuation 重建。主要收益已经在局部计算对照中验证。实施时同时处理当前 Label 临时产物、checkpoint 和 retained Factor daily 的契约，验证完整 Advance，而不是只替换一个调用。
2. **优化共用的 Label 准备。** 先一次性解析缺失价格和退市/停牌状态，再使用矩阵切片计算各 horizon。此项同时帮助因子评估、策略回测和共用该入口的批量研究。三个 horizon 的坐标复用可随后作为小改动评估；它需要额外内存，当前整块收益尚不充分。
3. **Alpha 子表达式复用。** 让同一计算片段只执行一次。这对复杂复合公式尤其有效；简单的 `rank(pct_change(close, 20))` 没有明显的重复子树，不能期待相同倍率。正式接入还需检查执行计划与 admission/private-artifact binding 的关系。
4. **补齐常用操作的矩阵实现，并评估 DailyTrack 的重复策略遍历。** 当前 `lag`、`delta`、多数 rolling 操作会进入逐股票的 Python builtin evaluator；DailyTrack 的 `_transition_strategy` 分别计算 finalized 和 resumable，存在重叠遍历。这两项已确认代码结构，尚未测量或实现候选。

当前 rolling sum/mean 已经是有补偿的滑动累计，rolling min/max 已使用单调队列，rolling std 使用精确整数和 Fraction 更新。因此不应把它们笼统描述成“每个窗口重新扫描”。进一步提速应针对 Python/对象开销，同时维持现有数值契约。

需要保留的计算边界包括：各 horizon 独立的有效样本集合、并列排名、缺失值和样本不足、T+1 Open 时序、退市 -100% 标签、确定的现金和订单顺序、固定 Tracking Origin、不可重写的既有跟踪结果。已有 `math.fsum`、精确账务 Decimal 和 Decimal → binary64 转换都有明确的正确性用途；直接替换成普通浮点累计或 Arrow 直接 cast 会改变这些边界。

**验证结果与测量边界**

- 所有报告中的同场景候选均进行了输出对照。Research Chunk 比较 continuation、最终摘要和策略每日观察；数组比较包括缺失位置，且同时比较序列化后的 SHA-256。
- 标签候选通过 30 组确定性边界输入，逐元素比较标签及全部 6 种可用/错误状态，包含零 entry、缺失 entry/exit、停牌、退市、无穷值及运算溢出。
- 在独立进程内同时应用标签、Factor 坐标与 Alpha 子表达式候选，复用当前 `test_factor.py`、`test_research_chunk_continuation.py`、`test_numeric_contract.py`：**25 passed，2 deselected，2.56 s**。两个排除项是需要稳定计时环境的性能门槛测试。
- 本轮未运行 `pnpm check:performance`。主机并非空闲状态，实验没有 PostgreSQL、RustFS、Parquet 文件读取、Worker 进程启动或发布写入，未测完整 DailyTrack Refresh/Advance，也未测财务字段和完整多年研究任务的端到端收益。
- 正式接入后按仓库要求在隔离环境验证 ResearchRun/Batch/Tracking 的相关集成边界，并在空闲主机运行完整性能资格检查。采用现行契约，不增加历史版本兼容、迁移或备用计算路径。

这是优化可行性调查，没有用户给定的失败阈值或已报告的数值错误，因此使用基线、差分对照和 profile 作为诊断反馈；没有把“耗时未超过随意设置的阈值”当作正确性证明。

**证据与复现**

使用仓库的 `uv` 环境，在仓库根目录分别运行以下脚本；脚本只使用本地确定性数据：

```sh
uv run --project apps/core python .scratch/compute-speed-audit-2026-09-08/benchmark.py
uv run --project apps/core python .scratch/compute-speed-audit-2026-09-08/candidates.py
uv run --project apps/core python .scratch/compute-speed-audit-2026-09-08/rotating_labels.py
uv run --project apps/core python .scratch/compute-speed-audit-2026-09-08/verify_candidates.py
```

本次实际调用增加了 `--offline --no-sync` 和临时 `UV_CACHE_DIR`，使用已经安装的依赖。

[初始链路与公式对照](/Users/koltenluca/code-github/thesistrace/.scratch/compute-speed-audit-2026-09-08/results.json) · [坐标与双子表达式对照](/Users/koltenluca/code-github/thesistrace/.scratch/compute-speed-audit-2026-09-08/candidate-results.json) · [股票池变化对照](/Users/koltenluca/code-github/thesistrace/.scratch/compute-speed-audit-2026-09-08/rotating-results.json) · [验证记录](/Users/koltenluca/code-github/thesistrace/.scratch/compute-speed-audit-2026-09-08/verification.json) · [源码版本与哈希](/Users/koltenluca/code-github/thesistrace/.scratch/compute-speed-audit-2026-09-08/metadata.json)
