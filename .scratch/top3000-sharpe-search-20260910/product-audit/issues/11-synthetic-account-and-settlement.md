# 合成收益账户的结算语义需要在结果与账本中明确

Status: needs-triage
Priority: P1
Type: product-research
Evidence class: current code, explicit ADR, real-data offline reproduction
Observed: 2026-09-10

## 已确认事实

当前设计明确采用整数 Execution Share Quantity 与分数 Adjusted Holding Units。卖出按移除的复权单位乘当日复权开盘价结算；成交费用则按原始股数乘原始开盘价计算。这是 [ADR 0070](/Users/koltenluca/code-github/thesistrace/docs/adr/0070-use-dual-units-for-synthetic-total-return-accounting.md) 与 [CONTEXT 中 Research Settlement](/Users/koltenluca/code-github/thesistrace/CONTEXT.md:334) 的明确选择，不应直接报告为计算错误。

本次10万元离线 downside20 行业处理、10只、10日调仓回放，2025-10-17按逐笔 raw_notional 加减重算现金为17787.3885344元，合成账户记录17905.8910005514867元，差118.5024661514867元。首次独立核验因此失败。读明契约后，用源Parquet价格独立重建复权单位、卖出结算、现金和费用，核验通过。保留模型边界，不能通过放宽误差容忍度掩盖差异。

证据：研究目录 `capital-replay/downside_ind_h10r10_100000.json`、`audit_capital_ledger.py`、`capital-replay-audit.csv`；实现 [卖出结算](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:1001)。所有离线实验只在独立研究进程设定本金，不改线上引擎。

## 为什么影响本任务

用户要用真实10万元账户执行。复权总收益模型可以用于研究，但不等于逐笔券商现金/股份账户；公司行动、股息到账时点、送转实际股数及个人股息税并未在本次回放中完整复现。按持有期限差别处理股息税是现实边界，见[国家税务总局政策说明](https://shanghai.chinatax.gov.cn/zcfw/zcjd/201509/t419000.html)。不据此估计本策略具体应交税额。

当前MCP strategy_summary及provenance没有足够醒目的合成账户标签；截图中结果页已观察到关键执行假设不在指标旁，见问题08。不能因为策略图净值一致，就把研究收益解释成券商账本完全可对账。

## 建议与验收

结果与MCP直接标识 accounting_model=synthetic_total_return，并把原始成交金额、费用、研究结算金额及复权调整分列；让差额能逐日对账。若产品承诺真实账户可执行回放，再独立支持时点化公司行动、税费和股份/现金事件；不能仅把复权模型改名成真实账户。

用户在结果页无需阅读ADR即可看见模型边界；导出账本按公开语义独立重算现金与净值；同时保留该设计下通过的数值证据。这是模型展示和实盘适配缺口，不是已证实的计算缺陷。
