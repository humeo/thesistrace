# 14 — 三种能力联合验收：实施计划

## 开始基线与范围

- 2026-09-13：13已独立提交为 `31a5214f4ea468ceedabee2ba308c805bef7f8d4`，开始14前工作树干净。01–13均已按计划、实现、验证、串行Standards/Spec审查和独立提交完成。
- 仍只使用隔离工作树 `codex/research-capabilities`；不修改原工作树，不推送、部署或自动操作服务器。以main为开发基准核对交付，但本次任务没有授权在用户其他脏工作树直接集成。
- 依据[14票](../issues/14-qualify-three-capabilities.md)、[母规格](../spec.md)当前执行约束及AGENTS。单一当前合同；不新增兼容、字段别名、旧执行器、vXX或迁移。已有历史迁移回归若夹具漂移，只修复测试证据来源，不修改指纹绕过校验，不在dev/线上执行迁移或清库。

## 验收顺序

1. 逐项映射母规格当前行为、01–13每票验收项到实现/测试/现存证据；核对独立提交及直接/传递阻塞都已完成。明确撤回的旧迁移要求，修正任务索引中与当前执行约束冲突的现行文字；不提前关闭母规格。
2. 核对组合矩阵：条件Signal、Universe/申万一级共同输入、10万及其他本金、equal/rank/inverse-volatility三种配权、每日Exposure、独立Selection Interval，贯穿Run、Batch、Track。复用独立人工期望和账户对账场景；缺口才补最小公开行为测试，不用同实现重复计算期望值。
3. 核对最后Open正常交易、跨Chunk/Track切点、恢复/取消及错误合同拒绝；永久Result/Checkpoint与临时持仓独立，TTL及不同当前数据重跑无需结果相等。复用12容量证据并说明量测范围，不把TTL解释为无写入峰值。
4. 优先解决12已记录的历史测试夹具漂移：`rank_ic_migration_target_schemas`以当前DDL合成历史target，导致维护迁移测试在指纹校验前失败。先在当前提交验证该偏差；仅将历史测试夹具绑定到可核实的历史DDL及原指纹，不为新功能新增迁移或运行时兼容。
5. 最终联合版本运行仓库原入口 `pnpm check`（quick、browser、Core/Auth/Agent真实依赖含恢复阶段、E2E）。使用现有TestRun/Compose隔离资源及专用uv缓存，在具备回环端口/Docker权限环境运行；记录每阶段handle、证据目录、退出码及首次失败。失败先定位，再修复并复验受影响范围，必要时完成尚未执行阶段，不宣称短检查替代完整入口。
6. 现有少量E2E核对分别提交两类研究、开始Track/手动刷新、过期显式重跑；真实浏览器补查当前产品关键页面，保存截图及状态，权限/分页在对应真实依赖边界验证。
7. 按实际改动审计镜像/启动边界：若01–13已影响最终运行依赖或Worker启动，选择现有镜像smoke；恢复/部署边界只有实际需求才升级完整镜像验收，不运行真实供应商/真实模型或服务器发布。说明未测试边界。
8. 证据齐备后冻结14修改，串行Standards审查→修复/复审→Spec审查→修复/复审，更新14tracker并独立提交。最后针对全部14票与提交/测试证据做完成审计；未满足项继续处理，不将预算/时间视为完成理由。

## 交付证据

- 在本计划及必要的联合验收映射中记录基线/最终提交、命令、失败原因、修复与复验、截图/账本/持仓容量来源、未测试边界。
- 13基线完整快速检查已通过：Python1522、Agent648、Auth200、Web368；原生MCP/Worker与来源边界真实验收通过。该证据不能替代14规定的 `pnpm check`。
- 12记录的历史夹具故障仍须在联合版解决；此前没有声称全量集成通过。

## 执行记录

- 14开始时仅阅读票据、母规格验收结构、package脚本及历史夹具入口并制定本计划；尚未修改14产品或测试代码，尚未运行联合门禁。

- 基线复核：当前“历史”fixture指纹为34220713aa0cb4f2f10c29cc04ae2cb05ae348166fd501f7e3dae2d03fa99ea2，声明目标为6f04fe84573259465442c092856b69714ed339c2093d51dcf67ba4b68aaa359f，确实不一致。逐一读取历史提交c23842ed49c667df2d80a62093fdf69c1527260b的8份实际schema.sql，计算恰好匹配声明目标；已固定为纯测试JSON夹具并保留source_commit/指纹，fixture用真实DDL再验指纹。没有修改运行时迁移函数、指纹常量或生产schema。任务索引中残留迁移演练文字同步改为当前合同初始化/读写要求；不改母规格状态。

- 历史夹具隔离验收8 passed/492 deselected（2.62秒），`historical-fixture-first.log`；随后启动完整 `pnpm check`，证据 `check-first.log`。
- 覆盖审计发现现有E2E包含分kind提交与手动Track，但没有真实浏览器→后端的持仓过期重跑闭环（13为组件浏览器+独立原生MCP/Worker证据）。已扩展既有隔离Draft/Track闭环，在本测试Track的临时持仓上推进到期时间，验证读取不提交、新Run显式提交、固定来源、原历史不变、新持仓可读及截图；不新增产品端点，不触碰共享dev数据。同步将该E2E的旧Rebalance展示断言更新为当前Selection文案。完整check尚在quick阶段，E2E阶段将读取这些新增断言；未宣称新闭环已通过。
- 已建立[联合验收映射](14-acceptance-matrix.md)：16组现行可观察行为对应实现测试入口，01–13子项状态/独立提交/计划逐票核对；main共同基准为2daf193e。完整check已通过quick（Python1522、Agent648、Auth200、Web368）及49项浏览器组件，进入Core真实依赖阶段，handle6002；尚未完成整套门禁。
- 浏览器分页测试重写了已跟踪的旧功能截图 `.scratch/research-global-sort/metric-filters-mobile.png`。确认写入者为现有 research-pagination.spec.ts 后，仅将该无关生成物恢复到本工作树HEAD，不纳入14提交，不操作原工作树。
- 镜像边界初查：相对main共同基准没有Dockerfile/lockfile/依赖或Compose配置改动，但研究/Batch/Track子进程入口与Publication维护行为已改变；联合验收结束后选择最终镜像smoke核对真实镜像初始化与Worker链路，恢复语义先由完整integration专门阶段及E2E证明，不直接扩大到未请求的服务器发布资格。

- 联合check的Core阶段出现失败但持续推进，保留handle6002。通过collection顺序定位最早五个失败并用另一个现有TestRun隔离入口复现（early-failures-first.log）：3 failed/2 passed。两个检查点SQL夹具遗漏当前必填holding_payloads/strategy_event_payloads；维护CLI测试仅执行一步，却只推迟orphan_scan，新增holding_expiry先获得调度。补齐合法空对象，测试显式推迟所有非queued_deletions任务后，early-failures-second.log为5 passed/495 deselected（3.99秒）。没有修改运行时合同或增加兼容。另两个全量失败单独通过，待全量traceback核对顺序残留。
- 三个早期回测失败独立复现（early-acceptance-first.log，3 failed/497 deselected，20.20秒）：两处旧测试仍假设Factor只有summary物理产物，未包含06新增每日观测/分期统计；一处终态字段枚举未含target_selection/target_exposure。改为通过完整Result reader校验Factor产物完整性并断言独立语义结果，终态显式补齐当前字段；未放宽产品校验。待复验。
- 首次完整check在Core结束：18 failed、474 passed、8 deselected（1132.99秒）；专门重启/Auth/Agent/E2E尚未执行。证据run_id 20260912t230639z-27420-7ed85a47及check-first.log/failure-summary.txt。其余已定位：对象全表计数依赖前序状态、短区间实际无入场Open、新Factor checkpoint观测产物、Signal+Exposure联合预算事实、MCP新增工具/可查询section枚举、Batch容量夹具过低先触发单Run拒绝，以及人为把持股数改0已在typed claim前失败。按当前边界修正：对象检查限定本产物/测试先建干净schema；破坏指定strategy_summary而非任意首对象；预算检查上限与冻结不变；Batch用128MiB触发组合容量、用合法动态Exposure在执行时越界触发单项失败。产品代码未改，不降低准入或Result校验。复验首轮失败及完整Publication顺序场景，failed-regression-first.log，handle42586。
- 首轮定向回归44例：38 passed/6 failed（146.91秒，failed-regression-first.log）。后续失败定位并修正：orphan扫描夹具同样必须推迟holding_expiry；参考Track checkpoint只保留完成边界之后的增量、初始净值取激活终态；MCP来源校验保留新公开checkpoint_manifest_sha256并校验摘要格式，其余私有内容仍拒绝；Run authoring provenance补Exposure；动态Exposure故障场景预留一日历史并先断言202。另MCP context工具清单修改时误将工具名插入调用参数，diff复核立即修正，但正在执行的测试已加载旧内容导致一次ValidationError；当前文件已仅在工具清单增加该名称，下一轮复验覆盖。remaining-regression-first.log/handle57892复验这6例。
- 剩余6例复验：4 passed/2 failed（110.08秒，remaining-regression-first.log）。MCP目录首次因算子数量增加而出现next_cursor，随机加密cursor不应逐字相等，改为比较语义内容及是否还有下一页；同步raw stdio清单/断线重连工具数更新17。Batch动态故障表达式误用了universe_return(1)，当前算子为零参数universe_return()，已经按实际目录修正；两项继续通过final-two-regression-first.log/handle21297复验。
- 最后两项定向复验通过：2 passed/498 deselected（8.96秒）。全部首次失败已经逐项通过受影响测试，开始最终联合pnpm check第二轮（check-second.log，handle6150）。为了在整套门禁到达E2E前尽早验证新闭环，同时使用仓库独立E2E拓扑仅运行Default/custom Folder Drafts用例（expiry-e2e-first.log）；两个运行均为现有隔离入口，不共享dev资源。
- 新E2E首次失败于旧helper的全局.cm-content定位，Signal/Exposure两个编辑器都匹配（expiry-e2e-first.log，截图已查看，run_id 20260912t234007z-42052-27d5579c）。将core-shell与auth-flow中的同类Signal操作明确为可访问名称Alpha formula；不修改页面来迎合旧selector。expiry-e2e-second.log/handle79399继续验证。完整check第二轮快速检查已通过并进入49项组件浏览器阶段。
- E2E第二轮已完成草稿/两类Run/Track并到达过期显式提交，失败于成功导航后调用Playwright response.json()（Network.getResponseBody: No resource）。改为验证202及新Run路由后从URL取得新ID，再由API读取结果；不延迟或拦截产品导航。expired-track-holdings.png已查看，显示Expired、显式重跑按钮、使用当前数据/原结果保留说明及已删除的来源Run。expiry-e2e-third.log/handle73270继续完成新Run持仓和历史不变断言。
- 新增真实浏览器闭环通过：expiry-e2e-third.log 1 passed（55.8秒），run_id 20260912t234903z-56291-c5b356be。页面依次验证两kind提交、固定现金、手动Track推进/来源Run删除、Expired状态读取无新任务、显式202新Run、原start_date与100000本金、来源链接/旧Track完全不变、新持仓可读；expired-track-holdings.png与current-data-rerun-holdings.png保留并已查看。完整check第二轮仍在Core真实依赖阶段（handle6150），没有提前声称整套门禁通过。
- 第二轮Core普通集成/验收阶段通过：492 passed、8 deselected、1既有warning（1378.16秒），run_id 20260912t234521z-54058-29efcb3e/evidence/pytest.xml。pnpm check handle6150继续运行，尚须专门依赖重启、Auth/Agent集成和全套E2E；本条不等同完整integration已通过。
- Core专门恢复阶段六项均通过：database-restart、rustfs-restart、rustfs-strategy-restart、rustfs-batch-cancel-restart、postgres-batch-restart、postgres-strategy-restart，各1 passed；最后两项65.08/65.68秒。对应run.txt phase均status=0，证据同20260912t234521z-54058-29efcb3e。完整check已继续到Auth集成，不重跑或替代这些已验证阶段。
- Auth真实集成145 passed。第二轮pnpm check在Agent集成停止：94 passed/2 failed，均为research-runtime.integration.test.ts两个batch模式仍断言旧“Ordered child ResearchRun results”文本，当前Scripted输出是ResearchComparison组件。已改为断言结构化组件及有序CHILD_IDS，继续保留持久化、回放/重启不重复准入及私有结果隔离断言。用原入口完整复验Agent集成（agent-integration-second.log，handle57315），并运行Agent typecheck；按AGENTS不重复未受这项测试修正影响且已通过的Core/Auth阶段，之后补完原check尚未执行的全套E2E与镜像smoke。记录分段修复，不宣称check-second整条命令exit0。
- Agent复验96 passed（3文件，60.65秒）、typecheck通过。启动全套pnpm test:e2e（e2e-full-first.log），补完完整门禁最后阶段；新增过期闭环已先单独通过，不等同全套E2E已通过。

- 全套E2E第一组仍运行（handle47170；run_id20260913t001701z-79110-d83d93e4，71项；当前旧镜像）。定位真实产品缺陷：ResearchResourceCards把成功Strategy结果强制解析成带Factor的旧组合结果；先以独立Strategy fixture复现1failed/4passed（resource-card-red.log），再按research_kind判别各自结果与指标，5passed（resource-card-green.log）。Web typecheck及完整shell368passed（web-typecheck-final.log、web-shell-final.log）。后续E2E必须使用重建镜像，当前全套首轮不代表修复已被浏览器验证。
- 其他已定位E2E测试契约漂移：Auth欢迎标题/导航品牌、Strategy直接准入缺initial_cash等字段、Chat资源卡替代旧结果表格与静态metrics/provenance披露、重载后读取时间变化、拒绝渲染的当前错误消息。auth-flow/chat-batch/chat-daily-track/chat-concurrency/chat-failures/chat-shell测试按当前实际UI/API修正，继续保留身份、有序子Run、实际指标、重载/删除不重复准入、键盘/窄屏等行为。新测试尚待当前首轮结束后完整复验，不能将修改断言视为通过。
- Context失败证据：隔离DB检查点inputTokensBefore=238232/238233，新增MCP工具定义后18400次历史fixture在读取工具前已超阈值；sourceWatermark未包含后来工具结果。将fixture降至17400以重新覆盖工具结果推动跨阈值，仍要求checkpoint包含真实工具结果；等待复验。
- Capacity首轮50并发请求仅20进入代理hold，DB另有MCP_TRANSIENT；Core ingress每principal并发4，直接同时冲击Core先触发另一层限制。容量测试调整为逐一等待已完成Core响应进入代理hold再增加任务，保持50个Host任务并发和第51个拒绝/无Session写入断言；待复验，不修改运行时限制。
- 全套首轮第一组71项结束：45 passed/26 failed（18.7分钟），其余8个隔离用例继续在同一handle47170运行。新增定位：日期输入测试通配拦截全部API导致当前工作台前置请求被abort，改为只覆写真实Data响应中的日期范围；Folder测试应检查可见的summary而非关闭菜单内同名span；Batch直接准入补每子策略initial_cash_cny；MCP授权E2E改用当前邮件验证码登录及当前品牌文案。Operator两处当前品牌文案同步。
- 已启动修复后镜像的11项聊天专项（handle57910，e2e-chat-regression-first.log，run_id20260913t003602z-90008-b092fbe0）；首个Batch用例尚未结束。所有后续测试修正仍需完整复验；E2E collection已通过79tests/14files，不代表运行通过。
- 修复后聊天专项继续：Strategy Batch、丢失Batch响应重放、50任务容量、真实工具结果后的single/batch压缩已通过（仍在跑11项，其余未定）。Factor Batch已通过结果/指标、重载、窄屏、重命名及导航，末尾删除菜单被异步聊天滚动关闭。定位SessionHistoryList对所有document capture scroll均关闭菜单；新增公开组件交互测试先失败（session-menu-red.log，非祖先main滚动关闭了aside菜单），修复为仅触发器祖先滚动关闭，1passed（session-menu-green.log），resize/外部点击不变。Batch E2E增加实际鼠标滚动聊天区后菜单仍可删除的断言，需下一次新镜像验证。
- 菜单修复后Web完整shell369 passed（43files，22.55秒）、typecheck通过；证据web-shell-menu.log/web-typecheck-menu.log。当前聊天专项镜像早于菜单修复，仅证明资源卡修复和其他用例；最终重建不可省略。全套首轮已有Financial、完整草稿/过期重跑、各独立小闭环及Operator导航隔离组通过，Operator邀请隔离组卡在旧文案“A 48-hour Invitation”，按实际“48-hour invitation link”修正，运行仍继续其余组。
- 聊天专项第7项DailyTrack也走到删除Chat菜单时受同一scroll缺陷阻塞（对应trace保留），前面的创建/只读观测/重复启动幂等/完整scope/页面往返已通过。当前专项继续8–11，镜像无菜单修复。启动包含两项产品修复及现行测试契约的完整浏览器第二轮（e2e-full-second.log）；第一轮和专项不终止，保留各自最终结果。
- 专项第8项手动Refresh/Retry、丢响应重放与Chat删除后继续推进通过。第9项真实running→完成/键盘Reload已通过，窄屏触控验收发现新资源卡Reload按钮36px、导航链接规则32px；DESIGN.md:283要求触控44×44，局部将这两个资源卡控件最小尺寸改为44。e2e-full-second在CSS修复前已开始构建，最终还需用新镜像定向重验此样式边界，不把第二轮旧CSS结果当通过。
- 首轮完整E2E结束exit1：ordinary45passed/26failed，8个隔离组6passed/2failed（Invitation旧文案与Dataset proof旧密码断言）。结果.local/e2e-runs/1789258613541-78960/results.json。Dataset完整刷新/重试/取消已到最后请求审计；当前proof发送otp，改验证6位otp只到proof且不转发mutation、不发送password，仍保留3条绑定动作及私有字段断言。
- 11项专项结束7passed/4failed（16.7分钟）：3个删除Chat处命中菜单scroll缺陷，1个触控尺寸36px。均已有修复；第二轮新镜像两个Batch已通过新增实际滚动菜单断言。
- 第二轮账户测试的新失败是旧HTTP cursor假设：HTTP list_research_runs当前签名page/page_size（MCP保留绑定cursor），旧limit/cursor被忽略且next_cursor实际undefined，原断言未验证类型。测试改为A的2页有序IDs及B页不含A IDs，保留跨资源404/草稿/幂等隔离。运行当前CSS和分页测试专项e2e-final-boundaries.log；完整第二轮handle34373继续，不能视作其旧用例通过。
- 第二轮Host restart用例已看到Core结果卡时Agent仍active=1；资源卡是独立实时读取，不能再拿旧结果组件出现当Agent完成屏障。两个恢复用例改为等待本次submitChatPrompt返回的确切Turn终态后核对数据库（复用waitForChatTurn），保留不重复准入/消息顺序断言。当前修正需定向复验。
- 最终两边界专项handle86771/e2e-final-boundaries.log进行中；镜像smoke已启动handle80422/image-smoke.log，完整第二轮handle34373继续。
- 当前分页隔离专项通过。随后A2UI专项遇到测试辅助Worker提前正常退出：前一账户用例留下合法queued工作，helper仅process_next一次并领取了其他Run，目标仍queued。process_research_run_with_barrier.py改为保持正常队列顺序处理至指定run_id进入claimed屏障，仍由现有30秒父进程超时及finally清理限定；不改产品Worker或隔离数据。两项需复验，其中分页结果本身已通过。
- 最终镜像smoke通过exit0，run_id20260913t005743z-13253-2668dd9b；run.txt全部phase（application/auth-session/health/caddy-single-origin/startup）status0，secret cleanup/diagnostic/log/raw-canary/资源清理均0。该镜像含资源卡、菜单及44px样式修复。未运行完整release qualification，不声称真实模型或线上环境已验证。
- 启动第二次最终边界专项e2e-final-boundaries-second.log，覆盖当前分页隔离、Host/provider恢复确切Turn结束、指定Run屏障及触控；完整第二轮仍在handle34373运行，当前已通过两个DailyTrack闭环。
- 第二次最终边界专项4 passed（2.0分钟），run_id20260913t010217z-16543-9044710d，覆盖当前分页、两个恢复屏障及44px触控/键盘/运行状态；退出与清理均0。
- 完整第二轮ordinary结束67passed/4failed（14.1分钟）；前三项为已由上述4项复验关闭的早期快照失败。第四项MCP断开测试读取整组Agent日志失败，捕获agent-events.jsonl=1100923字节，超过spawnSync默认1MiB缓冲。改为从本用例开始时间读取日志并保留错误原因，仍完整检查本用例私有字段不泄漏；整组raw-canary扫描由现有运行器保留。此修复尚待定向复验，未将重跑通过当作原因。

- MCP日志边界定向复验1 passed（8.4秒），run_id20260913t010840z-22976-66127d23，e2e-mcp-log-boundary.log，退出/清理0。已逐一查看最终边界专项的运行中截图、完成页及窄屏截图，资源卡显示正确阶段、按钮无横向溢出。
- Standards冻结快照/private/tmp/issue14-review-20260913，共36文件，首轮无发现。隔离Invitation继续发现测试为取消对话框也请求真实OTP，第六次触发当前5次/分钟限制；三个取消场景改填固定文本，五次实际提交保留真实OTP，未改运行时限流。此增量Standards复审无发现；Spec按串行要求开始。
- Invitation定向首个复验受沙箱回环端口分配限制，在测试执行前失败（e2e-invitations-second.log）；使用相同隔离入口在允许Docker/回环权限下继续e2e-invitations-third.log，未更改dev资源或放宽产品校验。

- 最终隔离组完成：完整第二轮7组passed，Invitation旧快照1failed；修复后Invitation单独1passed（26.0秒），run_id20260913t011544z-30343-668e60e2。最终Dataset组1passed（27.6秒），run_id20260913t011706z-32529-f1673565。aggregate .local/e2e-runs/1789260626426-4593/results.json仍如实exit1；对应失败已用定向结果闭合，不改写首次日志。79项E2E全部现行行为通过且无skip/fixme。
- 串行审查完成：issue14_standards冻结36文件无发现，取消OTP增量复审无发现；之后issue14_spec对同快照及增量无发现。审查均未委托实现；最终代码未再改动，仅更新验收结果与tracker。
- 联合门禁完成范围见14-acceptance-matrix.md。两次pnpm check失败与阶段修复保留，Core492及6个专门恢复、Auth145、Agent96、Web369、browser49、79项E2E与最终镜像smoke共同完成规定验证。没有运行真实模型/供应商、发布qualification、生产部署或main合并。
- 最终审计01–13均有独立提交与107项已勾选验收；14的8项现行验收完成，合计115项。内容/链接/差异检查通过；按既定顺序将tracker完成记录与14实现/测试证据纳入同一独立提交，提交成功后状态生效。
