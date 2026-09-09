# Contabo 6C12G Research 压测（2026-09-08）

## 结论

推荐当前混合请求负载使用 **3 个 research-worker + 2 个 batch-research-worker**。每个 Worker 保持现有 2 CPU 上限、2 GiB 容器内存上限、1.5 GiB 子进程执行预算和 2 个计算线程。五槽重叠执行期间平均 CPU 93.73%，达到充分利用这台服务器的目标，无需继续加到六槽来争抢 CPU。

这是所测配置中的资源利用选择，不是针对所有公式、其他业务高峰或多租户公平性的全局最优证明。容器 CPU 上限是可用上限，不是每个任务始终占两核。该设置已在服务器运行时生效；仓库的默认 replicas 仍为 1，后续常规部署需显式保留 scale 参数，否则可能恢复默认副本数。没有修改生产源码、生产 env 或部署分支。

## 覆盖与方法

- 服务器：Contabo vmi3564117，6 vCPU、约 11.68 GiB RAM、无 Swap。
- 字面完整可用市场区间：2010-01-04 至 2026-08-27，4,044 个 Research Session，`top3000`。Universe 是每日流动性选择；早期上市证券不足时不代表始终有 3,000 只股票。
- 等价基准：`rank(close)`，Strategy Backtest，H50、每 5 Session 调仓、无中性化。同样的输入分别经普通 Run 和单策略 Batch 执行。
- 滚动补充：20 日价格均值、20 日波动率与行业中性化，2010-02-01 起，之前 19 Session 用于预热；60 日成交量均值，2010-04-06 起，之前 59 Session 用于预热。
- 首次尝试从第一交易日运行 20 日均值被 admission 正确拒绝（预热不足），未创建 Run；完整区间基准因此使用无预热公式。不能把滚动任务说成从数据第一天开始已有有效信号。
- 每 10 秒采集主机 CPU/可用内存、Docker stats，以及通过本机 HTTPS 网关读取 MCP OAuth metadata 的响应时间。探针覆盖网关与元数据路由，不代表所有业务 API 或完整用户体验延迟。
- 每档只测一轮，未清理缓存、未重启依赖；结果不是严格冷缓存重复基准。

## 并发比较

| 同时执行的任务 | CPU 平均值（所有任务重叠期间） | 普通 Run 耗时 | 单策略 Batch 耗时 |
|---|---:|---:|---:|
| 1 普通 | 38.6% | 243.8 s | — |
| 2 普通 | 52.5% | 219.3–220.2 s | — |
| 2 普通 + 2 Batch | 82.1% | 232.6–233.2 s | 452.0–461.8 s |
| 3 普通 + 2 Batch | 93.7% | 249.5–256.0 s | 457.1–473.9 s |

耗时来自服务器 `execution_timing`，不包含提交与排队。MCP 客户端时钟和服务器约差 6 秒，计算耗时没有混用客户端时间。四/五槽是混合 Worker 路径，不能与两普通槽计算一个干净的线性加速倍数。单策略 Batch 仍执行共享 Alpha/Factor 再执行 Strategy 两个阶段；它不等同于普通 Run 的单通路开销。Batch 的价值在多策略共享计算，不在单策略延迟。

五槽阶段后半段接续了滚动任务，不是隔离的整波耗时。滚动阶段还出现本轮脚本之外的 Run（例如 14:34:37 UTC 开始的 `run_227e1ec085064e6c9c45`），因此只将其作为真实混合负载稳定性与完成性证据，不能归因出纯公式速度比较。

## 排队和多用户

普通与 Batch 是独立 Worker 池。某类槽全忙时，新任务仍可被接收，然后 queued；对应槽空闲后自动领取。本轮两个后续 Batch 实际经历 queued -> running -> terminal。普通槽空闲不能执行 Batch。

多用户共享这些执行槽；增加 Worker 能提升总吞吐，但当前是全局 FIFO 领取，不等于按用户公平排队。本轮使用已授权账号提交，没有做多个登录账号的公平性、配额隔离或持续到达率/SLA 测试。生产 MCP Batch 全区间 admission 约 15–16 秒的开销也独立于队列等待，应作为后续优化对象。

## 结果一致性与发现的缺陷

12 条相同输入的完整区间 Research（跨普通/Batch、1/2/4/5 并发）在删除结果最外层 `run_id` 后，`factor` 与 `strategy_summary` 的完整 JSON 各自完全一致。此检查证明这些结果在本次并发配置间确定性一致，不代替独立金融计算重算。

**发现且重复确认：纯预热 Chunk 的 continuation 校验缺陷。**

- `rank(volume / ts_mean(volume, 60))`，top3000，2010-04-06 至 2026-08-27，两次均在约 1.3 秒失败，已接收但首块没有提交进度。
- 失败 ID：`run_f65649cf3d8c411ebf1f`、`run_9d6f1f1fc3094f2aa636`。第一条子进程 peak RSS 235,286,528 bytes（224.4 MiB）；不是接近 1.5 GiB 预算或 2 GiB 容器上限的情形。
- 相同起点、截止 2010-04-30 的 60 日和 20 日公式均成功，分别约 5.0 秒和 3.6 秒。
- `execution.py` 的纯预热路径写入 `rolling_tail_sessions`，但 binding 尚为空；`research_chunks.py` 的 `_validated_alpha_factor_continuation_mapping` 拒绝 `binding_checksum is None` 且 rolling 非空的状态。`repro-warmup-validation.py` 在服务器现有 Worker 内验证：空 tail 通过，加入一个历史 Session 即报 `Alpha-and-Factor continuation is invalid`。
- 这是压测发现的已定位产品缺陷，**尚未修复/部署**。因此不能声称所有公式或全部预热窗口均已通过。增加 Worker 不会解决该缺陷。

证据：`rolling-worker2.log`、`worker2-later.log`、`repro.jsonl`、`repeat60.jsonl`、`repro-warmup-validation.txt`。没有修改正在进行其他工作的源码。

## 证据文件

- `summary.json`：本轮最终状态、队列等待、耗时、资源汇总。
- `resources.jsonl`：连续资源采样；`final-health.txt`：结束时容器、OOM/重启计数。
- `baseline-progress.jsonl`、`concurrency-{2,4,5}.jsonl`、`rolling.jsonl`：请求与状态证据。
- `equivalence-{early,c4,c5}.jsonl`：12 条结果的等价对比数据。
- `thesistrace-*-worker-*.log`：Worker 事件和子进程资源峰值。
- `worker-equivalence.txt`：旧/新普通 Worker 中 148 个 Python 源文件及依赖版本相同，避免将镜像标签差异误判为性能原因。

之前短区间批量压测的 210 条成功记录在相邻 `contabo-stress-2026-09-08` 目录，未混入本轮计数。

## 最终完成状态

本轮创建的 20 条 Research（Batch 按其 1 个子 Run 计数）已全部进入终态：**18 成功、2 失败**。失败为同一预热缺陷的原始用例与重复确认；没有遗留本轮 queued/running 任务。采样进程 PID 1176566 已主动停止，SSH 采样会话退出 255 是该有意终止的结果。

- 资源采样 236 次；CPU 最高 95.14%，全程最低可用内存 4.73 GiB。元数据探针 p95 62.4 ms，失败 0 次。
- 本轮任务日志记录的最大计算子进程 peak RSS 为 683,016,192 bytes（651.4 MiB）。这与 Docker working set、cgroup 总内存/文件缓存以及主机 MemAvailable 是不同指标。
- 五个 Worker 最终均在运行，RestartCount=0，oom/oom_kill=0；有健康检查的 API/Auth/Web/PostgreSQL/RustFS 均 healthy。Batch Worker 2 的累计 memory.events max=79，未记录此次起始值，不能判断发生在哪轮；因此不声称从未触及 cgroup 内存上限。
- 最后两个滚动 Batch 分别排队 150.873/134.322 秒，运行 516.112/515.409 秒，均成功；20 日均值普通 Run 与相同输入 Batch 的 factor/strategy_summary 也完全一致。行业中性化的两个不同公式任务均成功。
- 本轮未测试 6 槽、252 日最大窗口、金融字段、真实多账号公平性或高峰 Agent 并发；没有以这些未覆盖场景宣称通过。
