# 04 — 条件 Signal：实施计划

Status: complete

前置交付：01 a32208b、02 ffc1eac、03 703c303。保持同一隔离 worktree，严格串行；本票只扩展可执行 Signal，不提前开放 Exposure 或共同指标，不新增兼容/迁移/版本解释器。

## 现状与边界

- AlphaLanguage 使用受限 Python AST 编译作者输入，维护目录、定位诊断、窗口与工作量。当前仅接受 Numeric Series 根，语法限数值。
- research_kernel/alpha_expression.py 另校验冻结 IR，现有校验缺少完整类型信息。需让作者与持久 IR 共用当前类型/节点规则，不能新增可绕过准入的条件执行入口。
- series_plan.py 为共享 Series 求值核心，包含逐股和列式/截面执行路径；所有路径需保持相同缺失和分支语义。
- Web Alpha 编辑器的 Lezer grammar 当前只有数值、调用、一元与二元运算；目录和 MCP/HTTP 诊断沿用现有公共路径。

## 实施顺序

1. 在公开编译/Series 接口补独立小样本失败回归：六种比较、and/or/not、嵌套 if_else、常量广播、类型拒绝、未知传播和未选缺失分支；记录原失败。
2. 扩充单一当前数值/布尔及常量/股票序列类型规则。受限 AST 编译和冻结 IR 验证共享规则与资源核算；根仍必须为股票数值序列。两分支完整静态校验、字段绑定、嵌套窗口与工作量，不实现任意代码、循环或状态算子。
3. 扩展现有 Series plan 和各执行路径，布尔未知严格传播，if_else 逐位置选择；保留既有数值/浮点语义、去重与列式计算行为。
4. 接通目录、编辑器语法/高亮/补全、草稿及 diagnose_alpha_formula。HTTP/MCP 接受和拒绝必须同源；核对提交和冻结 provenance，不新增独立网页求值器。
5. 验证 Factor、Strategy、Batch、Track 使用同一结果；覆盖窗口/未来价格扰动、Chunk 与冷缓存一致性、原数值回归和现有性能约束。执行受影响真实依赖与编辑器交互验收；按实际失败边界扩展测试。
6. Standards → Spec 串行审查，修复复审后更新 tracker 并独立提交。全部关闭前不进入 05。

## 验证记录

- 已完成入口定位和实施计划，尚未修改表达式运行行为或宣称本票验收通过。

- 新增公开编译/Series 条件回归，首轮 10 失败、7 拒绝用例通过（issue-04/conditional-red.log，0.26 秒），证实当前缺条件语法。开始共享 expression_types，区分数值/布尔及常量/股票序列，复用到作者一元/算术类型校验；现有语言合同 56 项通过（type-foundation.log，0.29 秒）。修正两处导入排序。尚待比较/布尔/if_else 完整编译、冻结 IR 同源校验、共享求值器、编辑器/目录及跨接口验收；本票未完成、不提交、不开始 05。

- 比较、布尔与 if_else 接入作者编译及 Series 三条求值路径，17 项小样本通过（conditional-first.log）。冻结 IR 校验接入共享类型规则，首轮相关 62 通过、1 失败（ir-series-first.log）；失败为原 IR 测试允许常量根，与当前 Signal 根必须股票数值序列冲突，改为显式拒绝断言。Ruff 通过。仍需补冻结 IR 资源边界与独立新类型/列式覆盖、同步旧目录契约及编辑器/MCP/实际 Run 链路，本票未完成。

- 增加条件下截面 rank 与列式独立小样本、冻结 IR 工作量一致性和深度拒绝回归。首次发现新测试误用 rank 0.5 起点、漏传 cancellation_check，以及既有源码/IR 计算工作量相差 1；保留 columnar-ir-red/second 日志，修正手算及调用并统一工作量。超深 IR 先复现未拒绝（ir-budget-red.log），当前以共享上限约束节点/深度/工作量。
- 条件与既有语言/IR/Series 合同 122 项通过（conditional-contracts-second.log，0.74 秒）；原目录列表与非法比较根断言同步当前能力，保留非有限值检查。编辑器 Lezer 加比较与 and/or/not，移除后端从未接受的一元加号，生成 parser 成功。网页 typecheck 启动（web-types-first.log）。尚未验收编辑器交互、HTTP/MCP、真实 Run/Batch/Track、全 Kernel；两轴审查/提交未开始。

- 全 Kernel 369 项通过（kernel-first.log，49.47 秒）。HTTP/MCP 新增条件成功/类型拒绝/未选分支窗口拒绝，首轮仅两项旧 schema 指纹失败；同步实际当前 schema hash/bytes，未修改历史计时，第二轮通过（http-mcp-second.log）。
- 编辑器增加 Boolean 关键字补全，if_else 目录描述公布六种比较与布尔规则。新增真实 AlphaFormulaEditor 浏览器用例，检查输入保留、比较/布尔解析和高亮。首轮 Chromium 在沙箱 bootstrap_check_in Permission denied，未进入页面；获准本机重跑同一用例，1 项通过（editor-browser-second.log，8.3 秒）。这仅证明编辑器组件，不宣称完整提交/Track闭环；后续仍需条件表达式的 Chunk/冷缓存/实际 Run、Batch、Track 及双审查。

- 条件公式加入已有 Chunk 等价性及 Track 每个恢复边界检查，23 项通过（conditional-continuation.log，19.16 秒）；独立未来价格扰动及未选分支工作量超限检查共 22 项通过（future-work.log）。单日条件策略通过真实 Run→Worker→Track 首次入场，与原公式对照共 2 项通过（conditional-integration.log），环境清理完毕。
- 条件与原公式分别加入 Factor/Strategy Batch 对普通 Run 的既有真实等价性用例；启动独立 Batch 集成（conditional-batch-integration.log）。最终类型检查已通过；尚待 Batch 结果、审查、tracker 完成和提交。

- Batch 真实对照 4 项通过（conditional-batch-integration.log，24.36 秒），独立环境已清理。安全与 Series Plan 8 项通过（security-plan.log，2.63 秒）；Ruff 与 diff check 通过。Standards 静态审查无修改发现；Spec 独立审查已启动，尚未关闭票据或提交。

- Spec 审查无阻塞发现，Standards/Spec 均已关闭。更新全部验收及 tracker，与实现独立提交；05 尚未开始。
