# 因子评估、策略回测与 DailyTrack 提速

已实现共用标签准备、Alpha 重复子表达式复用，以及 DailyTrack 的列式增量与冷恢复。工作区为 `codex/compute-kernel-speed`，基线 `adc1007bf40308246e46c4e4deb3c31648b1c149`。改动留在独立 worktree，未合并或部署；本轮未操作 dev 数据。

**实测收益**

同一个进程中交替执行优化前后的真实计算函数，各 3 次，以下为中位数。研究和跟踪使用仓库资格测试的数据生成器：85 个交易日、5541 个历史股票身份、轮换 Top3000 股票池。构造输入与比较输出在计时之外；每次使用新的数据视图，避免坐标缓存污染对照。

| 计算范围 | CPU 优化前 → 后 | CPU 耗时减少 | 墙钟优化前 → 后 |
|---|---:|---:|---:|
| 因子评估，64 日计算块 | 1.893 → 1.651 s | 12.8% | 1.942 → 1.686 s |
| 策略回测，64 日计算块 | 2.051 → 1.814 s | 11.5% | 2.099 → 1.901 s |
| DailyTrack 完整增量计算与检查点投影，新增 1 日 | 0.961 → 0.756 s | 21.3% | 1.017 → 0.793 s |
| DailyTrack 冷恢复的 32 日计算块 | 2.924 → 1.261 s | 56.9% | 3.724 → 1.784 s |
| 重复子表达式，300 股 × 85 日 | 0.113 → 0.074 s | 34.6% | 0.114 → 0.081 s |

重复表达式样例为 `rank(close / ts_mean(close, 20)) - rank(lag(close / ts_mean(close, 20), 5))`。简单且没有重复子树的公式不会得到同样收益。

所有计时样本同时验证结果内容和 SHA-256 一致。研究块比较 continuation、最终统计及策略逐日观察；DailyTrack 比较完整检查点、continuation 和策略续算状态。另对 30 组确定性标签边界输入逐元素比较，标签和全部六种状态一致。

这组数据包含真实计算和检查点投影，不包含 Parquet 读取、Worker 调度、数据库与对象发布。本机存在其他负载（开始时 load average 7.49 / 10.66 / 11.53），墙钟有明显波动；上述局部计算收益不等同于完整多年任务或用户刷新耗时的同比下降。

**实现与正确性边界**

- [factor.py](/Users/koltenluca/code-github/thesistrace/.worktrees/compute-kernel-speed/apps/core/src/thesistrace/research_kernel/factor.py:109)：同一缺价坐标只分类一次，三个 Horizon 使用矩阵切片计算。分别保留买入不可用、停牌、数据缺失、退市卖出损失、零买入价和非有限结果的处理。相关系数继续使用原有 `math.fsum`，分组与并列排名不变。
- [series_plan.py](/Users/koltenluca/code-github/thesistrace/.worktrees/compute-kernel-speed/apps/core/src/thesistrace/research_kernel/series_plan.py:240)：仅在本次列式执行内合并相同节点，区分整数窗口、浮点常量与带符号零；保留原运算顺序和最后一次使用后的释放。持久化执行绑定及容量准入仍基于原计划，没有跨任务缓存或版本分支。
- [tracking_advance.py](/Users/koltenluca/code-github/thesistrace/.worktrees/compute-kernel-speed/apps/core/src/thesistrace/research_kernel/tracking_advance.py:39)：普通推进和冷恢复共用列式 Alpha/Factor 增量；保留冻结的 pending Alpha、最多 504 日的 Factor 和原策略账务。Label 只需要最多 21 日历史，即使 Alpha 使用 252 日 lookback，也不扩大标签窗口。DailyTrack 不生成无须保存的行式 Label 明细。
- [kernel_advance.py](/Users/koltenluca/code-github/thesistrace/.worktrees/compute-kernel-speed/apps/core/src/thesistrace/research_kernel/kernel_advance.py:170)：原行式算术入口保留为独立参考，工作状态投影集中到 `continuation_from_output`。DailyTrack 运行入口直接调用列式计算。
- [daily_track/calculation.py](/Users/koltenluca/code-github/thesistrace/.worktrees/compute-kernel-speed/apps/core/src/thesistrace/daily_track/calculation.py:105)：接入两个列式入口；保持当前检查点、Data Generation、Tracking Origin、发布及恢复契约。

审查额外确认并修复两个可复现问题：零买入价与缺失退出价同时出现时，行式也必须先拒绝零价；当天股票池为空时，列式 builtin 必须保留 `(0, T)` 形状。两项都保留了先失败、修复后通过的回归证据。有效输入的数值保持一致；零价组合统一为明确的数据错误。

没有改动 Decimal 账务精度、资金累加、交易费用、订单顺序、交易日时序或 Worker 并发。未将收益未经证实的评分 float 排序、坐标缓存、策略双遍历等一并改写。

**验证**

- 原始内核：262 passed。
- Core 快速检查：1190 passed。首次执行有 43 个失败，其中 42 个来自回环端口/系统运行时环境，1 个来自新财务 Fixture 未开启行业对齐；修正环境与 Fixture 后全过，未修改业务代码来绕过这些失败。
- 最终内核：311 passed，含 49 个新增参数化/场景用例。覆盖精确 Alpha、标签/Factor、分块续算、策略账务、检查点恢复、公式取反、持仓/调仓变化、行业、财务字段、空 Universe 和历史修订。
- 后续 Label 窗口收敛：20/252 日 lookback 跨 504 日滚动、财务更新差分，共 3 项定向复核通过。
- Ruff 和 `git diff --check` 通过。
- 隔离 Core 集成：426 passed；六个 PostgreSQL/RustFS 重启与恢复阶段各 1 passed，共 432 项。使用仓库运行器 `mise exec -- node tooling/test/cli.mjs integration`；退出码 0，本次资源已清理。普通阶段 8 个特殊标记用例被排除，其中六个恢复用例由后续专门阶段完成，真实模型用例未运行。
- 两条独立审查轴已闭环，最终 Standards / Spec 均无剩余发现；最后一次窗口变更另行复审通过。
- 长周期性能门禁：`mise exec -- pnpm check:performance` 已结束，运行标识 `20260908t054228z-63698-f403f7f4`，退出码 1。首个多年因子冷启动样本成功计算并发布，但耗时 **602.225 秒，超过 600 秒上限 2.225 秒**，性能资格未通过。运行器据此停止，后续 19 个冷/热样本、两项取消测试及汇总资格检查未执行。本次隔离容器、数据卷和网络均已清理。

该多年样本覆盖 2010-01-04 至 2026-08-13、轮换 Top3000，完成 69 个计算块；Worker 和计算子进程退出码均为 0，结果包含 `factor_summary`，完成后没有遗留 pin 或检查点。峰值 RSS 561.1 MiB，首个检查点 5.239 秒；未达到的约束是总耗时。本机同期有其他负载，但现有证据不足以把超时全部归因于负载，未修改门槛或重跑取代失败记录。

阶段记录为计算 435.485 秒、读取 133.214 秒、检查点提交 20.800 秒。Alpha/pending 的 122.536 秒和 Factor 的 33.180 秒属于计算阶段内部，不能再次累加。这说明完整任务仍有计算及读取成本；本轮局部提速已验证，完整多年任务的性能资格仍未完成，也没有优化前后完整多年任务的对照结论。

本轮没有前端改动，未运行浏览器/E2E、真实供应商或真实模型评估。

**复现与证据**

在本 worktree 根目录执行：

```sh
mise exec -- uv run --project apps/core python .scratch/compute-kernel-speed/measure.py
mise exec -- uv run --project apps/core pytest -c apps/core/pyproject.toml --rootdir . apps/core/tests/kernel -q
mise exec -- node tooling/test/cli.mjs integration
mise exec -- pnpm check:performance
```

本轮实际调用使用 `UV_CACHE_DIR=/private/tmp/thesistrace-speed-uv-cache`，已安装依赖的直接 Python 调用附加 `--offline --no-sync`。隔离集成/性能运行器仍使用仓库原入口和资源清理逻辑。

- [原始计时、指纹及源码哈希](/Users/koltenluca/code-github/thesistrace/.worktrees/compute-kernel-speed/.scratch/compute-kernel-speed/measurements.json)
- [测试计数和耗时](/Users/koltenluca/code-github/thesistrace/.worktrees/compute-kernel-speed/.scratch/compute-kernel-speed/test-evidence.json)
- [独立审查及修复](/Users/koltenluca/code-github/thesistrace/.worktrees/compute-kernel-speed/.scratch/compute-kernel-speed/review.md)
- [性能复现脚本](/Users/koltenluca/code-github/thesistrace/.worktrees/compute-kernel-speed/.scratch/compute-kernel-speed/measure.py)
- [隔离集成记录](/Users/koltenluca/code-github/thesistrace/.worktrees/compute-kernel-speed/.local/test-runs/20260908t051340z-46437-b7ea8e72/run.txt)
- [长周期性能记录](/Users/koltenluca/code-github/thesistrace/.worktrees/compute-kernel-speed/.local/test-runs/20260908t054228z-63698-f403f7f4/run.txt)
- [多年因子冷启动样本与失败原因](/Users/koltenluca/code-github/thesistrace/.worktrees/compute-kernel-speed/.scratch/compute-kernel-speed/performance-gate.json)
