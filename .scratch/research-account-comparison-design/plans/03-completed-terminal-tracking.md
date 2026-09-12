# 03 — 末日正常交易与严格追加：实施计划

Status: complete

前置：01 `a32208b`、02 `ffc1eac` 均已独立提交。继续同一隔离 worktree，严格串行，不新增兼容、迁移或版本路径。

## 已确认的当前行为

- `strategy._execute_strategy` 用 `terminal_cutoff` 阻止末日交易，并将末日标为 `terminal_valuation`。
- `transition_strategy` 计算两次：完整区间用于展示，截掉最后 Session 的另一份状态用于续算。这使旧终点会在下一次 Advance 重算。
- Run Result、Chunk Result 和 Track Checkpoint 分别构造 `pending_signal`，目前只包含日期与 next-open 时点，不含已确定的入选名单与权重。
- Track 的 warm/cold 入口依赖临时 `pending_alpha`；权威终端状态必须携带已作出的目标，才能在缓存丢失或历史数据修订后不重算过去决定。

## 实施顺序

1. 从公开策略/Advance 入口增加失败回归：末日确有换股和费用，最初 Open 全现金，末日 Close 决定保留；覆盖多个切点的整段与分段账户等价。
2. 统一每个 Session 的 Open 执行和 Close 决策。删除末日截断与前一日 resume 双重语义，以完整已执行终态作为唯一续算状态；不在结束时强平。
3. 定义终态权威待执行目标，保留决定日期、入选股票、当前相对权重、决定所用数据/合同身份。Run、Chunk/Batch、Track 都由同一计算产物投影，杜绝各自重算名单。
4. Advance 只处理更晚 Session；首个新增 Open 执行冻结目标。后续 Close 可使用新 Data Generation，缓存恢复只补未来计算依赖。保持选股相位、实际本金、峰值和累计指标。
5. 贯通终态 schema、持久 Checkpoint/Origin、HTTP/MCP 与完成日期/交易时点展示；源 Run 删除后 Track 仍能执行冻结目标。替换旧末日覆盖断言，不删掉独立回撤/累计统计覆盖。
6. 复用隔离真实依赖测试验证 Refresh 并发、幂等、失败保留旧完整状态、Retry/Checkpoint 原子发布；按受影响页面执行浏览器验证。按实际失败边界扩大检查，不机械重复无关门禁。
7. Standards → Spec 串行审查，修复复审关闭后更新 tracker 并独立提交。完成前不开始 04。

## 验证记录

- 当前仅完成源码定位和实施计划，尚未修改运行行为或宣称本票验收通过。

- 新公开接口回归 `test_completed_terminal.py` 已运行：末日交易与 1/2/3 三个切点共 4 项按预期失败（`.local/test-runs/issue-03/completed-terminal-red.log`）。失败分别证明末日仍为 terminal_valuation，以及 Advance 会改写已发布切点。尚未修改执行实现。

- 删除 `terminal_cutoff` 和未使用的跳过执行参数，普通/Chunk 执行都交易至最后 Open；transition 直接保留完整账户，不再额外重跑截去末日的区间。末日/多切点加本金回归 26 项通过。
- 增加旧 Alpha 不可用的续算回归，先复现 KeyError；每个选股 Close 冻结名单、等权相对权重、信号输入 checksum 与策略合同 checksum，下一 Open 读取已冻结目标。27 项定向回归通过。
- Run Result、Chunk/Batch 和 Track 的 PendingSignal schema/投影已接入内核产物，并修正原 resume 少一天引起的 report_count +1。尚须收敛权威 Checkpoint 单一终态、严格追加 observation 状态、缓存恢复和所有当前调用方/测试。
- 现有 Advance 合同检查正在运行（session 20297，`issue-03/advance-first.log`），已有失败待分析，尚未进行两轮审查、tracker 完成或提交。

- 旧 Advance 契约两处失败已定位：手工 compact fixture 未带冻结目标，以及断言仍要求终态与续算持仓不同。当前合同改为唯一完整终态，并移除 Checkpoint 的 continuation_positions/observation/metric_state 重复副本。
- Track 观测累积现在只接受严格晚于已完成边界的日期；永久峰值/回撤覆盖替换为不可改写边界和长期独立计算对照。Advance 与观测状态共 20 项通过（advance-third.log，15.46 秒）。
- 取数所需股票集合已包含冻结目标中的新入选股票，避免仅加载当前持仓而漏掉下一 Open 待买股票。全部 Kernel 检查运行中（session 51857，kernel-first.log），用于定位旧末日假设和其他未同步调用方。

- 全 Kernel 首轮 323 通过、21 失败（kernel-first.log，39.69 秒）。已分类为旧末日/可替换边界断言、Chunk 严格字段集遗漏 pending_signal，以及新增决策序列化触及旧的固定调用次数性能断言。未将整体视为通过。
- 修正 Chunk 当前字段集；Run 和 Batch 的续算取数同 Track 一样加入已冻结待买股票。决策 checksum 仅序列化已入选记录，不重复序列化整个共享 Alpha 横截面。
- 定向 contracts-followup.log 正在运行（session 23117）：Chunk、Batch、列式 Track 和观测投影；后续仍需严格校验 pending 目标、检查暖/冷缓存恢复、同步旧末日手算断言与公开 schema、真实依赖/网页验收及串行双审查。本票未完成、不提交、不开始 04。

- 更新明确的末日手算/拒绝订单重试断言，保留共享 Alpha 禁止重复计算和账户序列化性能约束，同时检查每个新目标最多序列化入选股票。相关 57 项通过（terminal-contracts.log）。
- 全 Kernel 第二轮 344 项通过（kernel-second.log，46.24 秒）；网页 36 项通过；MCP schema 确定性指纹更新后与新增损坏权重拒绝用例共 51 项通过（target-and-mcp.log）。仅更新 schema hash/bytes，未改写历史性能基准。
- 真实隔离验收已启动：项目 thesistrace-test-20260912t092926z-64305-00013450，session 14891，integration-first.log。选择实际本金账户、历史修订仅影响未来、权威 Checkpoint 恢复和并发 Owner/Refresh，用既有运行器随后执行原始依赖重启阶段。未宣称通过。

- 工作台原有完整 Run → Track E2E 已启动（session 46531，e2e-first.log），隔离环境、确定性数据。真实集成 session 14891 经句柄轮询仍在运行；不得因观察超时重启。

- 真实集成首轮 3 通过、1 失败（130.09 秒），失败是旧用例把第三个新增 Open 当作纯估值，因此仍期待持有 B。手算新行为是 Aug 6 执行冻结 A，Aug 7 按修订后的 Aug 6 均线买 B，第三个 Open 再换回 A。把验证切点设在 Aug 7，并断言旧观测不变、第一天零换股费用、第二天才发生交易；使用全新工作缓存证明不靠旧 Alpha。复用原隔离环境后用例通过（30.93 秒），原失败 XML 保留。
- 复跑 session 23056 正执行原始依赖恢复阶段；日志 integration-forward-only.log。E2E session 46531 已结束，results.json status 0，完整工作台 Run→Track 闭环 254.194 秒通过，独立环境已清理。网页 typecheck 与 Ruff 通过。
- 已定位需继续处理的单 Session 回测边界：旧指标累积通过 terminal_valuation 伪造 entry_session，当前执行已不产生该类型。不得靠保留旧分支或限制合法研究区间掩盖；需让无入场现金账户正确发布/比较并可继续 Track。清理前先补公开回归。
- 1000 次 Advance 读成本 fixture 改为每次仅附加新日期，保留既有峰值/回撤及读取成本验证；该真实用例尚未复跑。双审查/独立提交仍未开始。

- 六项原始依赖恢复全部通过，保留项目已由运行器清理。新增单 Session 回归先复现比较服务对 None 入场日的 TypeError（no-entry-red.log）。当前合同明确允许尚未入场：entry_session 为 null、比较状态 no_entry_open，账户/冻结目标照常发布；Track 比较从当前权威 metric_state 读取后来出现的真实入场日。移除 terminal_valuation 旧分支，不限制原合法日期范围。
- 比较/终态/结果定向 45 项通过（no-entry-first.log）。新增真实单 Session→Track 首次入场验收，与本金和 1000 次追加读成本一起运行（session 50287，no-entry-integration.log）。这轮复用隔离基础设施入口，只跳过已通过且本次无恢复规则改动的六项重启阶段，不宣称重跑。

- 跨接口 405 项通过（no-entry-contracts.log），网页类型检查通过。单 Session 真实发布与后续首次入场、本金案例均通过；1000 次追加读成本首轮旧分页切点失败，修正预期后通过（read-cost-corrected.log，31.70 秒），隔离环境已清理。恢复直接投影完整终态而非精简观测行；新增恢复后无需推进的终态往返断言，13 项 Advance 检查通过（restore-roundtrip.log，21.52 秒）。

- Standards 首轮提出 P2：合法非等权冻结目标会被当前执行静默按等权使用。先补回归复现未拒绝（weights-red.log），当前等权合同显式拒绝非等权目标；末日/Chunk 24 项通过（weights-green.log），Standards 复审关闭。新增无入场账户页面断言，24 项通过（cash-account-web.log）。结果 codec 26 项通过；发布字节与 Track Session 坐标真实依赖 26 项通过（publication-integration.log，26.97 秒），独立环境已清理。Ruff、diff check 通过。Spec 独立审查进行中。

- Spec 审查无阻塞发现；其所提示等待的发布/坐标集成已实际结束，26 项通过。最终网页类型检查、Ruff 和 diff check 通过。两轴审查全部关闭，验收与 tracker 同实现独立提交；04 尚未开始。
