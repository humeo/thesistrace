# 计算内核提速

Status: ready-for-agent

在 `adc1007bf40308246e46c4e4deb3c31648b1c149` 的独立 worktree 实现：

1. 共用 Forward Label 缺价分类，按 Horizon 向量化计算；保留六种状态和异常边界。
2. 列式 Alpha 执行时复用相同子表达式；不改变持久化表达式、Execution Binding、数值运算顺序或容量准入。
3. DailyTrack 的增量与冷恢复使用现有列式 Alpha/Factor 内核；按当前检查点契约保存状态，保留行式参考入口作为独立计算 oracle。

正确性：比较 Alpha、逐日 Factor、策略账务、最终 Result、分块 continuation、DailyTrack 检查点和恢复结果。覆盖动态 Universe、缺价、退市、停牌、财务字段、行业中性化、不同公式/持仓/调仓、历史修订和 504 日滚动边界。

验证：原始内核基线 262 passed（85.92s）；实施后定向测试、Core 快速检查、隔离 Core 集成和 `pnpm check:performance`。性能数据保留命令、输入、输出指纹、CPU/wall time 和运行负载；未完成或环境干扰不得宣称通过。

本轮不改变 Decimal 账务精度、Worker 并发、交易规则、数据发布流程，不合并或部署，也不触碰 dev 数据。原 checkout 的并行修改留在原位。
