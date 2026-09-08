# Review

Working-tree review，基线 `adc1007bf40308246e46c4e4deb3c31648b1c149`。两条独立审查轴使用相同的固定快照，包含新增文件；排除本地实验脚本和原 checkout 的并行修改。

## Standards

首次：0 项硬违规，1 项可选 P3 维护性建议。新 Tracking 冷恢复与 `continuation_snapshot` 重复工作状态投影，存在窗口和 Schema 漂移风险。

修复：两者共用 `continuation_from_output`，算术参考路径保持独立。

v2 复审：原 P3 已关闭，无新增硬违规或维护性问题。列式 Tracking 使用已有 `transition_columnar_strategy` 和同一账务核心。

## Spec

首次：2 项 P2。

1. 空 Universe 进入通用 builtin 时产生一维空数组，导致 `(0, T)` 对齐检查失败。
2. 原行式标签在退出价缺失时跳过零入场价校验，和列式内核的拒绝行为不一致；当前 Data 校验允许该输入进入内核。

修复：空股票轴保留二维形状；行式与列式都优先拒绝零入场价。新回归在修复前分别失败，修复后通过，包含退市、停牌、数据不可用、无法解释缺价，以及空 Universe 后恢复成员。

v2 复审：两项 P2 均闭环，剩余发现 0。252 日 lookback、504 日滚动、冻结 Alpha 与策略账务未发现新问题。

最终：Standards 0 项剩余发现；Spec 0 项剩余发现。代码审查不替代集成和性能实测。

v3 限域复审：只将 Label 准备窗口缩到最早成熟信号日 `first − 21`；Alpha lookback、pending Alpha、504 日合并和序列化保持原样。Spec 再次确认三个 Horizon 的入场、退出和未成熟日期完整覆盖，无新问题。相关 20/252 日 lookback 和财务数据差分测试全部通过。
