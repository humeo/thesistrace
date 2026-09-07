# Issue 06 验收证据

状态：complete。实现、验收、审查与独立提交完成。基线 `94d412e`；所有命令在隔离 worktree 执行。原 main 与 thesistrace-dev 数据未改动。

当前收尾状态：R5至R12 Standards→Spec均0未关闭发现。最终生产版本的镜像门禁退出0；完整回归暴露的测试缺陷已修正并按受影响范围复验通过。下文“待收集/进行中”等为逐轮历史，最终结果以本表和文末交付记录为准。

| 验证范围 | 当前最终结果 |
| --- | --- |
| 快速门禁与类型检查 | R8 Python 1116、Agent 638、Auth 196、Web 338通过；R9最终Web 340及类型检查另行通过 |
| 真实数据库 | Core 422及依赖重启、Auth 138、Agent 91通过 |
| 浏览器 | R10完整86例中84通过；剩余Financial及其下游Operator与R11 admission在R12全新隔离环境3/3通过（125s），最终各场景均有通过证据 |
| 镜像 | R9顶层pnpm test:image-smoke退出0；旧失败及根因保留下文 |
| 独立模型评估 | Luna/high首次、增量、长轮次3/3状态判据通过；只证明候选状态提取，非真实续接执行 |
| Review | Standards→Spec串行审查；当前0未解决发现 |

## 已完成前置票

01 `99e16db`；02 `0ca3b7a`；03 `08bddce`；04 `b58132a`；05 `94d412e`。各票 plan/evidence/issue 保存定向验证及串行 Standards→Spec 审查结果。05 最终 632 Agent unit / 90 PostgreSQL integration / 39 相关 Web tests 与类型检查通过；真实浏览器仅为生产组件 fixture，不冒称完整 Core/Agent 端到端或真实模型质量。

## 首轮完整门禁与修复

- `UV_CACHE_DIR=/tmp/thesistrace-uv-cache pnpm check`，退出 1，日志 `/tmp/thesistrace-ticket06-check-first.log`。Ruff通过；Python 1111passed/4failed，后续门禁未运行。
- 4项定向复现：`uv run pytest -q tests/architecture/test_core_runtime_boundaries.py::test_internal_import_graph_is_layered_and_acyclic tests/architecture/test_core_runtime_boundaries.py::test_web_shell_declares_only_the_four_product_resources tests/entrypoints/test_research_agent_mcp.py::test_stdio_entrypoint_reports_process_failure_by_its_lifecycle_phase tests/entrypoints/test_research_agent_mcp.py::test_stdio_entrypoint_reports_shutdown_failure_by_its_lifecycle_phase`，退出1，1.35s，`/tmp/thesistrace-ticket06-four-red.log`。
- 根因：CNInfo使用无状态诊断sink符合ADR0217，但允许依赖图漏记operational_events；路由断言错误包含import，误将导航helper名称当产品路由；02新增分页初始化后，stdio生命周期fixture缺database/分页factory，未到process/shutdown即startup失败。
- 修复测试边界：补合法依赖、只检查resourceRoutes数组、为生命周期测试注入固定分页secret的公开factory及database占位。没有改变运行时错误分类或放宽分页身份校验。
- 扩大至两测试文件：44passed/1failed，`/tmp/thesistrace-ticket06-boundaries-green.log`；唯一失败为未升级权限导致本机HTTP监听socket被沙箱拒绝，原4项已通过。第二轮pnpm check使用已授权隔离端口/Docker权限，日志 `/tmp/thesistrace-ticket06-check-second.log`，结果待收集。

## 文档

新增 `docs/runbook/session-context.md`，更新local-lifecycle/configuration/research-agent-eval的当前上下文、90%触发、小窗口、M/S与恢复契约。内容和最终集成尚待review，不声明最终验证通过。

## 未完成

完整pnpm check/image-smoke、Core/MCP与压缩/恢复的实际浏览器闭环、观测字段完整性核对、独立真实模型摘要评估、最终串行review及提交。

## 需求映射与仍待补齐的观测

- 预算/门槛：model-registry、model-runtime、guarded-language-model 测试覆盖配置与 D；session-context-controller.test.ts 精确构造232199/232200/232201完整输入、无空间保护、小窗口与跨日期固定快照。
- E覆盖/配对：session-context-selection/batches/generation 测试覆盖稀疏part引用、完整工具组、最后大结果进入E、超长文本完整分批、首次/增量/长轮次S、条件Reflector与失败不产生候选。
- PG/恢复：research-runtime.integration.test.ts 覆盖快照所有权/revision竞争、真实Provider payload、重启ask_user与Continue、部分正文排除、取消期间有效工具保留、所有长度与交替错误分支零重复执行。当前门禁会复验公开入口。
- 工具：tests/acceptance/test_core_research_agent_pagination.py 及相关 MCP runs/batches/context/daily_tracks 测试覆盖真实分页和小回执，完整产品串联仍待浏览器验收。
- 观测审计发现：当前run-telemetry仅包含聚合usage、最后一次输入估算/压缩统计；还需核验/补齐逐调用usage、工具页字节及恢复次数的安全事件。数据库恢复记录已有次数，不能将其冒称已写入运行诊断。此项按01/02/05验收缺口归因，完成前不标06 complete。

## 独立真实模型保留评估（进行中）

- 可复现探针：quality-eval.mjs；使用当前构建的生产generateSessionContext、patched Mastra Observer/Reflector和GuardedLanguageModel，仅InMemoryStore合成Session。原开发.env仅读取已配置模型凭据和本地服务端点；不接触开发数据库。
- preflight：3例（首次3消息/1349bytes、增量2消息/814bytes、长轮次4消息/33579bytes），0真实调用。探针最多12次调用、每周期600秒，调用前按配置C/D保守费用预留，未知usage立即停止后续调用。
- 首轮运行：THESISTRACE_CONTEXT_EVAL_SPEND_LIMIT_USD=1，Luna/high，参考价格沿用仓库2026-08-31 published-standard-upper-bound快照；这是声明口径的上界估算，不是代理实际账单。输出 `/tmp/thesistrace-ticket06-quality-first.json` 与 `.log`，结果待收集。
- 自动判据为候选生成、精确资源/请求/游标/错误保留、关键数值保留及完整计量。不会把这些局部判据冒称整个研究Agent资格认证；后续续接行为/语义核对仍需结合工程与浏览器证据。

### 首轮真实评估结果

退出0，3/3固定案例全部生成合法候选，并通过精确引用、数值和完整usage判据；共8次真实调用。首次25.437s，增量36.210s，长轮次93.238s；按声明参考价格估算USD0.034311。完整内容无关报告保存quality-first.json，未保存或输出M/S正文。未重跑/删除失败例；本轮没有失败例。这证明本固定样本的保留判据，不代表全研究任务资格认证、任意长上下文保真度或实际代理收费。

本轮辅助调用合计input43602/output6950 tokens，8次cacheRead全部0；实际缓存命中未出现。结构性固定前缀由前序Provider payload/重启测试证明，与这个真实usage结果分开陈述。

## 第二轮门禁进展

快速集合：Python1115passed、Agent632passed、Auth196passed、Web335passed，以及对应类型/preflight通过。Core隔离集成422passed/8deselected；6项数据库/RustFS重启测试逐项通过。Core项目thesistrace-test-20260906t233258z-52187-e4970a1b已进入清理并转入Auth集成；完整pnpm check仍未完成。

MCP runbook指纹/大小/时间/RSS已按02提交的benchmark与当前断言同步：e00ef7bf…89979、146969bytes、0.91s、157057024bytes/7.31%。没有重新编造测量值或声称新benchmark运行。

## 观测缺口修复

- 新回归先红：2failed/65passed，`/tmp/thesistrace-ticket06-telemetry-red.log`。缺少逐调用和恢复事件；不是不稳定复跑。
- Guard增加只读逐调用回调，在成功/length/失败/取消边界记录闭合预算、归一化usage和耗时；不记录原始finish reason。未知usage不填0；sink异常不能改变模型结果。
- 现有Run telemetry增加模型调用、工具结果UTF8字节数、恢复领取事件；每步从已有PG恢复查询恢复当前Run次数，仅在新持久化claim后增加。不添加新的运行调度、业务状态或正文存储。
- 67定向unit通过（telemetry-green.log），634全Agent unit与typecheck通过（telemetry-unit.log、telemetry-types.log）。公开Run+真实PG2passed/88skipped（telemetry-pg.log），证明恢复计数/辅助usage、Tool真实序列化字节数与正文排除。随后仅补齐事件中的C/P/H安全数值和文档，最终类型与回归仍待复验。
- 当前第二轮pnpm check的E2E镜像构建早于此观测补齐，不能将其当作最终源版本全门禁。Auth138和Agent90完整集成已通过；最终源版本仍需按计划验证。

## 浏览器门禁发现与定向修复

第二轮check在E2E发现：移动端账户入口隐藏时测试未展开导航；平板触屏账户入口被更高specificity的侧栏38px规则覆盖；桌面Chat Batch菜单按钮需悬停才接受点击，测试直接点击导致240s超时。证据位于隔离项目thesistrace-test-20260906t234955z-60058-c70db32f的playwright-results及check-second.log。已获得明确复现后停止该轮（退出130），入口已清理自己的容器/卷/网络；不是完整check通过。

修复：账户测试先按当前UI展开移动抽屉；触屏CSS以相同侧栏selector明确44px；Batch测试先悬停所属会话行再操作菜单，未使用force click或扩大timeout。定向重建/复验日志 `/tmp/thesistrace-ticket06-browser-fixes.log`，结果待收集。

工具链核对发现原host PATH选中Node26.4.0及pnpm11.19.0，虽前述工程测试通过，但不能作为声明的固定工具链结果。已信任当前worktree仅含工具版本的.mise.toml，验证 `mise exec -- node --version`=24.14.0、pnpm=11.9.0；后续和最终门禁统一使用 `mise exec --`，不会修改仓库版本要求。镜像内部此前已使用固定版本。此前真实模型保留报告保留其原运行证据，不声称来自Node24。

定向浏览器4passed（38.9s），`/tmp/thesistrace-ticket06-browser-fixes.log`，固定Node24.14.0/pnpm11.9.0，新隔离项目thesistrace-test-20260907t000232z-63625-8e5bfbd1已自动清理。移动账户、平板44px、Factor/Strategy两类Batch的真实用户闭环均通过。修复后没有force click、超时放宽或重跑掩盖失败。

## 压缩浏览器场景（进行中）

Scripted辅助响应/截断替代回归先2failed；加入当前测试Provider的受控Observer/S和明确场景主响应后2passed，连同原Scripted 31passed。首次类型检查暴露ReadableStream未启用asyncIterator声明，改用标准reader后通过，不修改TypeScript lib或绕过类型。日志scripted-context-red/green/types-fixed与scripted-final。

新增chat-context.spec.ts：在唯一Test Session中预置合成原文，经UI调用生产控制器；normal读取真实Core上下文；recovery和recovery-fails检查一次记录、独立原/替代消息、禁止截断工具执行、保留原文与刷新hash一致。场景没有浏览器mock Agent响应、force click或新压缩调度。定向隔离E2E日志 `/tmp/thesistrace-ticket06-context-browser.log`，结果待收集。

固定工具链下现有观测改动634Agent unit、Agent/Web类型检查、quality零调用preflight均通过（pinned-agent-unit、pinned-agent-types、pinned-web-types、pinned-quality-preflight日志）。此结果早于Scripted辅助fixture新增，最终回归仍需覆盖新增文件。

### 快速突发流的正文丢失回归

首次完整压缩浏览器3例：normal通过，recovery/recovery-fails均丢失原正文（context-browser.log，1passed/2failed）。新增公开Run+真实PG最小回归，burst-red.log中1failed/90skipped，正文为空。临时合成数据探针证实原正文既没有TEXT_MESSAGE事件，也没有raw Mastra记录，排除UI和ID归属问题；降低Guard高水位仍失败（burst-backpressure.log）。

根因是controller.error清空下游尚未消费的队列；改为Provider规范的有序error part后close，保留已生成正文，错误仍由Mastra恢复处理器接收，未验证完成原因的全部工具part继续被丢弃。burst-ordered-error.log中公开Run回归通过（1passed/90skipped）；所有DEBUG探针已移除。Guard60unit通过，完整Agent636unit通过（ordered-unit-fixed、ordered-all-unit）。测试消费器按Provider协议读取error part，未放宽预期错误码或工具执行断言。

补充小窗口真实浏览器场景：先建立快照，再追加原文，选择C=65535测试模型；断言零模型步骤、无辅助恢复、快照/历史/选择保留，刷新一致；切回大模型正常压缩。仅测试registry增加第三个Scripted模型，生产配置不变。当前4例隔离E2E日志context-browser-fixed.log，结果待收集。Web类型通过。

第二轮4例中恢复成功/失败均通过，另外两项为验收夹具错误：UI全局状态短暂仍是上一轮完成；SQL ORDER BY created_at引用了外层Session（Run实际字段started_at），导致拿到旧Run的step_count。改为按submit返回的确切Run ID等待PG终态，再验UI，并用run.started_at排序。context-browser-final.log中4passed（25.4s），隔离项目20260907t002926z-71629-6741c985已清理。后端safe telemetry也证明小窗口无调用、step_count=0与CONTEXT_TOO_LARGE；未改变产品逻辑来迎合错误断言。

完整固定工具链门禁已启动：check-final.log。仍须补充真实Core最后工具输出后的完整链路证据，不把预调用压缩当作工具返回后压缩；新增场景草案在/tmp，待当前集成结束后接入，避免与Schema生成并发编辑源文件。

### 真实 Core 结果触发压缩与分页续读

Scripted双工具/精确游标回归先1failed/2passed（tool-batch-red.log），补齐仅Scripted场景后32passed（tool-batch-green.log）；Agent/Web类型通过。真实浏览器single/batch两例2passed，14.8s（real-tool-browser.log），隔离项目20260907t004512z-93843-e8ef5279已清理。

两例用拥有者Test Session的合成原文和24个合法120字符中文文件夹，初始输入低于T，实际Core结果使下一请求越线。断言checkpoint水位包含本轮get_research_context；batch也包含get_alpha_catalog，证明压缩发生在整批真实工具返回之后。随后通过真实next_cursor分别读第二页，总4个只读活动，保留进一步分页提示；single仅1个工具活动。无恢复重试，revision=1，刷新后原文/快照保持。生产调度/分页实现未为测试改写。

主check的快速阶段（此前Scripted新增batch夹具前）Python1115、Agent636、Auth196、Web335通过；新增夹具另行32定向与类型验证。随后Core422/8deselected通过（640.26s），依赖重启测试逐项通过，Auth138集成通过；Agent集成及最终E2E进行中。所有业务代码使用同一最终版本；后加的验收夹具通过对应定向验证并进入后续集成镜像。

### 全套浏览器的新夹具故障与补齐

check-final.log：Core422与6个独立重启场景、Auth138、Agent91真实集成均通过；85例E2E在capacity用例等待get_research_context超时。旧通用Scripted场景选“首个无必填参数工具”，02的get_alpha_catalog分页参数改为可选且03工具确定排序后，实际选择目录。完整生产回答已完成，失败不是Agent容量未释放。保留失败证据后停止已核实的Playwright PID95943，整轮退出130，隔离项目20260907t004828z-95621-59af795b已清理；不是完整check通过。

定向单测在目录排前时先红（explicit-tool-red.log），将该“读取研究上下文”夹具固定为get_research_context后33定向通过，638全Agent unit与Agent/Web类型通过（agent-unit-final/agent-types-final/web-types-final）。未改变生产工具排序或选择策略。

为真实恢复中/刷新/停止路径补充无计时器的Scripted Observer屏障：仅明确合成来源标记触发，等待真实Run abortSignal，取消后结束流，不执行业务Tool，不引入HTTP测试后门。单测先红后绿（observer-cancel-red/green）；浏览器等待持久化恢复标签后刷新、Stop，再检查无M/S发布、一次记录和原正文保留。定向capacity/recovery/concurrency E2E进行中，日志capacity-recovery-browser.log。

恢复中/刷新/停止与capacity/concurrency三例真实浏览器3passed（13.7s），capacity-recovery-browser.log，项目20260907t005449z-98838-6e6b711a清理完成。Observer等待明确取消而非计时器；UI刷新仍显示恢复中，Stop后无已发布M/S（snapshot为null），原正文保留且恢复次数为1，工具未执行。完整Agent638unit、Agent/Web类型通过。

最终冻结后的门禁正在运行：check-delivery.log与独立e2e-delivery.log。最后的product code修改是有序Provider error part；其后的夹具/断言变更现已冻结。Standards审查可并行于额外整体验收，但两个审查轴仍按用户要求串行；最终门禁、review及提交完成前不修改完成状态。

### Spec 语义评估补齐与最终浏览器失败闭环

R1 Standards 0 findings；Spec 提出 P2：只检查 ID/数值字符串不能证明续读语义。新增 quality-semantics.mjs 独立判据及两个负向测试，实际候选 M/S 进入中立状态提取，不提供源文或标准答案、不执行业务工具，仅保存布尔判据/usage。quality-semantic-first.json 保留首次结果：1/3，首次/增量的 rebalance 不符合预期。合成源句“do not change 20 holdings or rebalance every 5 sessions”存在否定范围歧义，改成明确保持20持仓、每5交易日调仓；不改产品提示词。quality-semantic-clear.json：3/3，11调用、USD0.02988546参考成本，usage完整。报告覆盖状态提取而非真实续读执行或全Agent效果；原quality-first.json只是有限保留证据。定向Spec复审0，P2关闭；快照/tmp/thesistrace-ticket06-quality-r2。

独立 e2e-delivery.log：78通过/8失败，退出1；全部压缩相关用例通过。失败为鉴权后聊天卸载、旧遥测字段、2个未悬停删除菜单、2个旧进度展示断言、Research返回默认文件夹、旧Operator可编辑幂等键测试。不是完整门禁通过。项目20260907t005735z-334-06578354已清理。

鉴权根因：runtime discovery失败将已挂载conversation卸载，丢失草稿/精确拒绝状态；ChatConversation现保持已连接会话挂载，组件回归通过，新增到test:shell。独立4例鉴权/隐私/桌面及手机删除回归通过33.5s（browser-regressions.log，项目20260907t011102z-27250-074129c4已清理）。遥测字段断言与内容空值限制同步；删除菜单先悬停。

Research默认导航传递当前BrowserLocation，导航更新后按目标重新加载Folder；旧A2UI断言与既有progressHistory行为同步，结束后隐藏过期queued/running，成功提交的Tool回执链接继续可查。对应3例artifact-folder-browser.log正在验证。Operator验证改为读取真实确认对话框生成的key，各原有提交/响应丢失/轮询/权限故障场景仍通过该真实key绑定；显式改目标复用key改用浏览器HTTP契约拒绝验证，不恢复已删除的产品输入框。

check-delivery.log仍在运行；上述发现后的实现/验收文件已改变，后续最终门禁与review须覆盖更新版本。

### 定向复验与 R5 冻结

Operator r2：完整既有流程1passed（2.2m），operator-browser-r2.log，项目20260907t012139z-32810-bd52fa36清理。r1故障为合成acceptedReceipt在真实key生成前捕获空串；改成响应时绑定实际key，未改产品。取消重试的新key从实际proof请求观察，不假设已删除的输入框；原HTTP/Worker/权限断言保留。

artifact-folder-browser.log：2passed/1failed，A2UI实时/键盘/窄屏与默认Folder恢复通过；admitted生命周期先误找Tool内链接，改取实际最终答案链接。admitted-browser.log随后暴露旧Run complete标签竞态；绑定真实新Turn完成后，admitted-browser-r2.log继续走到旧3卡片断言。现按既有progressHistory契约分别验证2个factor可见卡片、策略后4个最终卡片、数据库至少6份完整历史，刷新仍4；最终全量验收待跑。

check-delivery.log：quick通过、Core422+6重启、Auth138通过；Agent87/91，4失败。两个恢复屏障使用vi.waitFor默认1秒而数据库/摘要交互需更长；多Run压缩案例30秒测试超时，后续测试首调用亦失败。为相关屏障设10秒条件轮询、多Run测试90秒；不改运行时超时或业务断言。pg-timing.log对应8场景全部通过/83skip，62.55s，其中多Run案例实测33.131s（超过旧30s）。此证据支持等待预算修正，最终全套仍须通过，不把简单重跑算修复。

R3 Standards发现质量探针旧字符串finishReason兼容分支，已去除；R3+R4复审0。Spec发现Folder导航乱序，folder-race-red.log两个受控响应顺序测试先失败；取消旧加载、向三个Core读取传递signal、成功和失败均检查取消、加载时清空旧资源后，folder-race-green.log24相关测试通过。新增生命周期测试已纳入test:shell。R5 Spec0，导航P2关闭；R5 Standards待核对。

R5完整门禁：check-r5.log运行中（命令UV_CACHE_DIR=/tmp/thesistrace-uv-cache mise exec -- pnpm check）。image-smoke.log为R5导航保护前的镜像；本轮结果与最终镜像版本分别记录，最终验收须覆盖R5。

### R6 镜像 MCP 持久化检查

旧 image-smoke.log 退出2，项目20260907t012020z-31895-6747f13e在image-smoke-mcp-evidence阶段报mcp_persistence_contract；此前重启/Worker恢复阶段均通过，cleanup、runtime_secret_cleanup、raw_canary_scan均0。隔离R5 PostgreSQL只读表名查询确认断言命中的全部是auth下合法的七个OAuth表，符合auth/schema-initialize.ts当前声明。旧检查跨所有schema禁止oauth，误伤Auth授权服务。

仅精确放行auth所属七个OAuth表；其他schema同名、MCP表及原禁止表继续拒绝。新增允许/拒绝回归，smoke architecture文件35passed（2.88s），Ruff通过；第一次未升级权限运行34passed/1个现有HTTP端口PermissionError，不算产品失败。R6快照/tmp/thesistrace-ticket06-review-r6-delta，Standards→Spec均0。测试脚本通过现有/smoke只读挂载进入仍在运行的R5最终镜像验收，生产镜像代码未改变。

### R7 Operator 重试定位

image-smoke-r5.log退出1，项目20260907t013311z-51531-cfa81a4d的Operator浏览器在1974行toBeFocused触发strict mode：Chats侧栏的Retry与Operator Researchers错误区Retry同时存在。此前目标数据、重启、存储中断和重试阶段通过；清理与canary扫描均0。MCP evidence在Operator浏览器之前且已通过，R6真实镜像合约得到验证；整个image-smoke仍因Operator失败而未通过。

把焦点及恢复点击两个定位限定到现有Operator Researchers region，保留焦点与恢复后Invitations可见断言；不改产品或以first/force回避歧义。R7镜像完整复验日志image-smoke-r7.log运行中。R5完整check已通过Core422（889.07s）及六个依赖重启测试，继续后续阶段。

### R8 浏览器时序断言

R5 E2E已完成新增上下文7例和完整admitted研究生命周期，但两个既有场景失败：protected MCP read在主回答终态自动收起outer history时点击内层summary，等待隐藏元素超时；Strategy案例实际一次get_research_run便得到成功结果，却要求至少2次poll。前者改为先等待Run complete和outer closed，再按用户操作展开；后者保留completed工具可见和真实Result/NAV/收益等验证，移除与Worker速度相关的最少调用次数。Scripted生产Fixture在第一次poll已succeeded时确实直接读Result，不改业务时序来满足测试。

R8 Standards0，Spec复审中；check-r8.log使用最终测试版本完整重验。R7 Core镜像主阶段status0，Operator浏览器88s通过、MCP evidence5s通过、final evidence/secret scan/cleanup全部0；顶层Auth/Agent/Caddy镜像子门禁仍需收集最终退出码。

### R9 Market 提交后焦点

R5 check最终退出1：quick/Core/Auth/Agent均通过，E2E83/86（689s）。第三失败在OperatorDataPage丢失提交响应、成功查回回执后Review Refresh失焦；不能因独立Operator及R7镜像通过就算已解决。Market原requestAnimationFrame可能在React提交前执行，此时按钮仍disabled。Financial/Industry已有提交后focus的模式，Market改成同样的pending ref + effect，在confirmation/pending清空的DOM提交后恢复焦点，删除五处frame焦点回调。

确定性happyDOM回归模拟frame先于React commit，真实父页面和对话框、受控HTTP client；direct accepted/reconciled两例旧代码均红，修正后7项相关测试全绿，类型检查通过（market-focus-red/green/types.log）。新测试纳入test:shell。R9 Standards→Spec待审。

R7顶层pnpm test:image-smoke最终退出0，覆盖Core/MCP/Operator/Auth/Agent/Caddy及清理；此结果早于Market产品修复。最终image-smoke-r9.log新构建复验。check-r8的quick Web阶段早于R9，新增测试另行通过，后续E2E最终镜像会包含R9；测试/类型与源码版本边界如实记录，不把旧镜像当作新代码证据。

R9 Standards→Spec均0；完整Web test:shell 340passed（18.56s），web-shell-r9.log。最终image-smoke-r9.log顶层退出0，Core隔离项目20260907t021159z-89776-53bdaf97；MCP evidence4s、Operator浏览器90s、final evidence/secret scan/cleanup均0，后续Auth/Agent/Caddy镜像子门禁全部通过。Caddy故意关闭upstream后的502是期望拒绝证据，最终keepalive两个202/receivedPosts2通过。R8 check Core422通过（921.15s），后续集成/浏览器继续。

### R10 新 Turn 完成等待

R8 check的Auth138/Agent91均通过；最终E2E的DailyTrack首次用例发现list_daily_tracks已存在但history隐藏。send helper仅等全局Run complete，可以立即接受上一轮的同名终态，随后与新轮终态自动收起history竞态。绑定既有submitChatPrompt返回的新Turn ID，等待该Turn completed_at对应time及history关闭后才继续；Batch同类helper同步处理。其余业务结果/工具权限/次数/页面断言保持。

R10不改生产代码；按仓库“只复跑受影响检查”原则，保留R8已通过的quick/Core/Auth/Agent及R9最终镜像/Web证据，以e2e-r10.log完整86例复验浏览器阶段。不将旧pnpm check非零退出描述成单次命令成功；最终门禁证据由明确版本和各阶段结果组成。

### R11 研究 admission 等待预算

R8 admitted用例初始提交只等30秒，失败截图Worked35s/5tools。隔离PG准确Session f62345f5-d075-4213-8040-6715ab14af83及安全telemetry投影显示step6模型于38.548s完成、工具39.134s完成，超出该测试等待；Run后来45.405s以INTERNAL_FAILURE结束，此失败证据保留，不宣称该轮成功。R10镜像构建同时进行，不能把增加等待当产品性能优化。

初始提交绑定返回Turn ID、等待该轮time并采用现有研究流程一致90s上限，再断言Run complete；产品调用超时和所有业务结果断言不变。R11仅改chat-shell测试，在最终e2e-r10尚未执行该文件前落盘；最终具体场景与整套结果另行确认。

R10/R11 Standards→Spec均0。进一步安全诊断：step6模型调用本身119ms，38.548s是Run累计时长，空档在框架/调度之间，不能写成模型生成32秒。Core submit已于02:38:34.395返回succeeded；浏览器trace Close context为02:39:04.064～04.430，Run失败02:39:13.246。DurableRunner使用refCount:false，故时间先后不足以认定断连导致INTERNAL_FAILURE；旧终态的具体内部原因未由安全日志确定，不作已修复产品缺陷声明。该测试30s等待不足有直接进度证据，最终正常流程仍须通过；不通过猜测修改产品或新增原文日志。

### R12 冷启动与受影响流程复验

e2e-r10.log退出1，84/86（17.1m）：Financial catalog在冷goto/data后5秒等Researchfields超时，记录仅Auth get-session200/capability404，Data/catalog尚未返回。改为export并复用auth-fixture已有openDataOverview（两个实际HTTP200及body完成、Dataoverview可见）后保持全部原字段/财务/Track断言。Standards→Spec0。

Operator第二失败是基线market11/financial05不符合其要求：Financial场景提前失败未执行publishFinancialTrackHead(recovered)，后续普通Research场景只推进market11。保留严格基线校验，不将半份准备当合法状态。R12浏览器在全新项目串行执行admitted、Financial、Operator三个完整案例；日志browser-r12.log。所有生产代码仍是已通过R9镜像的版本，不复跑无关数据库门禁。R11等待在R10测试收集之后编辑，采用此次明确加载最终文件的定向验收作为版本证据。

### 最终交付记录

- R12 browser-r12.log退出0：admitted完整研究生命周期、Financial完整发布/Track、Operator完整流程3passed（2.1m/125s）；项目20260907t030009z-40171-0ba03b6c，runtime_secret_cleanup/raw_canary_scan/cleanup/status均0。新Turn等待、冷启动等待和Market焦点均由最终源码验证。
- pnpm check已实际执行；R8 quick/Core422+依赖重启/Auth138/Agent91通过，E2E因测试等待缺陷退出1。R10全量84/86后，R12按实际受影响边界完成剩余复验；不声称某次pnpm check命令整体退出0，也不因测试辅助函数改动重跑未改变的数据库产品。最终生产镜像test:image-smoke R9顶层退出0，Web最终340与类型检查通过。
- 质量评估与诊断限制：固定合成首次/增量/长轮次3/3判据通过，属于候选M/S状态提取，不是全Agent真实金融任务的质量资格认证。一次旧测试超时后Run的INTERNAL_FAILURE未由保留的安全日志精确归因；正常完整场景最终通过，不把该历史终态宣称成已修复的具体产品缺陷。
- R1～R12审查中的实际代码/契约发现均闭合，当前Standards/Spec各0；最终diff检查通过。未改原main、未操作dev容器或卷，无兼容/迁移/fallback。仅此worktree的06改动进入独立提交。
