# 02 — 接入 daily_basic 的 16 个 DSL 入口

**What to build:** Researcher 能在同一个 Market data 区块发现并使用估值、股本、换手和原始收盘价字段；这些值由 Market Refresh 持续采集，按正确交易日进入统一 Data 读取和研究执行。

**Blocked by:** 01 — 统一现有字段目录、准入和家族合同

**Status:** complete

**Execution contract:** 在从 main 创建并核实的新 worktree 中，严格按 01→08 串行执行。每票开始实现前先记录 Plan；完成实现后逐项验收，进行代码审查、修复及复审，更新 tracker 并形成该票独立 git commit，完成后才开始下一票。审查同样串行，不并行委派实现或审查。

**Latest user decision:** 按用户最新要求，直接实现当前合同，不做兼容、版本迁移或 vXX 升级链；这覆盖母规格中有条件引入迁移的旧提议。保留数据、原有字段语义与必要研究引用的要求继续有效，不将“不迁移”解释为允许清库。

**Execution order:** 02；必须先完成 01 的验收、复审、tracker 更新和独立提交。

- [x] 按权威 226 清单接入 close_raw、total_mv、circ_mv、total_share、float_share、free_share、turnover_rate、turnover_rate_f、volume_ratio、pe、pe_ttm、pb、ps、ps_ttm、dv_ratio、dv_ttm，共 16 个作者入口。
- [x] equity.daily_basic 承载 15 个新指标；close_raw 只绑定既有 price.close.raw 身份，使价格家族为 7 项、Market 总目标为 22 项。daily_basic.close 保存作来源核对；差异有证据，不逐行换源补价，不改变复权 close。
- [x] 显式采集 daily_basic 的 19 个来源列，沿用历史证券身份和 Research Calendar，支持期间内退市股票。按交易日分片；达到 6000 行上限时继续拆分或验证受支持的取全方式，不能将可能截断的结果记为完成。
- [x] 有界真实来源资格证明每列的金额、股数、比率或倍数单位。换手率、股息率按已核实比例转为 DSL 小数，已为小数的来源不重复缩放，PE/PB 不除以 100；原始响应与规范化证据保留。
- [x] 按股票和交易日精确读取，缺日或缺值保持缺失，不前向填充；只用于收盘后的信号计算，不用于同日开盘决策。历史估值不宣称具有完整分母修订链。
- [x] Market Refresh 同时维护价格与每日指标的独立来源完成度、覆盖和重试检查点。无权限、限流、超时、缺列或截断不能被价格刷新成功掩盖，也不能丢弃旧历史；在固定数据上证明中断恢复可收敛。
- [x] 发布该家族及后续 Market Refresh 都保留非目标家族和各自真实覆盖，使用已有单一 Dataset Head、Operator 权限与生命周期保护，不新增独立发布入口或 Head。
- [x] Data 页在现有 Market 区块显示实际可用数量、来源状态和字段说明；搜索、补全、HTTP/MCP、Agent 能查询这些字段。指标未就绪时依赖它们的公式被拒绝，仅依赖价格的研究仍可执行。
- [x] 在同一冻结 Generation 上，从统一读取到 ResearchRun、Batch、DailyTrack 的值和日期对齐一致；研究执行禁用供应商网络仍可完成，仅读取所需列。
- [x] 演示一次有界采集或 Replay、候选验证、隔离发布、混合价格/估值公式提交和下一次刷新，证明字段仍可用。完成本票相关的来源、公开模块、真实存储/Worker、合同和页面验证。

**Verification:** 母规格 T01、T02、T08、T09、T10、T11、T15。完整历史范围由 07 汇总验收；本票完成可运行采集与研究链路及有界来源资格，不单独上线。

## Comments

- 2026-09-12：用户确认发布工单。已纳入最新的串行执行、每票 Plan / 验收 / 审查修复复审 / tracker / 独立提交，以及不兼容、不做版本迁移的要求。

## Plan — 2026-09-12

前置 01 已在隔离 worktree 完成验收和串行复审，独立提交 `18f1ee9`。本票继续同一 worktree，03—08 不开始。

1. 核实权威清单及已保存真实 daily_basic 来源证据，定义 19 列来源合同、15 列规范值及精确 Session 对齐；close_raw 复用价格原值。优先对单位、空值、截断与来源记录验证建立公开入口测试。
2. 扩展现有 Market Refresh 采集和持久化：独立保存 daily_basic 分片完成/失败与原始证据，历史身份包含退市证券；按日达到上限时按证券拆分并验证边界，不假定分页可用。价格成功不得掩盖指标失败。
3. 构建和读取 daily_basic 家族，接入当前统一目录、准入与研究读取；按需读取、精确日期、缺值不填充。候选组合及后续刷新保留非目标家族，不增加 Head、迁移或版本分支。
4. 同步 Replay、HTTP/MCP/Agent 和 Data 既有 Market 展示，以混合价格/估值公式验证 Run、Batch、Track 的冻结输入一致性；保存有界真实来源资格。
5. 运行受影响公开模块、真实存储/Worker 和浏览器验收；按 Standards → Spec 串行审查，修复后复审，逐项更新本票并独立提交。全部验收完成前不标 complete、不进入 03。

风险边界：现有市场采集按整日保存四类事实；接入第五类时必须保持各来源可恢复证据，不能只把 daily_basic 附加到一个整体成功标记。现有 Generation 与来源记录按自身声明读取，不能为了新字段补写历史根。

## Source collection progress — 2026-09-12

- 已核对官方 daily_basic 文档（https://tushare.pro/document/2?doc_id=32）及既有真实探针；当前文档说明单次最大 6000 行。新来源合同显式请求 19 列，日期与更新状态不计入 15 个数值指标。既有探针证明 19 列返回，不足以单独证明全部单位与历史完整性。
- 新增有界来源采集入口：按交易日查询，达到上限则按已知历史证券逐股重新查询同一天，不使用 offset/limit 假定取全。缺列、重复身份、非请求日期或未知证券拒绝；原始空值保留。
- 来源公开入口测试先因模块缺失失败（exit 2），实现后 6 passed / 0.17s，Ruff 通过。包含实际 6000 行边界及逐股拆分结果验证。测试进程 70832、77142 均已终态，不再轮询。
- 这只是 02 的首个实现步骤，尚未接入 Market Refresh 持久化、独立分片检查点、单位规范化、Generation 读取和研究链路。拆分原始请求证据及可恢复检查点需在接入阶段保存，不能将当前方法返回的合并响应冒充逐请求证据。本票未验收、未 review、未提交，保持 ready-for-agent；03—08 未开始。
- 下一步先读 Market Refresh 的 Source/Bootstrap/Candidate 入口，接入独立来源证据与日分片完成度，再实现规范化与统一家族读取，避免只注册字段却没有数据。

## Resumable source evidence and units — 2026-09-12

- DailyBasicCheckpoint 使用现有 AddressedFileStore 保存不可变请求回执，包含来源列、原始值、请求范围和观察时间。同一次 collection_key 重开已完成请求不联网；新刷新 key 重新观察重叠日期。整日达到上限的回执仅是截断证据，不代替逐证券分片完成。没有引入版本或迁移链。
- 恢复测试先 4 failed / 6 passed，实现后 10 passed；证明失败日期不抹除上一日证据、次次刷新观察隔离、损坏回执拒绝且不静默重取。首次 Ruff 两项行长失败已修复并通过。
- 新增只读资格脚本 qualify_daily_basic.py 与 daily-basic-unit-qualification.json：600519.SH、000001.SZ 在 2018-07-26、2026-09-09 共 8 次 daily_basic/daily 请求。四个样本均通过原始收盘价一致、市值/股本单位及两种换手率百分数尺度的交叉核验。该证据仅覆盖这些样本，不能宣称历史采集齐全。官方文档提供股息率百分数、每股/倍数等其余单位定义。输出未包含 token；配置只读，未改生产数据。
- normalize_daily_basic 已实现元/股/小数比例转换，倍数保持、空值不填充，缺行不生成记录。source_close 仅是来源核对值，不能作为 close_raw 的替代来源。非法数字/NaN/Infinity 拒绝。新转换测试先 5 failed / 10 passed，实现后全部 15 passed / 0.15s，Ruff 通过。
- 当前进程 41490、77856、87590、41034 均已终态；68457 也已收取终态 exit 1（转换实现前 5 failed / 10 passed），相关失败已由后续 15 passed 覆盖。
- 未完成的下一步：将来源入口接入 TushareDataSource 和现有 Operator 的 operation 身份；独立 checkpoint 目录须纳入来源引用/生命周期。为规范化数据增加当前 daily_basic 家族、按日期的 nullable 数值存储与按需 Series 读取，再接入刷新/Replay/研究验收。不得把未接入的源适配器当成 02 已完成。

## Generation and Series integration — 2026-09-12

- 已将 15 个每日指标注册到同一 Field Catalog，规范金额/股数/比例单位及中文用途；第 16 项 close_raw 绑定原 price.close.raw，只读 eod_prices.close_raw。行情目录按 Canonical ID 去重，未引入供应商 DSL 别名。
- 新增 daily_basic 的 nullable decimal Parquet 表及 daily_basic_sessions 采集日期表，复用当前家族/表/对象格式。家族 Coverage 由实际连续采集日期构建，不冒用行情范围；旧根仍只有自身声明的家族与字段。两个表必须同时存在，未知证券或日期、重复坐标、覆盖中间缺口拒绝。
- DailyBasicSeriesResolver 接入 Generation 的同一行式/列式读取分派。仅读取请求列、证券和日期；列式准确日期连接，缺失值不前向填充。真实 Parquet 测试验证一个 PE 值之后两天仍缺失，且 close_raw 不取 daily_basic.source_close。
- 同一候选普通构建与 64 Session 流式构建的根一致，包含稀疏/空分区；重新打开并完整 validate_generation 通过。原有价格/行业流式 Bootstrap 回归通过。
- 新增价格单独刷新回归发现：原先保留 daily_basic 文件但丢字段声明（实测 1 failed / 1 passed）。已将非目标家族目录条目与当前价格目录合成，保留完整家族描述和字段。刷新目标仍是当前已实现的核心价格家族；daily_basic 自身更新尚需接入后续来源刷新路径。
- 存储、依赖和来源整组曾 88 passed / 6.01s；随后新增刷新缺陷回归并修复，最终复验 session 66137 已终态 exit 0，88 passed / 5.96s，Ruff 通过；无正在等待的测试进程。一次测试调用误用 canonical 参数改为 replacement_canonical 后才复现真实字段丢失；不将参数错误当作产品缺陷。之前行长和 import-order 检查失败均已修复。
- 尚未完成：实际 TushareDataSource/Operator 的采集接入、operation 身份与 raw receipt 生命周期、daily_basic 新数据的刷新/重试检查点与独立状态、Replay/HTTP/MCP/Web 当前目录合同调整和 Run/Batch/Track 有界验收。当前仅完成存储/读取及价格刷新保留边界，不标本票 complete，不审查/提交半张工单，不进入 03。

## Daily basic refresh replacement — 2026-09-12

- 公开回归先复现 daily_basic 自身刷新被忽略：旧 PE 15 未变成新空值，新日期 PE 22 未进入候选（1 failed / 1 passed）。
- materialize_refresh 现在依据本次实际提供的家族选择更新目标：价格基础家族必需，daily_basic 提供时更新该家族，未提供时保留原引用与目录。首次从无 daily_basic 的旧根接入也使用同一当前合同。
- 每日指标的稀疏表按日历分区序号保留前缀和空分区，重写边界后的行以新观察为准；新空值不会拿旧值补回。覆盖由合并后的实际完成日期表重新计算，不把部分 replacement window 冒充完整历史。
- 回归验证首次刷新接入与直接构建得到同一根；已有 PE 15 更新为空且另一日加入 22；旧 Generation 重开仍是 15；价格单独刷新仍保留指标。初次 Ruff 两项行长失败已修复，测试 session 6950 已终态 exit 0：88 passed / 6.28s，Ruff 通过。没有待轮询的测试进程。
- 下个实现边界仍是 TushareDataSource/Operator：需要显式采集操作身份贯通检查点（同操作重试复用、新操作重新观察），而不是将固定日期或进程内随机值当作刷新身份。生产入口和 Replay/测试调用方一并改成当前合同，不添加可选来源跳过的兼容路径。
- 02 未完成、未 review/commit；03—08 未开始。

## Explicit collection operation identity — 2026-09-12

- CollectionPlan 与 BootstrapCollectionPlan 增加必填 collection_key，计划工厂同步要求调用方显式传入，空白/非规范身份拒绝。没有默认日期键、旧计划 fallback 或版本分支。
- Bootstrap Operator 传入 bootstrap 操作身份，刷新 Worker 传入 refresh 操作身份；同一 claim 重试保留身份，新操作不因日期相同混用。独立只读资格入口在每次调用显式建立独立 qualification 身份。
- 更新当前 Fixture/TuShare/Replay 的计划调用方。验证先 91 passed，补齐相同窗口不同身份及非法身份拒绝后 95 passed / 0.68s。首次新增参数造成的行长和 import-order 问题已修复；session 75162 已收取终态。AST 扫描核查所有相关当前调用均传入 collection_key。
- 这一步已完成 Operator→采集计划的身份传递；daily_basic 来源本身仍未由 TushareDataSource 调用，检查点生命周期和来源状态仍待接入。下一步直接用 plan.collection_key 建立该来源检查点，并同步生产与 Replay Source 的当前构造合同，不能增加无来源则跳过采集的兼容分支。
- 02 仍未完成，未开始 03—08。

## Daily basic Replay source — 2026-09-12

- 已核实工作仍位于隔离 worktree，01 提交为 18f1ee9；本票未提交，03—08 未开始。上一轮仅核对主目录工单，没有推进实现；本轮恢复到隔离工作树继续 02。
- ReplayTushareProvider 现在支持 daily_basic 的精确交易日请求和单证券分片，复用当前 Replay 结构中的显式 snapshot.daily_basic 记录，不增加版本、默认空来源或兼容路径。未录制该来源、窗口外日期、非法参数和不完整列均拒绝；已录制窗口中的缺行与原始 null 保留。原始每日指标不混入价格规范化 snapshot。
- 先用来源公开入口复现不支持请求的失败，再实现精确日期/列投影。新增 6001 条记录的真实边界测试证明 Replay 截到 6000 后，采集器会用单证券分片获得全部 6001 条；同 collection_key 重开时，即使后续 Replay 数值改变，也仍读取已保存观察。
- 边界测试初次通过耗时 30.80s，发现 Replay 每个证券分片重复验证全表。改为对该实例不可变记录建立日期/证券索引；最新来源与 Replay 合计 25 passed / 4.41s，Ruff 通过。测试 session 30088、27108 均已收取终态 exit 0，无待轮询进程。
- 下一步仍须将实际 TushareDataSource 的普通/流式 Bootstrap 和 Refresh 接入每日指标来源与显式 collection_key，落实 raw receipt 引用及生命周期，并更新生产构造调用和现有 Replay fixtures。当前通过的是 Replay/来源边界，不代表 Operator 已调用 daily_basic，更不代表 02 验收完成。

## Actual Source collection integration — 2026-09-12

- TushareDataSource 现要求明确 checkpoint_root，Provider 当前合同包含 query_raw；Bootstrap、流式 Bootstrap 和 Incremental/Refresh 均调用 daily_basic。生产 Operator 使用数据挂载内 .operator/daily-basic-receipts，计划 collection_key 原样传入；独立资格入口使用本地资格证据目录。调用方和测试同步更新，没有可选来源跳过分支。
- 使用完整 stock_basic 历史身份验证每日响应，再筛选研究证券并规范化。每日指标不经过价格的缺行补齐逻辑；刷新按窗口替换每日观察，新的 null 替换旧值，保留窗口前数据。每日采集有独立计时阶段，失败不返回成功候选。流式只在当前 Session 分区采集指标，候选含独立完成日期表。
- 新增实际 Source 用例验证非空 PE、金额/比例转换、raw close 来源分离、刷新新空值、旧 batch 未被改写、同操作重开不请求 daily_basic。普通和流式结果写入真实 Parquet 后，data_identity 和全部家族描述一致，完整 validate_generation 通过。最初比较根哈希失败；检查磁盘 manifest 证明差异只有两个操作的来源证据哈希，改为验证数据身份与家族相同，保留各自来源证据。
- 更新现有六个 Replay fixture，显式记录每日指标；无变化刷新也录制其窗口内原始观察。各次刷新使用不同 collection_key，避免测试复用缓存掩盖录制错误。生成脚本首次保留格式断言失败后修复了原 fixture 的空白匹配，并保留原有非 daily_basic 字节布局。录制均为确定性 synthetic fixture，不是新增真实供应商资格证据。
- 既有来源回归初次 70 passed / 2 failed（新增字段/阶段对应预期），修复后 73 passed。Replay/入口/Operator 初次 60 passed / 1 failed（Fake constructor 缺少当前 checkpoint_root 参数），更新后 61 passed。
- 最终定向来源、Replay、资格入口、Operator、真实存储共 217 passed / 11.61s，Ruff 通过。测试 session 39645、9990、11316、18404、45443、66761、24660 均已终态，无运行中的测试。本轮未运行真实 DB/Worker 集成或浏览器验收。
- 尚未完成：raw receipts 与候选来源证据的可验证引用/生命周期、价格与 daily_basic 的独立完成度及部分状态合同、HTTP/MCP/Web/Agent 目录同步、真实 Worker 与 Run/Batch/Track 的有界验收。本票仍未验收完成，不 review/commit 半张工单，不进入 03—08。

## Sealed daily source evidence — 2026-09-12

- 核查发现 Generation preparation 当前只保存 source_lineage 的哈希；仅有 collection_key 不能直接找到、验证每日指标回执。本轮先补齐来源侧的可验证不可变证据清单，Generation 持久引用与保留层仍未完成。
- DailyBasicCheckpoint.seal 要求本次实际完成的日期与声明日期完全相同；不完整采集拒绝封存。清单仅引用当前采集实际使用的回执，避免把同操作目录中未使用的请求混入证明。每页最多 256 个原始回执地址，索引/页均为内容寻址 JSON 且有字节上限；不把大请求身份列表重复塞入候选说明。
- verify_evidence 重开索引、分页及每份原始回执，检查内容哈希、操作身份、请求地址、重复引用及日期集合。证据不含凭证；缺失或篡改不能静默重新采集。先新增缺方法失败回归，实现后证明未完成日期不能 seal、重封结果一致、删除原始回执后校验拒绝。
- 普通 Bootstrap/Refresh 在规范化完成后把封存引用放入 source_lineage.daily_basic_evidence；流式采集仅在全部分区迭代完成后绑定引用，未消费完不能声称来源完成。保持当前操作身份，不添加版本或兼容路径。
- 实际 Source 用例重开普通和流式来源证据，二者声明日期均为 2026-08-03 至 2026-08-05；6001 条 Replay 分片用例也封存并验证分页索引。最终来源/Source/Replay 共 99 passed / 6.81s，Ruff 和 diff check 通过。session 24429 为实现前失败（已终态），11236、98483 为通过终态，无待轮询测试。
- 下一步必须完成 Generation 持久引用：当前 preparation 仍只有来源说明哈希，尚未将 sealed evidence 接入已发布家族的可重开引用与生命周期保护，不能把本轮来源侧测试当作候选保留规则已完成。其他待办仍为独立来源完成度/部分状态、HTTP/MCP/Web/Agent 目录和真实 Worker/Run/Batch/Track 验收。本票未 review/commit，03—08 未开始。

## Generation source references and retained raw history — 2026-09-12

- 将 DailyBasicCheckpoint 的原始回执/证据存储移动到 Data 的 daily_basic_evidence 模块，TuShare 适配器复用该公开能力。原始观察在挂载内 .operator/daily-basic-receipts 追加保留，明确不进入派生 Generation 文件回收；生产 Operator 使用同一目录常量。现有 Bootstrap/Refresh 外围均持有 mounted_data_mutation_lock，未新增数据库版本、迁移或运行时兼容合同。
- 新 daily_basic 家族 manifest 明确持久化 source_evidence；普通/流式构建从封存的 source_lineage 引用写入，真实 TuShare 候选缺少该证据拒绝。确定性来源中不声明供应商原始观察的 fixture 使用空证据集合。旧 Generation 没有这个新家族，不需要赋予或改写其证据。
- 日指标刷新保留此前所有来源索引并追加当前观察，价格单独刷新保留整个每日指标家族和证据。完整校验重开原始回执，并要求证据日期集合与实际采集日期表一致；删除旧回执后，新刷新候选校验也会拒绝。源文件不在派生对象 inventory 中，不会因旧派生根退出保留集合而自动丢弃原始历史。
- 实际来源/存储用例证明普通与流式候选重开的 canonical 内容相同。因为各自的来源观察已进入家族身份，两种独立操作不再要求根/家族哈希相同；验证的是值、日期、字段和各自证据的完整性。
- 新回归发现 open_refresh_base 的行式候选表集合仍遗漏 daily_basic 两张表，导致已有指标候选无法成为下一次刷新输入（209 passed / 1 failed）。已修复成对表合同，定向复验通过，随后完整受影响来源/Replay/存储/Operator 210 passed / 14.90s。首次参数落点错误和 Ruff 行长已修复；最终 Ruff、diff check 通过。
- 更新独立家族可用性测试：价格支持 7 项、每日指标支持 15 项、共三个当前 authorable 家族。新增价格 ready 时每日指标缺失为 not_ready、落后一日为 partial 的用例，共 4 passed；来源完成接口改成公开 mark_session_collected 后再跑 16 passed。
- 真实依赖暂未执行：本次 Docker socket 默认沙箱访问被拒绝后，授权只读探测仍无响应，/_ping 在 5 秒超时（exit 28）。docker info 等待两分钟无输出后仅终止本次查询 PID 304，session 49066 已终态 143；未停止/重启 Docker 或任何容器。测试 session 80225、20929、57708、66008 均已终态；当前无待轮询进程。这只是当前真实 Worker 验证阻碍，其他工作可继续，不将目标标 blocked。
- 剩余：采集过程的独立来源完成状态/重试行为需要真实 Worker 证据；HTTP/MCP/Web/Agent 当前目录合同和 Run/Batch/Track 的有界验收仍未完成。下一步可先完成无需 Docker 的目录、准入和界面合同检查，同时有界重查 Docker 可用性。本票未验收、未审查/提交，03—08 未开始。

## Current catalog, filters and formula completion — 2026-09-13

- 本轮继续 02，01 仍为 18f1ee9，未开始后续工单。默认来源和市场读取以外，核对 DSL 与 MCP 当前合同：既有相关内核、MCP 入口及架构合同测试 156 passed / 17.89s。该结果不代表真实 MCP HTTP / Worker 研究链路已验证。
- 补充独立 DSL 预期：close_raw / pe + turnover_rate 分别绑定原始价格、每日估值和换手率身份；close_raw 来源仍为 daily，PE 单位 multiple，换手率 DSL ratio、来源 percent。只声明价格的 Generation 目录不会出现 PE。最终 Alpha Language 合同 61 passed / 0.20s，Ruff 通过。
- 浏览器字段夹具由当前公开 Alpha Catalog 生成，包含目前已实现的 28 项（7 价格 + 15 daily_basic + 6 原三表），不是尚未完成的 226 项。新增跨消费者检查逐项比较夹具和后端公开目录，防止旧夹具继续冒充当前合同。
- 复用 Data 页与真实 AlphaFormulaEditor 的仓库 Playwright 组件入口，在 1280px、390px 两种宽度验证：仍为四个顶层状态区；daily_basic 单独落后一日让 Market 显示 partially ready；15 项来源筛选、中文搜索、close_raw 搜索；既有财务筛选；turnover_rate_f 和 close_raw 的补全选中及插入；无水平溢出。最终 2 passed / 4.5s。页面组件 7 passed，Web typecheck 通过。
- 本轮只更新验证夹具和测试，未为数据来源增加新顶层 UI，也未改产品页面/编辑器实现。浏览器请求使用同一 /api/data Replay 响应；不能将这些组件证据当作真实服务端提交研究完成。
- Docker 本轮有界 /_ping 再次 5 秒超时（session 2257 exit 28），未启动集成环境、未操作共享开发数据。其他测试 session 67977、37711、38040、25008、12435 均已终态通过，无待轮询进程。尚有无需 Docker 的来源重试/状态边界可继续，因此不将整体目标标 blocked。
- 待完成仍为采集过程独立来源完成度/重试验证、真实 Worker/HTTP/MCP 与 Run/Batch/Track 的有界执行验收、按本票完整范围进行串行审查修复复审，随后更新验收并独立提交。02 未标 complete、未提交。

## Interrupted collection and broader quick checks — 2026-09-13

- 新增实际 Refresh 来源中断用例：分别注入限流和权限错误。价格 source_collection 已完成时，daily_basic_collection 仍独立失败；旧 canonical 不变且不封存完整证据。重开后只请求第 2、3 日，第 1 日复用原始回执。两项通过，验证的是来源阶段和每日指标检查点，不冒充真实 Worker 事务验收。
- 新增截断一致性回归发现两步缺陷：整日已观察证券在单证券分片中消失时原先仍被接受；仅在汇总后拒绝又会缓存空分片，造成同操作无法恢复。已将必需行校验移到保存回执之前。6000 行边界下，失败后只重取此前遗漏的一只证券，收敛为完整 6000 条；未引入旧数据 fallback 或删除检查点来强行通过。
- pnpm test 的工具归属、29 项工具测试和完整 Ruff 通过；Core 阶段 1264 passed / 1 failed / 135.34s。唯一失败为 HTTP 价格目录旧预期遗漏 close_raw，已更新为 7 个价格入口；新增 HTTP 用例验证全部 15 项每日指标的身份、单位、分类及价格-only 目录不暴露它们。来源/Replay/HTTP 定向复验 34 passed / 13.12s，Ruff 通过。
- 按仓库 quickCommands 中尚未运行的阶段顺序继续，Agent typecheck/test/eval-preflight、Auth typecheck/test、共享 TypeScript、Web typecheck/test:shell 全部通过（session 10580 exit 0，Web 355 tests）。未将最初中途失败的 pnpm test 声称为一次全绿；修复后只复验受影响 Python 范围，并完成原本未运行的后续阶段。
- Docker /_ping 本轮再次超时，session 97419 exit 28。只读确认 OrbStack 与 Helper 进程存在，orbctl status 返回 Running；Docker API 无响应并非应用进程未启动。读取了本地 orb/orbctl help，未执行 start/stop/restart/reset/config 修改，也未操作共享容器。
- 所有本轮测试句柄 62986、23832、61706、97830、85347、22497、10580 均已终态；无等待中的测试。两个截断回归的先失败证据已由最终 34 项复验覆盖。
- 下一步需进一步核对价格来源在 daily_basic 失败后的持久完成/重试边界：当前测试只证明每日指标已完成日期不会重取，不能声称价格原始响应已独立缓存。真实 Worker/HTTP/MCP 和 Run/Batch/Track 的最终执行证据仍被 Docker 无响应阻碍；工单完整实现、验收、串行审查复审和提交仍未完成，03—08 未开始。

## Independent price checkpoint — 2026-09-13

- 继续在 codex/field-expansion-226（HEAD 18f1ee9）实现 02；上一轮只有确认发布状态，未推进实现。本轮先重跑价格请求计数回归，两项明确失败：每日指标失败后的价格请求从 1 增为 2（session 90037 exit 1）。
- 新增 MarketSourceCheckpoint：按采集操作、类型、精确起止窗口隔离，保存通过规范化和覆盖校验的原始价格响应；沿用 AddressedFileStore 的原子写入及内容哈希，128 MiB 有界读取。每日指标中断后，新 Source/Provider 实例从该响应恢复，成功价格不再访问供应商。新操作重新观察；损坏回执直接拒绝，不能静默联网替代。
- 价格重叠补全先复制表列表，避免把历史补入行写回原始响应。未完整的新日价格/日历/复权/涨跌停事实不能进入检查点；同操作补齐真实响应后可恢复。
- Provider 当前合同显式选择 Market 请求窗口。Replay Bundle 在价格已缓存时仍能绑定每日指标响应，不依赖先调用价格采集产生的进程内状态；Live Provider 不需要额外窗口状态。没有 hasattr 回退、双版本合同或迁移链。
- 未发布的新来源回执目录统一为 .operator/market-source-receipts，容纳独立价格和每日指标证据；同步更新生产入口、Generation 校验和相关测试。没有移动或修改既有生产数据，原始来源仍在派生 Generation GC 范围外保留。
- 首轮来源/Replay 85 passed / 7.01s。扩展新进程恢复、新操作重采、损坏拒绝以及存储/Operator 后 196 passed / 13.51s（session 6508 exit 0）；最后补齐不完整价格同操作恢复，6 passed / 0.13s。完整 Core Ruff 和 git diff --check 通过。早期三项行长错误已修复。测试句柄 90037、43598、6508 均终态，无在跑测试。
- Docker 只读诊断：orbctl doctor 配置检查通过，仅非 OrbStack kubectl 路径警告；Docker /_ping 仍 5 秒超时（session 9089 exit 28）。未执行 --fix、重启或共享环境修改。该结果不能证明引擎健康，真实 Worker/HTTP/MCP 和 Run/Batch/Track 验收仍未执行。
- 下一步：在现有隔离集成用例中补齐实际每日指标来源中断→重新领取→发布→读取的 Worker 验收，并继续处理研究执行验收；恢复 Docker 后运行对应入口。还需完整串行 Standards→Spec 审查、修复复审、逐项验收和独立提交。本票仍未 complete/commit，03—08 未开始。

## Worker fixture, execution equivalence and initial serial review — 2026-09-13

- 新增真实 Worker 重试验收：限流失败保持 Head / freshness 不变，重新建立 Service 与 Provider 后仅请求未完成每日分片，价格请求为零；成功发布后验证家族、值、原根和重复领取。54 个集成用例收集通过，Ruff 通过；此新增用例尚未实际运行，不能标为通过。
- 新增真实挂载 Generation 的独立行式预期：混合 close_raw / pe + turnover_rate 的单次计算与挂载读取一致；整日每日指标缺失时 Alpha 为空；列式跟踪在缺失日及恢复日的 continuation 与行式一致。测试先修正了调用参数和 RunInput 测试辅助函数，最终整个 tracking_columnar 文件 8 passed / 8.64s。
- 新增 Batch 因子评估及 Strategy Sweep 与单次研究子执行的逐项 final_values / continuation 对比，使用同一实际挂载 Generation、跨 chunk 缺失日期，并禁止供应商调用。完整 batch_execution 文件 5 passed / 4.02s。上述属于真实文件与计算入口证据，不替代 HTTP / 数据库 / Worker 产品闭环。
- 依 code-review 技能建立固定快照 /tmp/thesistrace-issue02-review-20260913（46 文件），严格先 Standards、后 Spec。Standards：0 硬违规、2 启发式维护性发现（稀疏表分派重复、来源证据地址重复）。Spec：1 实现缺陷（价格从 64→65 Session 刷新时保留 daily_basic 后候选无法验证）、1 未完成验收（真实 Worker/HTTP/MCP/Run/Track），无范围扩张。
- 对 Spec 缺陷先补真实文件回归并得到 Generation table partitioning is invalid。修复使独立稀疏家族可保留较短分区范围；其两张表的分区数量必须一致，数据行数、日期和实际 Coverage 继续校验，新价格日期读取每日指标为缺失。未扩张旧家族声明或补写旧根。
- 同步处理 Standards 两项：TableSpec 集中 allows_sparse_sessions，初建、刷新和列式校验复用；每日证据相对地址只由 daily_basic_evidence_path 定义，Generation 不再拼接其目录。
- 修复后采集/回执/存储 161 passed / 11.30s（session 85936）；一项新增测试函数行长已修正，最终完整 Core Ruff、diff check 通过。所有本轮测试句柄 50077、8279、52517、25755、31346、71252、8165、71349、85936 已终态，没有在跑测试。中间失败属于测试构造错误或已记录的实际跨分区缺陷，未将最初失败命令声称为一次全绿。
- Docker 等待用户异步答复：已说明重启 OrbStack 会影响其他 Docker 开发服务，询问由用户自行恢复或授权重启；尚无答复，不以超时当批准。只读日志最后记录 09-12 23:05:43 sleep，配置自检通过，不能据此证明超时原因；未重启/修复共享环境。
- 接下来对上述修复做串行 Standards→Spec 复审，继续保留真实依赖验收缺口。02 未完成/提交，03—08 未开始。

## Serial re-review result — 2026-09-13

- 修复快照 /tmp/thesistrace-issue02-rereview-20260913，固定较初审变化的五个文件；其余范围和 HEAD 不变。
- Standards 先完成：0 硬违规、0 未解决启发式发现。集中稀疏表语义、集中证据地址两项关闭；跨分区修复未引入新的规范问题。
- 随后 Spec 完成：原 P1 64→65 分区问题关闭，新增实现发现 0。复审者独立执行跨边界回归及采集日期中间缺口拒绝，2 passed / 0.61s。无新的范围扩张。
- 验收缺口保持：新的真实 Worker 重试用例尚未运行，实际 HTTP/MCP 提交、Run/Track 完整产品链路仍需隔离环境证据；挂载数据计算、Batch 和跟踪 continuation 已验证，不能据此替代产品验收。
- 本票当前实现发现已收敛，但验收条件未全部成立，仍不标 complete、不提交；后续如修改产品实现，须针对变化再验证并复审。异步 Docker 恢复/重启问题仍未获答复，未操作共享服务。03—08 仍未开始。

## Product acceptance preparation — 2026-09-13

- 上轮属于进展：新增验证、修复分区缺陷并完成串行复审；本轮没有重复进行已通过的计算测试。HEAD 仍为 18f1ee9，02 未提交。
- Docker API 再次在 5 秒超时（session 18827 exit 28）；异步恢复方式问题尚未回复，未重启共享服务。已明确存在阻碍，但此前仍有产品验收用例可补齐，因此本轮继续完成独立工作。
- 新增 HTTP 完整验收：旧目录不含 PE 且拒绝新字段公式；发布每日指标后目录28项，混合公式经过真实Worker成功；建立DailyTrack、发布下一交易日、刷新推进；原Run仍固定此前Generation，旧Generation不增加PE。现有全行情加财务目录预期由12修正为13（新增close_raw）。
- 新增 MCP stdio 完整验收：查询 close_raw/pe/turnover_rate，提交混合公式，启动既有真实研究Worker入口，断开重连后查询成功结果。复用既有测试发布助手，daily_fields选项只用于构造测试数据，没有增加产品开关或兼容路径。
- 最初单独收集 acceptance 文件缺少 integration 中 canonical_store 测试模块；改用仓库 integration+acceptance 两个测试根后，476项中3项指定用例收集成功（473 deselected，0.47s）。两个新增函数行长已修正，最终 Ruff 和 diff check 通过。此处只有收集/静态证据，未执行真实依赖测试。
- 产品实现与上一轮通过复审的快照相同。新增三个测试/助手文件冻结在 /tmp/thesistrace-issue02-product-tests-review，先进行 Standards，再进行 Spec 补充审查。03—08 未开始。

## Product-test review and blocking audit — 2026-09-13

- 新增三个产品测试/助手文件按顺序完成 Standards→Spec 补充审查：两轴均无新增发现，无范围扩张。审查确认发布使用真实候选/Lifecycle CAS，后续刷新使用 materialize_refresh，MCP经过实际stdio及独立Worker；这些是待执行测试的结构核查，不是执行通过。
- 02 的当前未解决事项为实际运行真实 Worker 重试、HTTP/MCP 与 Run/Track 产品验收，并按结果修复/复审后逐项验收及独立提交。无需真实依赖的实现与必要测试、审查已完成；不再增加重复测试或重复检查来替代这个阻碍。
- 同一 Docker API 无响应已连续多轮由有界/_ping确认，本轮 session18827 为终态exit28。OrbStack恢复方式异步问题未获答复；不重启共享服务，不将等待视为批准。此时没有可继续推进的独立实现工作，严格串行规则也不允许跳至03。因此将线程目标标记blocked，待Docker恢复或获得重启授权后恢复02验收。
- 01已完成提交18f1ee9；02保持未完成且未提交；03—08未开始。所有实际测试进程与审查任务已终态，没有后台验收等待句柄。

## Docker recovered; real integration running — 2026-09-13

- 新一次只读 /_ping 返回 OK，未由本任务重启 OrbStack。线程目标恢复 active；此前恢复/重启授权问题不再是当前必要操作。
- 已通过仓库原有隔离入口启动完整 Core integration：mise exec -- node tooling/test/cli.mjs integration。运行ID 20260912t164240z-49328-87be0225，项目 thesistrace-test-20260912t164240z-49328-87be0225，工具进程 session77360。使用独立 PostgreSQL/RustFS/Auth，未操作共享开发数据。
- 基础服务健康及初始化已通过，普通 integration/acceptance 测试正在执行；目前已有失败标记但尚无完整终态汇总。不得据此声明新增产品验收通过，不因观察超时重新启动本轮；继续轮询相同句柄，终态后读取实际诊断再修复。
- 本轮测试期间未修改产品源码或测试文件。02仍未complete/commit，03—08未开始。

## Integration failure repair and targeted recheck — 2026-09-13

- 完整普通集成运行 20260912t164240z-49328-87be0225 已终态：460 passed、8 failed、8 deselected，1356.51 秒；依赖重启阶段因普通阶段失败未运行，专属资源已清理。失败清单已从 pytest.xml 核实。新增 daily_fields HTTP Run/Track 和 MCP 真实 Worker 用例已通过；不能据此称完整门禁通过。
- 修正八处测试合同/夹具：HTTP 页码分页及所有权断言；两处动态 Replay 显式 daily_basic 响应；首次增加每日家族的发布事件与结果；Decimal 按数值比较；重启后验证当前 Overview 元数据；MCP 空 Head 合同；容量竞争按 Auth 实际额度构造恰好一个剩余名额。未增加产品兼容分支或修改配额。
- 七个受影响测试文件 Ruff 通过，git diff --check 通过。当前修复尚待真实执行结果及串行复审。
- 通过临时 /tmp/thesistrace-issue02-recheck.mjs 复用仓库 TestRun/integration/finish，只选择八个原失败和两条新增产品测试；未修改永久测试运行器。运行 20260912t171434z-61399-230bd85f，session75696，已确认专属 PostgreSQL/RustFS 健康并继续初始化 Auth；当前进程仍活跃。此轮不执行未受测试修复影响的依赖重启阶段，不声称其通过。
- 02 未完成、未提交；03—08 未开始。下一步轮询同一运行句柄，按实际失败继续修复，再串行 Standards/Spec 复审与本票独立提交。

## Targeted result and remaining MCP assertion — 2026-09-13

- 上轮为进展：修复八处合同偏差并启动定向重测；本轮继续同一session75696直到终态。运行20260912t171434z-61399-230bd85f：9 passed、1 failed、466 deselected，155.46秒；隔离资源已清理。Worker恢复、HTTP/MCP新字段研究、Track推进、容量竞争等所选用例通过。
- 七文件冻结快照 /tmp/thesistrace-issue02-integration-fixes-review 已串行完成 Standards→Spec：两轴均0发现。审查结果只覆盖当时快照，不代替测试。
- 唯一剩余失败为MCP空Head目录仍预期close。已核对 ResearchAgent registry.get_alpha_catalog：按Overview.available_field_ids构造目录，空Head没有可用字段，所请求close列入unknown_identifiers。修正测试为fields空、generation为空、unknown包含close及原unknown；保留Builtin和诊断断言，无产品改动。Ruff通过。
- 单独复验运行20260912t171834z-63091-c79b9195，session58273仍活跃。临时运行器的阶段筛选已收紧为精确的六个restart阶段；上一轮误跳过rustfs-s3-ready探测，后续真实S3测试已通过，但该探测未执行的事实保留。本轮恢复原S3就绪探测。没有修改永久运行器。
- 下一步读取58273终态，对最后这处MCP测试变化串行补审，核对02全部证据并独立提交。02仍未complete/commit；03—08未开始。


## Acceptance and independent delivery — 2026-09-13

- 最后 MCP 复验 20260912t171834z-63091-c79b9195 已终态 exit 0：1 passed、475 deselected、6.91 秒；S3就绪检查正常执行，专属资源清理完成。与前一轮9项通过共同关闭完整普通集成的8个失败点，未将完整首次运行描述成全绿。
- 最后测试增量冻结于 /tmp/thesistrace-issue02-final-mcp-review，严格 Standards→Spec 补审均0发现。初审的分区缺陷、两项维护性发现及真实产品验收缺口全部关闭。
- 验收1—2：当前目录为7价格+15每日指标+6既有财务，共28；close_raw只绑定原始价格。字段/HTTP/语言/目录测试及真实页面搜索补全已通过。
- 验收3—6：19列原始来源、6000行拆分、历史身份、独立价格与每日分片恢复、空值/单位、限流失败和证据损坏拒绝由来源公开测试及真实Worker重试证明。有界真实资格原始响应和规范值见同目录daily-basic-unit-qualification.json，不将4个证券日期样本当全历史采齐。
- 验收7：真实Parquet候选重开及64→65 Session跨分区回归证明非目标家族/覆盖和旧根保留；实际Worker使用单一Head发布并验证。
- 验收8：1280/390真实浏览器组件2项、Data组件7项、Web类型与355项测试通过；部分状态、四个顶层区块、来源/中文搜索和补全一致。实际HTTP/MCP目录、拒绝与提交路径通过。
- 验收9—10：挂载Generation计算与列式跟踪8项、Batch与单次等值5项，禁止供应商网络；真实HTTP混合公式→Worker→Run→Track下一Session与MCP独立Worker产品验收通过，旧Run保持冻结Generation。
- 本票不涉及依赖重启机制变更，六个专门restart阶段未在02末轮执行；不宣称完整integration入口或完整产品发布门禁通过。完整历史与最终跨模块发布门禁分别由07/08承担。无线上切换、兼容路径、版本迁移或自动清库。
- 所有02验收已满足，随独立提交 feat(data): add resumable daily basic research fields 交付；提交前HEAD为18f1ee9，可由该主题提交精确定位。03开始前再次核实提交成功。
