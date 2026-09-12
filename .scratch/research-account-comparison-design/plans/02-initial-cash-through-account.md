# 02 — 实际本金：实施计划

Status: complete

前置：01 已独立验收并提交 `a32208b`。在同一隔离 worktree 串行实施；不新增兼容路径、迁移或版本号，不触碰 dev/线上数据。

## 当前证据与边界

- Run service 固定 `FIXED_INITIAL_CASH_CNY = "10000000"`，既用于定义生成也用于校验。
- Strategy 内核固定 `INITIAL_CASH`：初始化、累计收益、CAGR 与成本分母都依赖它。只改输入不足以满足本票。
- Strategy Definition/Result/Tracking Origin 已携带 `initial_cash_cny`，复用该字段贯通，不创建另一份重复本金资源。
- 保持当前选股、等权及末日规则；末日修正在 03，Exposure 和配权在后续票。

## 实施顺序

1. 先以公开合同/计算接口增加失败回归：Strategy 显式十进制 CNY 字符串，有限、正、至多两位小数；Factor 不接收账户字段。验证 10 万、1000 万及不足一手现金场景。
2. 将本金贯穿规范化请求、Run/Batch 账户定义、准入与 provenance；不为缺失字段提供服务端旧金额默认值。网页可以预填显式金额，提交时仍明确记录。
3. 内核初始化及完整/增量指标使用该账户固定本金；续算从已有现金/数量继续，校验基线一致，避免 Refresh 重新注资。
4. 同步目录、HTTP/MCP、草稿/复用、表单及结果/Track 读取；Strategy Batch 每个子账户独立，Factor 合同保持。
5. 使用独立手算验证合法数量、佣金、余款、收益分母与现金非负；再验证 Run/Batch/Track 实际发布及源 Run 删除后的继承、网页和 MCP 合法/拒绝输入。
6. 按受影响边界选择既有验证入口；Standards 后 Spec 串行审查、修复复审、更新 tracker，独立提交后才开始 03。

## 验证记录

- 已补实际数量/费用/收益基线回归，固定本金实现先失败（initial-cash-red.log），内核参数化后四个手算场景通过。
- 本金合同与账户/续算定向 46 项通过（kernel-first.log）；追加续算不重新注资、拒绝更换本金后，本金文件 15 项通过（initial-cash-continuation.log）。
- 接入显式 Strategy/Batch 本金、规范化值、作者目录、草稿与网页字段。其余调用方和旧测试 fixture 尚待同步，真实依赖和浏览器验收尚未开始，不宣称本票完成。

- 全部 Kernel 首次在移除旧常量导入后 329 通过、3 失败；三处为 codec 测试 fixture 对新 `metric_state.initial_cash_cny` 使用整数零，修正为该账户实际基线后结果合同 26 项通过（result-contract.log）。不冒称整轮一次全绿。
- 草稿和 Run 网页测试修正显式本金 fixture 后 45 项通过（web-tests-second.log）。第一次真实 `typecheck` 暴露缺字段 fixture，已同步并复跑；先前裸 `tsc --noEmit` 不作为工程类型验证证据。
- 当前仍需：其他 API/MCP/Batch/Agent 测试 fixture 与合同同步、实际 10 万/1000 万 Run/Batch/Track 发布与继承验收、浏览器验收、两项串行 review 和独立提交。

- 真实隔离账户验收通过：10 万/1000 万/0.01 元分别初始化、手算合法数量/费用/现金、同本金复算一致、只变本金的 Batch 子账户独立、删除源 Run 后 Track 继续且不重新注资（real-initial-cash-first.log，31.38 秒）。依赖恢复阶段仍在运行。
- 补齐 01 遗漏的架构测试 Factor 导入/Track section 断言，与本票本金 schema 一并更新当前 MCP 合同摘要；48 项架构合同通过。只更新 benchmark 的确定性合同 hash/bytes，未改写历史性能数据或声称重跑性能基准。
- Agent Scripted Run/Batch 47 项通过（agent-tests.log）；浏览器完整工作台闭环和更广架构检查运行中。

- Spec 复审发现无限金额可能在账户计算时损失精度。明确当前可执行金额范围为 0.01–1,000,000,000 CNY（10 亿元），目录、准入、内核和网页一致拒绝超限；网页采用精确分单位比较。该边界是本票的执行约束，不增加兼容路径。
- 工作台完整浏览器闭环通过（results.json status 0，423.647 秒）；六项原始依赖恢复阶段通过。完整 Core 集成检查仍在运行。

## 审查与收敛

- Standards 原 P2：完整历史续算未拒绝本金基线变化。先复现失败，再在统一执行入口检查完整/紧凑两条路径；43 项定向回归通过，复审关闭。
- Spec 原 P2：任意长金额通过准入但账户失精度。统一明确金额范围，22 项金额回归通过、网页 52 项通过，金额范围增量 Standards 后 Spec 串行复审均无未关闭发现。冻结快照 `/private/tmp/thesistrace-issue02-cash-cap-review`。
- 最新网页工程 typecheck、Core source/tests/benchmarks Ruff、diff 格式检查通过。无兼容适配或迁移。
- 尚待完整 Core 集成运行结束，核对新增 MCP 实际规范化提交与 Track 来源字段；未结束前不完成 tracker 或提交。

- 最终金额边界修复后全部 Kernel 339 项通过（kernel-final.log，49.95 秒）；网页 52 项、工程 typecheck 与 Core Ruff 均通过。最初新增两条内核上界测试遗漏必填行情 fixture，补齐后 22 项通过；保留原失败日志，不将 fixture 错误描述为运行时缺陷。

- 完整 Core 普通集成 462 项通过、8 项按 marker 留给独立阶段或真实模型专用检查（941.97 秒）。新增真实 Run/Batch/Track + MCP 金额提交/来源验证用例通过（33.493 秒）。唯一 warning 为既有 read-cost 用例 `record_property` 与 xunit2 报告格式不兼容，不是业务失败。原始六项依赖恢复阶段继续运行。

## 最终验收

- Core 普通集成 462 项、六项原有 PostgreSQL/RustFS 恢复阶段全部通过；运行器退出 0，清理本次独立容器和数据卷。原始证据：`.local/test-runs/20260912t085238z-51661-86fa4bcb/`，汇总日志 `issue-02/integration-all-first.log`。
- 核心 339、网页 52、Agent 47 项及工作台 E2E 通过；MCP 合同、分页及轨迹定向验证通过。最终金额范围由公开准入和内核边界回归验证；完整普通集成开始于范围增量之前，不据此替代最新金额边界检查。
- Standards 与 Spec 的原 P2 均经修复复审关闭；没有未关闭发现。已核对范围内 diff、未跟踪的新计划和两份测试，没有其它用户工作混入。
- 本票独立提交。未运行真实付费模型、完整全产品 E2E、性能基准或镜像发布资格；本票没有镜像/启动变更。不宣称部署或 main 合并完成。
