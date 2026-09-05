# 临时 CNINFO 半年报公告查询诊断

## 结论（2026-09-04 实测）

当时失败的查询窗口现在可以完整查询，但历史异常未复现。
不能把本次查询成功当作“已证明上次一定可由即时重试恢复”。

| 运行 | 每个请求最多尝试 | 完整页数 | 公告数 | 不同公司代码 | 失败 / 实际重试 | 耗时 |
| --- | --- | --- | --- | --- | --- | --- |
| baseline | 1 | 23 / 23 | 690 | 346 | 0 / 0 | 12.358 秒 |
| with-retry | 3 | 23 / 23 | 690 | 346 | 0 / 0 | 9.194 秒 |

两次均为 25 个 HTTP 请求：股票元数据 1 次、总数查询 1 次、逐页查询 23 次。
全部 HTTP 200，每页 30 条，退出码均为 0。两轮排序后的完整结果校验和相同：

`ceb3067375c0b0055df06b79dd82c33bce4f935572e8d8996ef8e8c5a6f00968`

346 是该窗口半年报类别的全市场公司代码数，不是本次应更新或已更新公司数。
探针不读取 Dataset 股票范围，也不执行 Tushare 三表更新。

## 隔离和复现范围

- 使用运行中的 Data Operator Worker 的同一个已构建镜像：
  `sha256:decca8f9b0a5ac8675aece10ea928b44eed8c4bff5374f078933ec1d17c4a789`。
- AKShare `1.18.94`，Requests `2.34.2`；运行安装包原有
  `stock_zh_a_disclosure_report_cninfo`，只为请求包装诊断和可选重试。
- 原参数：`symbol=""`、`market="沪深京"`、`category="半年报"`、
  `start_date="20260808"`、`end_date="20260817"`。
- 连接/读取超时沿用 30 秒；HTTP 方法、地址、分页与查询参数不变。
- 使用独立 Compose project/network、只读容器、512 MiB 内存及 0.5 CPU 上限。
  只挂载此脚本，不挂载开发数据，不提供数据库配置或 Tushare 密钥。
- 不运行原完整 Refresh，不改数据库或 Dataset Head，不改生产代码，不重启 Worker。
- 这是人工授权的实时只读诊断，不是可依赖公网的 CI 回归测试。
  新容器不是原故障进程，也不复制其当时的网络连接或并发负载。

## 日志及成功判定

- `baseline.jsonl`：UTC 07:37:46.585 至 07:37:58.945。
- `with-retry.jsonl`：UTC 07:38:32.790 至 07:38:41.984。
- 每个请求记录页码、尝试次数、HTTP 状态、Content-Type、响应大小/摘要和耗时。
  异常记录类型及脱敏消息；不保存 Cookie、密钥、完整响应或环境变量。
- 只有所有预期页均成功、实际公告行数等于上游总数，才输出 `probe_succeeded`。
- 可选重试只处理 Timeout、ConnectionError 和 JSONDecodeError，同一请求最多
  3 次尝试，退避 1 / 2 秒，并尊重可识别且不超过 30 秒的 Retry-After。
  不在无失败时额外重发，也不重试确定性结构错误。
- 本次全部请求首次成功，重试恢复路径未在真实请求中被触发。
  9.194 秒与 12.358 秒的差异不能归因于重试策略。

## 如何运行

从仓库根目录执行，输出为 JSON Lines。命令仅查询公告，不提交更新：

```sh
docker compose -p thesistrace-cninfo-probe-20260904 \
  -f .scratch/cninfo-discovery-probe/compose.yaml run --rm -T probe --max-attempts 1

docker compose -p thesistrace-cninfo-probe-20260904 \
  -f .scratch/cninfo-discovery-probe/compose.yaml run --rm -T probe --max-attempts 3

docker compose -p thesistrace-cninfo-probe-20260904 \
  -f .scratch/cninfo-discovery-probe/compose.yaml down
```

静态检查已通过：
`uv --no-cache run --no-sync --offline ruff check .scratch/cninfo-discovery-probe/probe.py`。
格式检查也已通过。无缓存模式避免访问受沙箱限制的用户级 uv 缓存。
执行后已核验本次 Compose project 没有残留容器或网络；脚本和日志保留用于复查。

## 对原故障的解释边界

当前证据与“原查询遇到了一次非持续性失败”相符，但不能还原历史根因。
旧日志只保存了统一错误码，不能区分超时、断连或无法解析的响应。
缺少重试不是产生首次请求异常的原因；它意味着发生异常时没有就地恢复机会，
而是直接放弃该类别、记录完整性缺口，等待未来新的 Refresh 补查。
是否能恢复原来那次故障，尚无直接实测证据。本报告记录的是探针运行时的历史行为；
当前适配器已有请求级有界重试，其事实依据是
`src/thesistrace/adapters/cninfo_financial_announcements.py`，不能从本探针的两次成功推断恢复效果。
