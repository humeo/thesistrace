# MCP净值导出与错误诊断不足

Status: needs-triage
Priority: P1
Type: product-research
Evidence class: 已复现的契约可用性问题
Observed: 2026-09-10

## 复现与现状

strategy_observations调用limit=100返回INVALID_INPUT、Tool input is invalid，既没指出limit字段也没给出最大50。工具描述和TS limit?:number未暴露边界；limit=50成功。完整2109日净值需要43次顺序游标调用。trace_6c19b28642944358bd41187645d5e1cd已保存。

## 对研究的影响

独立核算净值、分年/滚动分析需大量往返和自行持久化；错误不能让agent一步修正。当前MCP返回期末持仓，不提供完整逐笔历史交易/信号回放数据，不能据此精确重算10万元账户。

## 建议方向

在描述/schema/错误里公开分页上限和字段级原因；提供受限导出或按服务端标准口径汇总年度/滚动指标。需要小资金重放时提供有权限边界的成交/信号数据，而非暴露存储凭证。

## 验收建议

limit=51等边界给出字段/允许值；分页无遗漏重复且结果绑定不可变Run；导出能独立复算Sharpe/回撤，传输大小/权限均有约束。

## 证据

mcp-pagination-error.json；../observations/run_96384289b08844dca9dc.json；../nav-audit.csv

以上路径以研究目录/仓库为参照。UI证据见同目录上一层截图；产品代码只读核查，尚未实施修复。

## Comments

2026-09-10：在持续量化探索中记录；优先级针对用户当前的近期/状态切换/10万元20%回撤目标，不表示产品所有用户的统一优先级。
