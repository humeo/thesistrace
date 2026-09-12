# 13 — 当前数据重新回测：实施计划

## 基线与边界

- 开始前已确认 isolated worktree `codex/research-capabilities` 干净，HEAD `4c2ad039`；12已完成实现、验证、串行审查和独立提交。
- 依据[13票](../issues/13-rerun-holding-diagnostics.md)及[母规格](../spec.md)第10节。只实现显式创建普通新 Strategy Run；不实现精确重放、旧引擎/字段兼容、原 Attempt Retry、自动续算或往旧产物填回持仓。14联合验收尚未开始。
- 复用当前 ResearchRun admission、请求收据、Data Head准入、预算、队列、取消及12持仓发布。Agent仍调用 `submit_research_run`，网页调用同一资源提交入口；不新增独立诊断计算服务。

## 已核实的入口

- `research_run/models.py`：ResearchRunAdmissionCommand当前按research_kind分支，StrategyBacktestSpec拥有实际本金、持股数、Selection Interval、Exposure、Weighting及窗口；提交身份/文件夹独立。
- `research_run/service.py`：`admit_with_outcome`/`_admit_with_outcome`先查request_id收据，再prepare_child_admission读取当前准入Dataset，最后事务复查收据并发布普通queued Run。来源解析必须接入这条路径，不另写队列/预算。
- `daily_track/models.py::TrackingOrigin`复制了immutable_input、seed_run_id、原数据身份、已验证原Result及计算规则；即使源Run删除仍可作为参数来源。
- 12的DailyHoldings面板持有具体unit_id、日期范围与expired状态；仅显式按钮触发新提交，结果读取/页面展开不提交。

## 实施顺序

1. 定义当前合同的来源型提交和冻结来源元数据。保留普通手写Spec提交；来源型提交必须可由服务端按拥有者解析完整原配置，避免要求Agent猜测或把不一致配置标成原策略重跑。优先用互斥、严格有类型的来源命令接入既有submit能力，而不是让所有策略字段变成optional。具体union形状以当前HTTP/MCP生成器可表达的最简合同确定。
2. 先按原请求身份查收据，再解析来源；并发重复提交保持同一结果，即使随后源Run删除也能重放收据。新request_id与来源记录纳入请求指纹；同身份不同来源/调查日期按现有冲突规则拒绝。
3. Run来源读取自己的冻结配置及数据/规则身份。Track来源从自己复制的Origin恢复原研究起点，固定调查日期和对应已发布Checkpoint来源，不从中间日期全现金启动，也不依赖仍存在的seed Run。禁止跨拥有者引用、未来/范围外调查日期。
4. 将来源配置投影成当前StrategyBacktestSpec，完整保留策略、实际本金、模拟参数与所需日期。走当前编译/依赖/数据完整性诊断；非法原配置给可定位issues，不隐式替换。只使用当前Data Generation，新Run内正常冻结；旧文件/引擎不可用不得成为前置读取依赖。
5. 在新Run/结果/状态返回中保留来源关系及新旧实际数据、规则身份。来源不作为旧数据额外pin；不覆写原Result、Track、cursor或持仓。
6. 网页过期面板显式“重新回测生成持仓”，重用提交幂等身份处理断线重试，成功跳转新Run；新Run显示当前数据重新回测标记、原Run/Track入口与允许差异说明。无额外数据版本确认步骤。MCP目录/类型/当前合同校验同步。

## 验证及完成标准

- 公开接口先写能稳定复现的失败回归：来源参数保留、Track完整起点、非法配置定位、所有权及request_id冲突/幂等。
- 真实PostgreSQL/RustFS与普通Worker：完成原Run→过期→修订历史价格发布新Head→显式创建新Run，验证不同收益允许成功、当前Head冻结、来源可追溯、原结果/游标不改、新持仓独立TTL。再验证旧数据不可用及Track源Run删除仍可创建；普通取消与排队行为复用实际路径。
- 原生MCP闭环沿用既有submit能力，读expired不产生Run；网页闭环显式提交和新Run导航，错误/重复点击/断线重试不多建Run。
- 定向单元/合同、真实依赖、网页测试与必要快速检查。按AGENTS选择验证，不将小样本测试冒充生产/精确重放保证；14负责联合交付验收，12已记录的历史迁移夹具基线漂移仍需14核对。
- 实现/验证后冻结快照，Standards审查→修复复审→Spec审查→修复复审，更新13tracker并独立commit，之后才开始14。

## 执行记录

- 2026-09-13：13开始，已读取票/母规格及准入、TrackingOrigin入口。此时只写计划，尚未修改产品代码或13测试；12提交已完成，工作树此前干净。
- 实现起步：新增严格的来源型提交模型 `CurrentDataRerunCommand`，与原按kind分支的 `ResearchRunAdmissionCommand` 组成 `ResearchRunSubmissionCommand`。原Batch/手写Spec模型保持本身职责，来源命令不接受formula、本金或kind覆盖；服务端将从已授权来源解析完整配置。Track来源显式携带checkpoint manifest和调查Session，避免并发Refresh改变提交身份。初始合同测试2例因缺失模型失败；实现后及补充原Factor/Strategy直接提交测试共3passed0.24s，Ruff通过。
- 当前仅定义模型/测试，尚未将来源命令暴露到HTTP/MCP或接入服务，不能声称已可重跑。后续在admit_with_outcome普通收据预查后解析来源，避免源删除影响已有幂等收据重放；不旁路prepare_child_admission/预算/队列。
- 代码核对：Track当前provenance返回冻结研究参数与tracking_strategy_session，但未返回当前checkpoint manifest。13需在对应公开来源读取中提供可引用的已发布checkpoint身份，网页与Agent可取得该身份后提交；不能要求调用方猜测内部ID。解析Track来源由DailyTrack模块拥有，不在ResearchRun直接查询其私有SQL。
- 原策略ImmutableRunInput还含costs/risk_free_rate及execution模拟参数。来源投影必须保留可执行的模拟参数，并采用当前规则/编译/数据准入；不能仅复制公开选股字段后静默套成本默认值。来源元数据与新/旧数据规则身份应由普通新Run持久化，避免为来源强制加载旧Data Generation或旧结果引擎。

- 来源提交已接入 HTTP/MCP 普通准入路径；收据预查在来源读取之前，Run 来源按拥有者解析，Track 由其模块提供已发布 Checkpoint/Origin。原模拟参数不符合当前固定合同则返回具体字段诊断，不默换参数。来源元数据随新 Run 冻结并公开。
- Run 真实依赖验收第三次执行通过（1 passed, 499 deselected，7.91 秒）：修订历史行情、移走旧 Generation 清单仍成功重跑，参数保留、新数据冻结、新旧收益可不同、原结果/过期持仓不变、新持仓可用；删除原 Run 后相同 request_id 仍返回已创建 Run。首次遗漏模块导出导致初始化失败；第二次修订夹具未遵守 adjusted_price_string 派生格式，修正后通过。证据 rerun-third.log。
- 正在扩充 Track 源 Run 删除后的完整起点回测、固定 Checkpoint、调查日期拒绝及普通取消验收。首次启动遗漏隔离 uv cache 环境变量，尚未执行测试；已改用授权隔离运行入口与专用缓存重启。前端/MCP闭环、审查与提交仍待完成。
- Track 真实验收识别并修复了激活 Checkpoint 缺少 data_generation_id：当前合同直接补齐来源字段，不加入旧格式回退。后续测试比较中的 seed_research_available 差异来自测试主动删除 seed，已改为删除后取基线。rerun-track-fourth.log：1 passed, 499 deselected，15.44 秒，覆盖 Track 完整研究起点/调查日期/固定来源/原状态不变/普通取消。
- 过期持仓视图已接入显式新 Run 提交，Run 页面显示来源入口与当前数据结果可不同说明；Track detail 提供当前已发布 Checkpoint 身份，按钮以选中持仓期间末日为调查日期。请求失败后重试保留 request_id，不因查询/展开提交任务。Web typecheck 通过；browser-first.log 三项真实浏览器测试通过（3.5 秒），包含断线后同请求重试及新 Run 导航。
- MCP 目录改为说明来源型提交与额外读取权限。合同断言随当前 union 更新；canonical 合同 223611 bytes / SHA256 4d25b5f2a9887b26a666085ef36464a4bdb99d83d89074bf52e2dd9b4a4d0b18。权限回归识别动态 source scope 缺失被映射 INTERNAL，已用预期 FORBIDDEN 结果修复；尚待本轮复验结果及原生 MCP 子进程验收。未完成 Standards/Spec 审查、tracker 验收或提交。
- contracts-fifth.log：来源命令与 MCP 当前合同、动态来源权限共 51 passed（3.90 秒）。原生 MCP 子进程验收 rerun-native-mcp.log：1 passed, 499 deselected（24.31 秒）；Track 源 Run 删除后从保留 Origin 提交、幂等重放、Worker 执行与取消完整通过。
- 全量快速检查 quick-first.log 正在执行，Python 阶段已有失败，尚未出完整诊断；不认定通过。已识别 provenance 大小验证夹具缺少新必需 checkpoint 身份并补齐，定向 pagination.log 7 passed（2.57 秒）。新增真实依赖边界：其他拥有者不可引用 Run/Track、错误 Checkpoint 拒绝、原模拟成本非法时具体字段诊断；rerun-source-boundaries.log 正在运行。所有修改仍属于13未提交工作，14尚未开始。

## 最终验收与串行审查

- `rerun-source-boundaries.log`：真实 PostgreSQL/RustFS、原生 MCP 子进程与普通 Worker 完整闭环 1 passed, 499 deselected（26.88 秒）。覆盖修订历史数据、旧 Generation 清单不可用、来源参数/本金/策略保留、新旧收益可不同、旧结果不变、Track 源 Run 删除后完整起点至调查日重跑、固定 Checkpoint、新持仓独立可用、幂等收据、普通取消、跨拥有者拒绝、错误 Checkpoint 拒绝、非法原成本字段诊断。
- `contracts-fifth.log`：来源命令和当前 MCP 合同/权限 51 passed（3.90 秒）；`pagination.log`：含完整 provenance 上限校验 7 passed（2.57 秒）。来源 scope 不足返回 FORBIDDEN；不自动重跑、不使用旧执行器或字段兼容。
- `browser-second.log`：四项浏览器测试通过（4.9 秒）：显式读取、过期/空仓/请求失败、显式重跑与断线同请求重试、Track 固定 Checkpoint/选中期间调查日期及新 Run 导航；窄屏截图 `expired-holdings-rerun.png` 已视觉检查，无水平溢出。
- 首次 `pnpm test`：43 failed / 1479 passed，其中1项 provenance 夹具缺少新必需字段，42项受限端口/生命周期环境失败。修正夹具并在具备端口权限的同一工作树重跑 `quick-second.log`，完整快速检查 exit0：Python1522、Agent648、Auth200、Web368，Node工具/模型离线检查及 lint/typecheck 同入口通过。不声称全量集成/E2E已在13运行；14负责联合验证。
- 冻结审查 `/private/tmp/thesistrace-issue13-review-g6pla4t4`，HEAD4c2ad039；包含 tracked/untracked 最终文件、两份diff、来源/标准文件、SHA256清单与验证记录。Standards审查先完成：无发现；随后同一快照 Spec审查：无发现。审查后复核代码及来源上下文未变；只追加验收记录。
- 13按独立验收单元提交；14尚未开始。
