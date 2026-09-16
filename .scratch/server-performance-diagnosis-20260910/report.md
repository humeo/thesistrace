# 服务器性能与内存诊断（2026-09-10）

结论：已确认两个可复现的性能缺陷、一个监测缺陷，以及 Data Operator 的任务结束内存回收不足。没有通过本次诊断发现研究结果计算错误，也没有据此证明所有计算正确。

## 范围与安全边界

- 当前本地 main：`ad16ea9bd8e369c20270d187499cb089b7b7069e`。
- 线上 `financial_candidate.py`、`financial_series.py`、`refresh.py`、`research_batch/execution.py` 的 SHA-256 与本地逐一相同。
- 服务器仅作只读检查，没有停止、重启或修改服务，没有提交新的研究或刷新任务。
- 用户明确授权后，将一张不可变收入表及必要清单（203 个文件，102,505,249 bytes）复制到本诊断目录。副本仅用于本地性能测量，未作为完整 Canonical Dataset 使用。
- 诊断脚本中的替代算法只存在于此目录，未修改生产源文件、部署或提交代码。
- Arrow 25.0.0，本地与线上默认内存池均为 mimalloc。本地测量不能直接代表线上吞吐。

## 1. Data Operator：大部分内存已经 free，但没有归还操作系统

进程 PID 2854376。在财务刷新成功并 published 后数小时空闲，容器约 2.16 GiB，匿名内存约 2.13 GiB，文件缓存约 2.3 MiB。

只读遍历 glibc 主堆块的大小/占用标记，未读取或输出业务内容，也未暂停进程。两次完整遍历结果一致；验证了块对齐、边界、空闲块前后大小和遍历前后的堆范围。

| 主堆指标 | bytes | 解释 |
|---|---:|---|
| 堆映射 | 1,813,291,008 | 约 1.69 GiB |
| 内部空闲块 | 1,752,305,664 | 程序已经释放 |
| 顶部空闲块 | 4,677,456 | 程序已经释放 |
| in-use 或 tcache | 56,307,888 | 约 53.7 MiB，保守归入占用 |
| 空闲合计 | 1,756,983,120 | 约 1.64 GiB |

`smaps` 同时显示该主堆几乎全部仍是 RSS。这证明约 1.64 GiB 是分配器保留空间，不是活对象泄漏。其余映射没有逐对象分析，不能将这个结论外推为整个进程绝无泄漏。

机制：Data Operator 在同一进程执行刷新并回到轮询等待，结束时没有运行 glibc 内存归还逻辑。Batch Worker 已有 `gc.collect()`、Arrow `release_unused()` 和 Linux `malloc_trim(0)`，但 Data Operator 未使用该结束边界处理。

代码：
- [常驻 Worker 循环](../../apps/core/src/thesistrace/entrypoints/data_operator.py#L398)
- [临时财务刷新服务调用](../../apps/core/src/thesistrace/data/refresh.py#L734)
- [Batch 已有内存回收](../../apps/core/src/thesistrace/research_batch/execution.py#L1384)

依据：[glibc malloc 源码的 chunk 大小及 in-use 位定义](https://codebrowser.dev/glibc/glibc/malloc/malloc.c.html#1353)。遍历代码：[read_allocator_metadata.py](read_allocator_metadata.py)。这不是对进程调用 malloc_trim 后能释放精确多少内存的实测，当前未在生产进程注入任何调用。

## 2. 已复现：财务列式读取退回 Python 逐行对象转换

读取链路：

`read_financial_table` → 多个 Parquet 对象 → `_overlay_financial_table` → `table.to_pylist()` → Python dict 去重 → `pa.Table.from_pylist()` → PIT 历史压缩与时间对齐。

[具体热点](../../apps/core/src/thesistrace/data/financial_candidate.py#L2570) 将整张投影表反复转成 Python 字符串/字典，再转回 Arrow。这是实测占主导的 CPU 和临时对象开销。

### 真实快照定向复现

- 财务 family：`cea82fc459da39fd7757f6e700dbf23d28d09ae6825b8ca9c48ecc62cc4a0d0f`。
- income 表：200 个对象，总计约 102 MB。
- 输入为字典序前 3,000 个 income instrument ID、64 个研究交易日、单个 revenue 字段；不是每日 top3000 流动性 Universe。
- 最新窗口 2026-06-11 至 2026-09-09：读取 223,328 行，去重后 223,059 行，输出 192,000 个坐标。
- 替代诊断算法保持列式处理，并保留 SHA-256 字符串拒绝行为、重复 key 的首次出现顺序及最后值覆盖语义。
- 三个窗口完整字段表完全一致；另验证重复值覆盖，以及 null、大写、非 hex、过短、过长 hash 均与原实现一致拒绝。

最新窗口交错执行原实现/诊断算法，各三次：

| 指标 | 原实现 | 列式诊断算法 |
|---|---:|---:|
| 完整字段读取总耗时中位数 | 3.239 s | 1.006 s |
| 去重阶段中位数 | 2.421 s | 0.116 s |
| 总耗时相对比例 | 1 | 0.311 |

这次定向读取约快 3.22 倍，耗时降低约 69%。它不是完整 ResearchRun、Batch 或服务器整体吞吐的加速比例。重复测试机器负载有波动，取三个样本中位数；Arrow CPU cache-size 探测在本地沙箱提示权限警告，但读取和等价断言均退出 0。

每个对象后的 `release_unused()` 在最终三次原实现总共仅约 5–6 ms/次读取，不是本次主导热点。先前将它列为嫌疑的假设已在本地样本排除，未单独测服务器该调用。

证据：
- [复现脚本](profile_financial_read.py)
- [三个窗口的初次结果](financial-read-profile.json)
- [保留拒绝校验后的重复结果](financial-read-repeat.json)
- [重复测量日志](financial-read-repeat.log)

运行：
```sh
UV_CACHE_DIR=/private/tmp/thesistrace-diagnosis-uv-cache uv run --project apps/core --no-sync --offline python .scratch/server-performance-diagnosis-20260910/profile_financial_read.py --repeat-latest
UV_CACHE_DIR=/private/tmp/thesistrace-diagnosis-uv-cache uv run --project apps/core --no-sync --offline python .scratch/server-performance-diagnosis-20260910/profile_financial_read.py --check-semantics
```

## 3. 重复历史扫描会放大上述开销

相邻且不重叠的两个 64 Session 窗口：

- 2018-01-02 至 2018-04-10：打开 91 个对象，约 42.6 MB。
- 2018-04-11 至 2018-07-12：打开 93 个对象，约 44.8 MB。
- 第二个窗口重复打开第一个窗口全部 91 个对象。

[读取实现](../../apps/core/src/thesistrace/data/financial_candidate.py#L1515) 先读取截止窗口末日的历史，再压缩窗口前版本；[每个研究切片重新创建 resolver](../../apps/core/src/thesistrace/data/generation_store.py#L1141)。这是可确认的重复成本，不应直接删除早期记录：PIT 计算需要窗口开始时已可见的报告状态。进一步优化必须保存正确的期初状态及窗口内新版本，并受 Data Generation 与内存预算约束。

## 4. 已验证：Strategy Sweep 加载了不需要的 Alpha 输入字段

[策略阶段](../../apps/core/src/thesistrace/research_batch/execution.py#L1124) 每个策略、每个窗口重新调用共享窗口读取，仍传入原 Alpha 的全部 field bindings 和 lookback，并再次构建 numeric field matrices。之后才读取已经计算好的私有 Alpha-and-Factor 结果。

真实策略内核只消费共享 Alpha 矩阵、交易价格与交易状态等执行数据。诊断复用了现有确定性 fixture，先计算 `rank(revenue)` 的共享结果，然后使所有 Alpha 数值字段不可读取。三种持仓/调仓组合的最终结果、逐日记录和 continuation 均完全相同。这个证据证明这些 Alpha 输入在策略消费阶段不需要重新加载，财务公式会放大重复读成本。

- [策略消费函数](../../apps/core/src/thesistrace/research_kernel/research_chunks.py#L505)
- [复现代码](probe_strategy_field_dependency.py)
- [三组等价结果](strategy-field-dependency.json)

这不是一次完整 Batch Worker/数据库恢复集成验收；实际修复仍须通过对应真实依赖恢复与结果等价验证。

## 5. 监测缺陷

[Factor Batch 的 chunk 消息](../../apps/core/src/thesistrace/research_batch/execution.py#L775) 把计算分项写成 `_empty_phase_seconds()`，虽然同一块实际执行了多个 Alpha 的计算。日志中的零不能解释为无计算开销。应区分没有采集与实际测得为零，并补齐阶段计时。

## 建议实施顺序

1. 将热点去重保持为列式操作，保留当前拒绝校验和覆盖顺序；已有真实快照验证了明确收益。
2. 为 Strategy Sweep 加载真正需要的执行数据，避免重新读取 Alpha 字段和不必要的预热范围。
3. 在 Data Operator 完整操作结束边界处理内存归还；验证重复刷新后的驻留内存不随次数增长，并覆盖成功、失败与恢复。
4. 再评估带边界的财务 PIT 读取复用和补齐分项计时。

当前没有源码修复或部署；这里保存的是定位证据和仅用于诊断的替代算法。未运行全套产品回归，也没有把定向等价检查表述为全产品正确性验证。
