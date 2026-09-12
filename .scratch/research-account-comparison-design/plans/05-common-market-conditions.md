# 05 — 本研究市场与行业共同指标：实施计划

Status: complete

前置交付：04 4e26486。继续同一隔离 worktree，保持逐票串行，不新增兼容、迁移或版本路径。

## 已定位的边界

- 共享表达式类型目前只有数值/布尔常量与股票序列；Series Plan 接收逐股字段，截面 rank 使用 Universe。共同序列必须明确独立作用域，不能复用 rank 的 Alpha Eligible 集合做统计。
- AlignedResearchData/ColumnarResearchSeries 已提供历史 universe_members 与 industries，并提供调整后 Close 字段。market_series 目前只在 industry neutralization 下装载行业；共同输入需独立触发行业依赖，不能强制用户做行业中性化。
- Data Generation 维护 SW2021 历史行业成员和治理校验；须核对正式行业目录、加载切片及准入，不能从 Benchmark 或当前行业标签补过去。

## 实施步骤

1. 核对正式 SW2021 L1 身份目录、Generation 成员可见性、Data readiness 与 Run/Batch/Track 加载入口。确定四种受限共同指标及静态行业参数语法，目录明确研究 Universe 内子集。
2. 补独立小样本失败回归：10%、−2%得4%与1/2；零收益分母、缺失/无有效成员、历史改行业、Universe 外股票和未来数据扰动。
3. 在共享表达式 Module 添加共同数值/布尔作用域与固定指标引用；校验行业身份及静态参数，声明 Close、历史成员、前一观察、工作量与来源。共同数值可广播参与 Signal，根仍需每股数值输出；不引入任意聚合或证券查询。
4. 以统一计算入口从各日期原始 Universe 历史成员构造共同序列，保留成员数、有效数与排除原因。接通行式/列式、Chunk 与 Track 冷缓存，不受 Alpha 缺失、未来标签或中性化筛选影响。
5. 联合 Warm-up、Generation 冻结身份、就绪与资源预算贯通普通 Run、Batch、Track。研究区间和选股 Universe 保持用户定义；行业参数只控制共同输入。
6. 同步 Data/Research 目录、编辑器与 HTTP/MCP 诊断/来源呈现。验证未知行业、非法参数、不可用范围的同源定位反馈。
7. 完成治理发布及真实计算链路、浏览器交互验收；Standards → Spec 串行审查，修复复审后更新 tracker 与独立提交。05 关闭前不开始 06。

## 验证记录

- 当前完成实施计划和入口定位，尚未修改共同指标运行行为，也未宣称验收通过。

- 核实 Industry Source 保存正式 SW2021 classifications 原始谱系，但当前 Generation 计算表只保存历史 l1/l2/l3 成员编码；共同输入的正式行业身份发现与准入需继续贯通。market_series 和 Generation loader 当前按 industry neutralization 条件取行业，必须拆出独立行业依赖。
- 新增 common_market 聚合公开接口与独立样本，先复现模块缺失（common-red.log），再实现按当日 Universe/历史行业选成员、前后 Close 有效性、均值/上涨占比及计数/排除原因。3 项通过（common-first.log，0.03 秒）：10%/−2%、零收益、空行业、历史变行业、Universe 外股票、缺失和未来扰动。修正测试导入排序。尚未接编译器、正式目录、Generation/warmup/加载、Run/Batch/Track及UI/MCP，不宣称票据完成。

- 根据 Tushare 官方 SW2021 分类表（https://tushare.pro/document/2?doc_id=181，2026-09-12 核对）建立31个固定 L1身份映射。采用已存成员字段使用的六位 index code，不把行业层级 industry_code 或旧 SW2014 采掘代码当作L1身份；静态整数参数精确校验，浮点/字符串/布尔/未知编码拒绝。此目录只校验身份，不证明本次 Generation 数据就绪。
- 共同数值/布尔 Series 加入共享类型规则；先复现缺类型 AttributeError（common-scope-red.log），然后实现常量→共同→股票的显式广播优先级。共同条件选择常量/共同分支仍是共同序列，参与股票分支才产生股票序列，布尔数值混用仍拒绝。共同指标与既有条件回归27项通过（common-scope-first.log，0.07秒），Ruff/diff check通过。
- 下一步固定表达式入口 universe_return()/universe_advancing_fraction() 与 industry_return(六位L1整数)/industry_advancing_fraction(六位L1整数)，接入目录、编译IR及Close/行业/前一观察的依赖。当前仅完成身份与类型基础，四个入口尚不可调用，不提前发布为已支持能力。

- 四个共同指标注册到现有 builtin 目录，编译为单一 common 引用（指标身份与规范行业编码）；隐式声明 adjusted Close、1个前置Session和固定每成员工作量。行业参数仅接受正式静态整数，不允许股票字段/浮点参数，rank仍拒绝共同序列。
- 时间窗口算子参数从股票专用改为数值时间序列，保持第一参数作用域；股票行为不变，共同均线保持共同作用域。共同节点加入冻结IR校验，禁止伪装成普通call绕过身份校验。先复现未知入口、冻结IR节点拒绝，再实现；common-ir-first.log 中35项共同/条件回归通过。修正目录长行/导入排序。
- 当前尚未接Series求值的共同上下文、独立行业加载、数据准入/来源及正式行业目录展示，因此不可宣称Run可执行；这些在本票提交前必须完成。后续需同步目录/参数类型变更涉及的旧断言、MCP schema及编辑器契约。

- 共同节点已接 Series Plan 的行式、rank矩阵和列式求值，聚合在同一矩阵请求内按行业缓存并广播；alpha入口传递历史行业。共同与条件回归36项通过（common-runtime-first.log）。
- 新增 requires_common_industry 从已验证冻结表达式发现行业依赖；准入、普通Run、Factor Batch联合依赖、Strategy Batch共享计算、Track增量/冷缓存重建/等价核对均传递独立 require_industry。仅复用已冻结分数的 Strategy执行阶段仍只加载成交事实，无需重复加载信号依赖。
- DataDependencies、market/composite/columnar loader 支持该独立依赖，未强制修改用户中性化选择。先以新依赖测试复现参数不受支持（industry-dependency-red.log），完成后既有数据读取与共同指标85项通过（industry-dependency-final.log，10.21秒）。新增嵌套行业依赖、历史行业条件行式/列式一致、三种真实本地Generation读取共19项通过（industry-runtime-fixed.log）。首轮4个失败来自测试断言把list写为tuple及既有fixture使用L1占位编码，已将样本设为正式801010并修正容器类型；不是不稳定重跑。Ruff及git diff --check通过。
- 新发现必须修正的成员边界：market_series 的 universe_members 已按当日Open/成交额筛选，Columnar _UniverseMembers也有该筛选；共同指标不能直接复用。下一步保留原始历史Universe成员作为明确的共同计算输入，贯通切片、Batch与身份；行业映射也应覆盖原始成员。新增零成交但Close有效、缺Open但Close有效样本，验证不会被Alpha/成交资格提前排除。当前实现仍复用筛选后成员，因此本票尚未验收，不提交。
- 仍待完成：原始成员口径、计数/排除原因来源落地、正式行业目录及UI/MCP、预算中行业静态literal节点一致性、公共schema/旧catalog断言更新、Run/Batch/Track真实链路与浏览器、串行Standards/Spec审查。

- 已修正原始成员边界：AlignedResearchData/ColumnarResearchSeries 明确新增必需 historical_universe_members；Data loader 从原始 Universe Membership 保留它，行式行业映射覆盖该集合。切片、输入身份、Batch共享包装透传该集合；测试fixture显式声明，无旧输入兼容或运行时回退。
- 共同Series求值独立要求 historical_universe_members，rank及Alpha资格仍使用原有筛选后成员。列式共同计算的证券轴取历史成员，防止整段零成交股票在加载Close前就被移除。
- 先复现缺少历史成员属性（historical-universe-red.log），完成基础后56项通过（historical-universe-first.log）。本地Generation样本验证B全段成交额零但Close有效仍参与共同收益，A才是可选股；行式/列式及切片一致（historical-generation-fixed.log）。首轮样本只修改调整后Close导致治理校验拒绝，已保留原有完整合法价格链，只改成交额，用独立精确预期22/21验证，没有放松校验。
- 当前受影响Alpha、Factor、Chunk、数据读取与共同指标179项通过（historical-universe-regression.log，13.45秒），Ruff/diff检查通过。这些是本地数据Generation及Kernel验证，不代表HTTP/MCP、Worker/Track或浏览器链路已验收；后续仍需执行本票约定的真实链路与串行review。

- 作者目录增加有界31项 industries（正式整数code与中文name），沿现有Alpha catalog提供给HTTP/MCP消费者，目录身份不冒充Generation就绪。Data页添加共同输入及真实Universe子集说明、参数目录；Research编辑器提供编码/中文名补全。更新当前前端fixture契约，不增加旧catalog兼容。
- 新目录回归先复现industries缺失（common-catalog-red.log）。73项共同输入/语言契约通过（common-catalog-fixed.log，0.40秒）。修复temporal_series拒绝路径遗漏结构化expected/actual，现明确接受stock/common数值序列；普通builtin非有限值测试不再对需要治理上下文的common入口直接调用标量evaluator。
- Data/Research相关37项组件测试通过（common-catalog-web.log，3.44秒），Web typecheck通过（common-catalog-typecheck-final.log）。Data测试检查Universe子集说明、编码名称及数据范围仍需校验。
- 实际浏览器验证发现数字编码补全会将801拼成801801010（common-catalog-browser-fixed.log）；保留失败证据并修正token替换范围支持数字。实际编辑器补全与原条件语法2项通过（common-catalog-browser-passed.log，4.2秒）。此前首轮Control-Space是测试快捷键写法错误，改为Control+Space后才发现上述真实产品问题。
- 本票仍未完成：共同统计的成员数/有效数/排除原因结果来源、IR静态行业literal资源核算、HTTP/MCP schema与范围诊断真实验收、普通/Batch/Track共同条件Worker链路、Data页面真实浏览器及串行Standards/Spec审查。当前05维持in-progress，尚未提交，06未开始。

- 修正行业静态参数的资源核算：源码编译原先绕过literal递归深度检查，冻结IR原先也没把metadata形式的行业literal计入节点/深度。先复现30层abs+industry literal越界却未拒绝（common-resource-red.log），修复后共同输入/语言77项通过（common-resource-final.log）。独立验证深度32成功/33拒绝、256节点成功/259拒绝，源码与冻结IR都检查，无放宽预算。
- 检查MCP契约发现AlphaCatalogView分页重新组装时丢掉新industries；新增registry回归复现缺属性（common-mcp-catalog-red.log），补上有界31项正式目录映射。Agent与作者目录一致；合法行业、旧行业/动态参数/多余参数诊断同源且含位置。当前MCP契约44项通过（common-mcp-contract-fixed.log，3.93秒），同步实际公开schema指纹和字节数到既有证据文件；未新增版本/兼容接口。
- 本轮Ruff与diff check通过。结果来源计数尚未贯通：现有CommonMarketSeries已返回逐Session计数/原因，SeriesPlan目前仅取值数组；后续需传到Alpha session/Chunk及结果读取，避免丢失排障证据。Kernel compose_output已有diagnostics.alpha_coverage；ResearchRun公开provenance目前仅身份，需选明确适当结果路径，不能把逐股快照永久保留或忽略本票返回统计要求。

- 共同统计通过可选typed observer从SeriesPlan同一次聚合返回，避免为解释重复计算；重复引用相同共同指标只记一次。Alpha每个使用共同输入的Session记录identifier/industry_code/value/member_count/valid_count/exclusions，普通无共同输入Session不附加无意义记录。行式和列式保持同一数据来源。
- 本地Generation样本先复现计算结果丢失common_inputs（common-observations-red.log），接通后返回精确共同收益44/483、成员2/有效2，以及首Session insufficient_history=2（common-observations-first.log）。
- Chunk专门测试复现压缩时丢失common_inputs（common-observations-chunk-red.log），修正pending Alpha压缩/展开保留副本，批量compact复用往返完全一致；kernel compose_output diagnostics也透传。修复定向通过（common-observations-chunk-fixed.log），相关Alpha/Factor/Chunk/数据与共同/条件回归204项通过（common-observations-regression.log，11.64秒），Ruff/diff check通过。
- 统计目前保存在计算matrix和Chunk产物，尚未完成ResearchRun正式发布与读取。下一步入口：research_run/result.py 的 row/columnar payload构造、staged payload finalize与read_result_section，result_schema.py耐久模型/表定义，service.py完成时结果provenance与数据发布；须有正式可查询结果与来源显示才算本票完成，不能拿中间产物存在代替产品交付。后续DailyTrack和Batch也需共享同一输出路径，严格保留本票及后续ticket存储边界。

- 正式结果路径当前按Research Kind严格校验payload集合；staged发布从 Worker final_values和Strategy observation partitions组合，不能直接把任意diagnostics塞进已有summary。已开始在result_schema/result明确共同统计契约，尚未声称发布完成。
- CommonInputObservation验证正式指标/行业身份、有限值、member_count=valid_count+排除数、有效样本与missing值一致、上涨占比范围、已知排除原因与严格数值类型。先复现模型缺失（common-result-contract-red.log），12项样本/拒绝行为通过。
- common_input_observation_rows把Alpha matrix按本Chunk实际Research Sessions转成经过校验的结果行，排除warmup和先前pending Session；拒绝重复指标/日期和缺失日期。先复现转换入口缺失（common-result-rows-red.log），13项通过（common-result-rows-first.log）。此转换函数尚未接Worker发布与公开分页，属于本票进行中的实现，不能把模型存在视为功能验收。
- 后续必须接通：Run/Batch逐chunk输出共同observation行、已有staging/publication分区和恢复语义、结果读取section及来源/前端；Track使用新Advance固定Generation并复用结果契约；随后完整本票验收与Standards→Spec审查。不要修改01–04完成状态，不开始06。

- 共同统计分区已复用现有Canonical Parquet Writer实现写入/读回，保留Session、指标身份、行业、nullable值、样本数与四种已知排除原因。存储industry_code用空串明确编码Universe范围（公开语义仍None），因为既有writer禁止nullable排序键；首轮由该约束直接拒绝（common-result-parquet-first.log），未放宽writer或增加兼容分支。
- 先复现未提供Parquet入口（common-result-parquet-red.log）；实现后真实字节往返验证共同Universe/行业空样本、null值、计数与原因。读回按当前Schema和必填值校验，拒绝错误行业/计数、重复或乱序身份；写入输入排列不同产生完全相同字节。共同与已有Result Bundle契约43项通过（common-result-parquet-regression.log，0.81秒），Ruff/diff通过。
- 尚未连接的关键生产路径再次确认：ResearchChunkCalculation目前只给strategy_daily_observations；research_run/execution.py子进程chunk envelope对字段集合严格校验；service.py约3150行接收chunk、约3263行发布checkpoint，约3114行拼staged partitions；Batch Factor和Strategy有独立完成路径。下一步必须同步这些当前契约，不能只加codec后宣称Run已发布共同统计。完成后还需result section/API/MCP/UI、Track与真实验收，再串行review与05提交。

- ResearchChunkCalculation新增明确common_input_sessions，Warmup为空；正式Chunk从Alpha结果只提取当前Research Sessions的共同统计，不携带逐股values、不重复pending日期。先复现缺属性（common-chunk-output-red.log），实现后17项Chunk测试通过（common-chunk-output-first.log）。
- 普通Research Worker将这些Session经共同结果校验转换成common_input_observations，纳入当前子进程严格envelope；纯Warmup和已完成checkpoint重用消息携带空列表，后者后续发布须从已存checkpoint恢复，不能因此丢失原数据。未增加旧消息fallback。
- 初轮Worker内存生命周期回归暴露已有Fake缺alpha_expression及新common_input_sessions；更新最小当前fixture契约，保留弱引用断言验证yield前释放数据。Worker生命周期、Chunk及共同结果测试35项通过（common-worker-chunk-fixed.log），Ruff/diff检查通过。
- 仍未接收持久化：service._record_chunk附近目前仅staging strategy observations，checkpoint binding/SQL observation_payload及恢复/完成分区拼装也仍只认识旧业务字段。下一步必须把共同payload纳入同一受验证checkpoint链、完成发布、Batch路径和分页读取；这些尚缺，当前05不可验收或提交。

- 新增common_input_references统一遍历冻结表达式并去重，requires_common_industry复用它。Checkpoint接收前验证共同记录精确覆盖冻结共同输入×本分块Research Sessions，拒绝缺失/多余/重复日期及指标；先复现缺函数（common-checkpoint-coverage-red.log），相关共同/结果39项通过（common-checkpoint-coverage-first.log）。
- 当前schema的execution_checkpoints新增nullable common_observation_payload引用与JSON类型约束；仅修改隔离worktree代码，未对dev/prod执行SQL、迁移或指纹绕过。Checkpoint记录将共同Parquet分区staging并纳入出版payload、checkpoint binding/hashchain和同一事务INSERT；恢复重读分区，校验writer合同、数据模型、冻结身份及研究日期覆盖，缺失分区不能作为无数据继续。
- 新代码纯单元/Worker生命周期/Chunk与结果回归36项通过（common-checkpoint-regression.log，2.79秒），Ruff/diff通过；尚未运行新schema的真实数据库checkpoint写入/故障恢复，所以不得宣称持久化链路验收通过。需要检查隔离初始化schema约束及执行原有真实验收。
- 后续仍必做：最终Result拼装共同分区及schema精确payload名单、分页Result section/API/MCP/UI、Batch独立完成路径、DailyTrack；完成本票真实链路及串行审查后才可05提交。下一轮优先继续实际发布路径和数据库验证，不能停留于单元绿灯。

- 已使用既有TestRun/integration隔离运行器做实际数据库+对象存储+HTTP/Worker/Track回归：.local/test-runs/issue-05/checkpoint-integration.mjs仅选择one_session_cash_account两项，明确跳过restart阶段，不把它称为故障恢复验收。Docker 29.4.0可用，测试项目thesistrace-test-20260912t111036z-95131-d11e51f8；当前schema初始化与checkpoint写入完成，2 passed/472 deselected（pytest 21.01秒），进程退出0，测试容器/数据卷/网络已清理。
- 日志checkpoint-integration.log；权威报告.local/test-runs/20260912t111036z-95131-d11e51f8/evidence/pytest.xml。测试期间未改被测源码，未启动重复测试。两项使用close及04条件公式，不含共同输入，故只证明新schema和空共同checkpoint契约不破坏现有Run→Result→Track闭环；仍需共同输入的实际分区保存、重读/恢复及最终结果专门验收。
- 下一步优先最终发布：result_publication_payloads_from_staged需接共同分区描述；_prepare_execution_result从checkpoint收集引用；read_result_bundle/read_semantic_result_section和精确payload名单需支持对应当前结果。普通/Batch/Track不能各自创造口径，最终还要受结果字节预算与分页约束。05未完成，继续。

- 最终Result可接收共同Staged Parquet partitions并发布独立common_input_observations描述及分区。描述检查格式、writer、稳定顺序、行数/日期边界；完整Result读取验证实际数据与描述一致，Factor和Strategy精确payload名单均识别共同分区。无共同输入不写空物理产物，这是当前能力按需输出，不是多版本兼容。
- 普通Run _prepare_execution_result从checkpoint的common_observation_payload读取已保存引用，依据冻结共同身份数及Chunk实际Research Sessions生成分区描述，不重新计算历史指标。Result Bundle继续走现有字节预算。先复现staged共同参数不支持（common-final-bundle-red.log），编解码和共同结果45项通过（common-final-bundle-regression.log，0.71秒）。
- 已新增并运行真正包含共同表达式的隔离验收test_common_statistics_publish_from_checkpoint_to_completed_result：HTTP提交close * universe_advancing_fraction()、真实Worker、数据库checkpoint、对象存储最终Result读取；冻结Generation一致，返回恰好3个研究Session、不含warmup，完整成员/有效数和原因符合预期。1 passed/474 deselected（pytest 5.41秒），运行器退出0并清理全部测试资源；项目thesistrace-test-20260912t111719z-96983-6614c212。日志common-publication-integration.log，权威报告.local/test-runs/20260912t111719z-96983-6614c212/evidence/pytest.xml。期间未修改被测源码；测试后只修正新增测试导入排序。
- 本票未完成项仍包括共同结果分页section/HTTP/MCP/UI、Batch的Factor/Strategy独立完成路径、DailyTrack统计结果、共同输入checkpoint故障恢复与范围诊断、完整相关回归及Standards→Spec审查。真实普通Run发布通过不能替代这些边界。05仍in-progress，未提交，06未开始。

### 2026-09-12 — Common observation result paging

- Added `read_common_input_observation_page`: cursor orders by Session, identifier, industry identity, so multiple metrics on the same Session are not dropped. Reads only required partitions plus lookahead, validates Parquet encoding/count/bounds, skips completed historical partitions.
- Added current `common_input_observations` ResearchRun semantic section for Factor and Strategy; no-common formulas return an empty collection based on the frozen expression. Common formulas require their published descriptor rather than silently returning empty on missing payloads. Reused encrypted owner/run/manifest/section-bound cursors and `fit_page` response byte bounds.
- MCP current schema now has seven Run sections and three collections. Measured canonical schema SHA-256 `da1394e71b21ee42251bc81f32a92de1a7d31fc9f8d58a939beb78635db41873`, 147937 bytes; updated current contract fixture and benchmark evidence. No compatibility contract added.
- Red/green: new same-session pagination test first failed due to missing reader; implementation passed. Initial MCP contract checks exposed the changed schema fingerprint and section/collection inventory; updated those exact current-contract expectations. Final result/MCP/HTTP contract suite: **106 passed**, `.local/test-runs/issue-05/common-page-contract-fixed.log`. Result-only suite: **49 passed**, `.local/test-runs/issue-05/common-result-page-regression.log`.
- Actual isolated DB/Worker publication + service pagination: **1 passed, 474 deselected**, 8.72s; runner exit 0 and resources removed. Project `thesistrace-test-20260912t112713z-99540-2d866a81`, log `.local/test-runs/issue-05/common-page-integration.log`, evidence `.local/test-runs/20260912t112713z-99540-2d866a81/evidence/pytest.xml`. This is service pagination on actual Worker-published data, not yet a native MCP call against that completed Run.
- Still outstanding: Batch/Track common observation publication and queries, native MCP common-result acceptance, user-visible result scope/evidence, industry readiness real acceptance, retry recovery, serial Standards/Spec reviews, tracker completion, independent commit. Do not start 06.

### 2026-09-12 — Batch common observation publication

- Factor Batch now emits each item's common observations per shared research window. Strategy Sweep reads the same observations from its immutable Alpha artifact, including reuse, without reloading Alpha source columns. Added a compact common-session accessor rather than copying the complete stock score matrix.
- Added current child message `item_common_input_chunk_succeeded` with the existing progress acknowledgement. Parent validates item identity, sequential window ordinal, exact frozen metric identities and Session coverage; stages each window as the existing common Parquet contract. It retains only staged references and publishes them with each completed child Run. Batch completion independently rejects incomplete partition coverage; no-common items have no common partitions.
- Red/green: both new stream tests initially returned no observations. During implementation an insertion landed in the shared prerequisite block and was corrected; strict row projection also required an explicit list and skipping the projection for formulas without common inputs. Final kernel/protocol/chunk/result regression **75 passed**, 10.40s (`.local/test-runs/issue-05/common-batch-chunk-regression.log`); Ruff and `git diff --check` passed.
- First real isolated Batch test failed at admission because existing fixtures began at the research start and lacked the common return's previous Session (`.local/test-runs/issue-05/common-batch-integration.log`, 2 failed). Added 2026-07-31 to the explicit test Generation and direct admission response assertions; did not change production readiness policy.
- Real rerun **2 passed, 475 deselected**, 14.52s, runner exit 0; isolated project `thesistrace-test-20260912t113620z-3215-b846fc2e`, resources removed. Log `.local/test-runs/issue-05/common-batch-integration-warmup.log`, evidence `.local/test-runs/20260912t113620z-3215-b846fc2e/evidence/pytest.xml`. Factor Batch checks common observations equal ordinary Runs under the frozen Generation; Strategy Sweep compares complete Result values including common observations against ordinary Runs and exercises starting a Track from its result.
- Remaining: Track must persist/query newly appended common observations (starting a Track alone is not that proof); native MCP completed-result call, frontend result scope/evidence, industry readiness and retry recovery acceptance, serial reviews/tracker/commit. 05 remains in progress; no 06 work.

### 2026-09-12 — Track appended common observations

- `project_tracking_checkpoint` now stores required `common_input_observations` for only the Advance's retained Sessions. The typed current Checkpoint contract verifies exact identity/date coverage against the frozen expression and retained Strategy delta; it rejects missing/duplicate/out-of-order observations. No stock-by-day score matrix is retained and the seed Run history is not copied into each Advance.
- Moved the shared `CommonInputObservation` model and row projection to `research_kernel/common_observations.py`; Run, Batch and Track consume that definition. A direct Track import from ResearchRun caused a package initialization cycle in the first implementation; moving both shared pieces removed the dependency cycle. All current imports changed directly; no alias/old-contract adapter added. Projection raises `CommonInputObservationError`; publication-specific validation still uses `ResearchResultError`.
- Red/green: new common-input Track test initially failed because Checkpoint lacked observations. It now compares row/columnar checkpoints across three advancing/recovery boundaries, asserts only appended dates are retained, and verifies typed Checkpoint rejection of incomplete statistics. **5 checkpoint/recovery cases passed** (9.84s); **41 advance/common/Batch/Worker lifecycle tests passed** (29.02s), `.local/test-runs/issue-05/common-track-shared-regression.log`. Shared-model/MCP/HTTP/result regression **106 passed** (4.04s), `.local/test-runs/issue-05/common-shared-model-contract.log`; current MCP schema unchanged by the module move.
- Real isolated Run → start Track → manual Refresh → tracking Worker → read immutable Checkpoint: **1 passed, 476 deselected**, 13.67s, runner exit 0. Project `thesistrace-test-20260912t114315z-5472-321c0e55`, all resources cleaned. Log `.local/test-runs/issue-05/common-track-publication-integration.log`; evidence `.local/test-runs/20260912t114315z-5472-321c0e55/evidence/pytest.xml`. Confirms the appended last Session's valid/member counts and metric identity are published.
- Next: Track semantic common-input pagination must combine seed Run data and selected immutable Checkpoints using the existing snapshot-bound cursor, and retain same-Session metric/industry ordering. Existing `_get_result_section`/`_bounded_strategy_observations` in `daily_track/service.py` and `session_coordinates.load_read_snapshot` are the current bounded read path. No Track common-input section is advertised yet. Frontend evidence/native MCP/industry/recovery qualification and serial reviews/tracker/commit also remain. 05 is incomplete; do not start 06.

### 2026-09-12 — Track common-input pagination

- Added current `common_input_observations` Track section, typed request/response, and catalog inventory. It reads seed Run statistics through the existing semantic reader, then immutable appended Checkpoints. No-common strategies return an empty collection from their frozen expression.
- Reused the existing encrypted researcher/Track/section/snapshot-bound cursor and `fit_page` byte limit; order is Session, metric identifier, industry identity. SQL checkpoint selection starts before the cursor date so a second metric on the same checkpoint boundary date remains readable. Only page-sized checkpoint metadata is loaded; payload reads stop after lookahead. Overlapping or unordered observations are rejected. A newer Track Head continues to invalidate stale non-origin cursors under the existing contract.
- Updated `SemanticResultSectionReader` protocol for explicit `has_common_inputs`; no compatibility fallback or new version. Current MCP inventory: five Track sections, three Track collections. Canonical schema measured SHA-256 `8b46196bcc587f34f354b0ec5bd15b1d17970db5bb5530fd163859725bbf7e2e`, 150402 bytes. Current contract and benchmark fixtures updated. **57 MCP/HTTP contract tests passed** (3.91s), `.local/test-runs/issue-05/common-track-page-contract-fixed.log`.
- Real isolated single-metric cross-Run/Track pagination passed first: project `thesistrace-test-20260912t114746z-6891-e16ce233`, **1 passed, 476 deselected**, 7.94s, `.local/test-runs/issue-05/common-track-page-integration.log`.
- Added explicit two-metric same-Session coverage. Final real Worker/DB service pagination suite **2 passed, 476 deselected**, 14.86s. Project `thesistrace-test-20260912t114924z-7546-fe33154e`, log `.local/test-runs/issue-05/common-track-page-multiple-integration.log`, evidence `.local/test-runs/20260912t114924z-7546-fe33154e/evidence/pytest.xml`. Both cases paginate one record at a time across seed and appended observations and compare the complete returned sequence. Runner exit 0; containers/volumes/network cleaned. Ruff and `git diff --check` passed.
- Remaining for 05: native MCP calls against actual completed Run/Track, frontend result scope/statistics display and browser acceptance, industry readiness/future/history/recovery coverage audit, serial Standards then Spec review, fixes/review/tracker/commit. Ordinary/Batch/Track publication and service pagination now have real evidence, but this is not completion of the ticket. Do not start 06.

### 2026-09-12 — Native MCP and web common-input evidence

- Extended the real completed-Run/Track acceptance to launch the actual stdio MCP executable via the existing `_mcp_client` helper. Both `get_research_run_result` and `get_daily_track_result` page one record at a time and reproduce the complete published sequence, including two metrics on a Session. First native run **2 passed, 476 deselected**, 27.92s; project `thesistrace-test-20260912t115205z-8633-2ec0f607`, `.local/test-runs/issue-05/common-native-mcp-integration.log`; exit 0 and resources removed.
- Added authenticated web GET routes `/api/research-runs/{run_id}/common-input-observations` and `/api/daily-tracks/{track_id}/common-input-observations`, using the same typed service queries/results as MCP. Explicit invalid/stale cursor, unavailable result, transient/read failure, and missing owner/resource responses; page size stays 1–50. No duplicate calculation path.
- Added shared `CommonInputObservations` component to succeeded Run details and Track supporting details. Closed by default, abortable fetch on expand, bounded Previous/Next pages, failure/reload-first-page state. Shows historical research Universe scope, SW2021 L1 subset identity, adjusted-Close metric meaning, valid/member counts, exclusions, zero as `0.00%`, missing as `—`. No eager full-history fetch. Uses existing design tokens/dense dark styling.
- New real browser component tests bundle the actual component and intercept fixture HTTP responses; **2 passed** (3.8s), `.local/test-runs/issue-05/common-input-browser.log`. Covers no fetch while closed, zero/missing values, industry identity, excluded count, page navigation, error vs empty state, retry. Screenshot `.local/browser-tests/common-inputs.png` inspected visually. This is component browser evidence, not an authenticated full-app E2E.
- Web typecheck passed; existing Run/Track page regressions **36 passed**, `.local/test-runs/issue-05/common-input-web-regression.log`.
- Final real API/MCP/Worker run adds HTTP success, invalid cursor 400 and oversized page 422 assertions: **2 passed, 476 deselected**, 27.41s; project `thesistrace-test-20260912t115937z-11596-f5fb4389`, `.local/test-runs/issue-05/common-web-http-integration.log`, evidence `.local/test-runs/20260912t115937z-11596-f5fb4389/evidence/pytest.xml`; exit 0 and resources removed. Ruff and `git diff --check` passed.
- Auto-review rejected one combined test-generation command, interpreting its read-only template extraction as destructive modification of the original conditional test. No part of that rejected command executed. Added new fixture/spec with explicit `apply_patch`; original `conditional-alpha.spec.ts` SHA-256 remained `8d7908ca38622e827ca1d70d7fb5c87664f7e57edb81a985f8e0c64815dc97a4` before/after. Browser execution subsequently approved. No unresolved approval blocker.
- Next: requirement-by-requirement 05 audit, especially actual industry readiness and common-checkpoint retry recovery evidence; resolve missing checks, then serial Standards/Spec reviews, repairs/re-review, tracker and independent commit. No review has started yet; 05 remains uncommitted and 06 has not started.

### 2026-09-12 — Industry admission and publication recovery

- Common industry formulas now validate historical industry readiness over their compiled calculation lookback, independently of neutralization. Rejections identify `formula` and its source range; plain industry neutralization retains its existing requested-period check.
- Added a regression that first failed on missing rejection, then passed after the admission correction. Combined common-input/admission tests: **23 passed**, `.local/test-runs/issue-05/common-industry-coverage-regression.log`.
- Added an explicit formal `801010` industry fixture and transient result-publication fault. Real acceptance confirms checkpoint reuse, recovered industry statistics, appended Track statistics, HTTP and native MCP pagination, and unavailable-industry formula admission diagnostics.
- Isolated run **2 passed, 477 deselected**, 14.61s, exit 0; project `thesistrace-test-20260912t120652z-13498-8faa8de0`; containers, volumes and network removed. Evidence `.local/test-runs/issue-05/common-industry-recovery-integration.log`.
- Full fast checks started before serial reviews. Ticket 05 remains in progress and uncommitted.

### 2026-09-12 — Fast-suite findings before review

- First `pnpm test`: **50 failed, 1286 passed**, 121.43s. Most failures were sandbox-denied loopback binds in test-runner fixtures; two Core HTTP/probe tests also require local ports. Log `.local/test-runs/issue-05/quick.log` retains the original errors. No development stack was used.
- Actual defects: the static industry catalog lived under `data`, causing kernel imports to load infrastructure and violate layering. Moved the sole catalog to `research_kernel/industry_catalog.py` and updated callers directly; no alias or relaxed kernel boundary.
- Updated current catalog/result-section fixtures and HTTP route inventory, and supplied the Batch lifetime fixture's frozen expression. The graph test also exposed the already-committed Initial Cash authoring dependency on the pure kernel numeric limit; declared that legitimate inward dependency, retaining cycle validation.
- First focused rerun: **47 passed, 2 failed, 1 deselected**; remaining failures identified the authoring edge and trajectory result-section fixture, now corrected. Full fast suite is rerunning with loopback access. No review or commit yet.


### 2026-09-12 — Final verification and serial reviews

- The first loopback-enabled retry stopped at Ruff import ordering after the industry catalog move; corrected that import ordering. Final `pnpm test` exited **0**: **1336 Core**, **648 Agent**, **200 Auth**, **361 Web** tests, plus **29 tooling** and **11 evaluator-preflight** checks; typechecks passed. Log `.local/test-runs/issue-05/quick-fixed-imports.log`. Core emitted one existing forkpty deprecation warning; Web emitted fixture socket diagnostics but all assertions passed. This is deterministic engineering validation, not real-model quality evaluation.
- Independent fixed-snapshot Standards review: **0 findings**. Independent Spec review, run after Standards: **0 findings**. Snapshot `/private/tmp/thesistrace-issue05-review-20260912`, reports `standards-report.md` and `spec-report.md`; reviewed working tree against `4e26486`, including untracked files. Source stayed unchanged throughout both reviews.
- Standards confirmed historical-member semantics, pure Kernel boundaries, immutable bounded storage, owned pagination, HTTP adapters and existing frontend design. Spec confirmed all ticket05 criteria, including governed identities, warm-up, consistent Run/Batch/Track calculation, diagnostics and published evidence. Both are static reviews and do not replace recorded runtime checks.
- Browser evidence covers the actual editor industry completion and actual common-input component interactions. Real isolated API/Worker/database/storage/native-MCP acceptance covers publication and retry recovery, ordinary/Batch/Track consistency and paging. No full authenticated browser E2E or deployment is claimed for this ticket.
- All eight acceptance items checked. Preparing the independent ticket05 commit; ticket06 has not started.
