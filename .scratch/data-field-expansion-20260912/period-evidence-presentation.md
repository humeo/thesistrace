# Q4 期间差异展示提案：已撤回

用户明确要求简化：两个 TTM 流量直接运算时，覆盖窗口不一致就返回缺失。此前建议的期间差异摘要、逐股票日明细和来源展开界面不进入本版设计，也未实施。

当前规则见 [正式规格的 TTM 缺失规则](spec.md#implementation-decisions) 与 [ADR-0246](../../docs/adr/0246-return-missing-for-misaligned-ttm-flow-arithmetic.md)。后端检查窗口，结果复用现有缺失传播和覆盖统计；代价是有效样本减少，并可能影响调仓选股。
