# 226 个行情与财务字段：统一 Data 与 Alpha DSL 规格

Status: ready-for-agent

日期：2026-09-12。整理自本轮字段研究、grill 决定、代码核查与用户对硬切和 Data 页分组的要求。本文是本功能的实施与验收依据，替代同目录此前逐轮追加的设计草案；191 / 223 项清单仅作为范围演进记录。

`ready-for-agent` 表示需求与验收标准足以进入实施，不表示接口数据已采齐、字段已上线或测试已通过。本轮只发布规格；来源资格验证、实现和数据发布均须按下述门槛完成。

## Problem Statement

Researcher 希望组合行情、估值、盈利、成长、现金流和资产负债结构开展策略探索。核查基线只有 12 个 Alpha-authorable Fields：6 个行情字段、6 个三表财务字段。三表已保存更多来源列，但只有少量字段完成规范化、研究时间投影和 DSL 接入；每日指标与供应商财务指标还需采集。因此问题同时涉及来源、计算、字段目录、研究读取与数据发布，不能只放宽作者目录。

扩容还会暴露当前合同的限制：财务就绪被压缩为一个开关，页面每类字段只识别一个 Dataset Family，部分 Generation 校验依赖当前全局字段集合，行情刷新只显式保留既有财务和行业。直接追加字段可能让旧研究无法重试、新字段在下一次刷新后消失，或页面错误显示全部就绪。

Researcher 希望一次切换到整洁的当前实现，复用已有数据，保持现有 Data 页面的大类结构，并明确财务期间和缺失语义，不增加复杂的期间差异界面。

## Solution

将目标清单扩展到 **226 个 DSL 字段**，通过单一 Field Catalog、Canonical Field References 和 Data 读取接口提供给 Alpha Formula、ResearchRun、Research Batch、DailyTrack、HTTP/MCP 与 Research Agent。

| 范围 | DSL 数量 | 处理方式 |
| --- | ---: | --- |
| 原有行情与三表字段 | 12 | 保留作者名、Canonical Field 身份、原有含义和数据 |
| daily_basic 数值入口 | 16 | 新采集；15 个新每日指标身份，close_raw 复用已有未复权价格身份 |
| fina_indicator 供应商指标 | 163 | 新采集独立财务指标版本，保留供应商定义与证据范围 |
| 已存三表扩展 | 32 | 从原始记录提供 16 个存量、16 个显式 TTM 流量 |
| 核心流量 TTM | 3 | 新增 revenue_ttm、net_profit_ttm、operating_cash_flow_ttm |
| **合计** | **226** | 相对原有 12 项增加 214 个作者入口 |

新增百分比字段以小数比例参与 DSL，例如 15% 为 0.15；新增 19 个流量按匹配的可见报表重构 TTM。两个 TTM 流量直接运算时，窗口不一致就返回缺失，沿用现有缺失传播和覆盖统计。

现有行情、三表、行业及其他研究依赖作为底座，与两个新来源组成新的 Data Generation。验证后统一切换 Dataset Head 和当前应用合同；历史来源、既有研究及其必要数据引用继续保留。

Data 页仍为 Market data、Financial data、Industry data、Strategy Benchmark 四块。行情目标 22 个字段，财务目标 204 个字段；实际可用数量与就绪状态来自当前已验证数据。

## User Stories

1. As a Researcher, I want a documented catalog of market and financial fields, so that I can explore valuation, growth, profitability, cash flow, and balance-sheet structure in one Alpha Formula.
2. As a Researcher, I want explicit TTM fields and consistent percentage units, so that financial expressions have predictable meanings without changing my existing formulas.
3. As a Researcher, I want unavailable or incompatible financial inputs to remain missing, so that research does not silently substitute another report or invent a value.
4. As a Research Agent, I want the same available fields and validation rules as the webpage, so that research submitted through MCP uses the same contract.
5. As a Data Operator, I want to reuse retained history and collect only the required new sources or confirmed gaps, so that expanding the dataset does not require downloading all existing data again.
6. As a Data Operator, I want refreshes and publication retries to preserve other data families and accepted research inputs, so that updates do not remove fields or overwrite concurrent work.
7. As a Researcher, I want one current implementation and the existing Data page categories, so that the expansion remains understandable while my results and tracking history are retained.

## Implementation Decisions

### 1. 一个字段权威入口与一套当前合同

- Data 拥有 Canonical Field 定义、来源规范化、Dataset Family、Dataset Coverage、研究可见时间和读取。Alpha Language 拥有作者名解析、编译和表达式计算；ResearchRun、Research Batch、DailyTrack 继续拥有各自准入与执行生命周期。采集、发布和界面不复制这些规则。
- 继续采用静态、类型化字段定义，经一个入口提供 Field Catalog。每项声明唯一作者名、稳定身份、中文含义、研究分类、来源列、源单位、规范单位、固定期间、合并/归母或供应商范围、适用公司类型、缺失规则与证据类型。
- 作者名保持全局唯一的 snake_case，不与现有 Builtin 冲突；不新增点号访问、同义别名或可编辑字段注册平台。原有 12 个字段的意义不改写；新增期间使用新的 Canonical Field 身份。
- 相同输入的值保持，以冻结的 Generation 为边界。新候选可依据原始证据纠正旧投影错误（例如等待日历的报表应当生效、无法确定的冲突值应当缺失），必须逐坐标保留归因，禁止改写旧根或为保持旧错误增加兼容分支。此处落实用户最新的“开发阶段遇到问题及时解决”要求，不把跨 Generation 的有证据修正误当成字段语义改写。
- 将财务布尔开关和固定两组分派替换为实际所需家族与字段集合。Alpha Authoring Catalog 依据 Generation 已验证的可用字段集合生成；HTTP/MCP、Web 和 Agent 采用同一当前合同，不保留旧开关或旧响应形状的运行分支。
- 系统支持某字段、某 Generation 包含该字段，以及该研究范围可使用该字段，是三个不同事实。某股票日值为空不等于整个字段未实现；未通过来源语义或采集完整性验证则不能冒充已就绪字段。

### 2. 数据家族与页面分类分离

| Dataset Family | 作者入口目标 | 数据特征 | 页面归属 |
| --- | ---: | --- | --- |
| equity.eod_price | 7 | 原有 6 项与 close_raw；复用现有价格 | Market data |
| equity.daily_basic | 15 | 新增每日指标，按股票和交易日记录 | Market data |
| equity.financial_pit | 41 | 原有 6 项、新增 16 存量和 19 TTM 流量；复用三张稀疏版本表 | Financial data |
| equity.financial_indicator | 163 | 独立供应商指标宽版本表 | Financial data |

- 两个新增家族仍由现有 Data Module、Operator Worker 和单一 Dataset Head 管理，不新增服务、研究资源或独立发布 Head。日历、证券身份、交易状态、股票池、行业和基准依赖继续沿用。
- daily_basic.close 作为来源校验数据保存；close_raw 只绑定已有 price.close.raw 身份。发现来源价格差异应记录并核验，不逐行换源补缺，也不改变已有复权 close 的含义。
- 延续 Market、Financial、Industry Refresh 的产品入口。每日指标随 Market Refresh 更新，供应商财务指标随 Financial Refresh 更新；内部保留不同来源的采集完成度、待更新状态及覆盖，不以某一个来源成功代表整组完成。

### 3. 固定财务范围、期间与单位

- revenue、net_profit、operating_cash_flow 继续取最新可见年报；assets、liabilities、equity 继续取最新可见报告的期末存量。原字段范围分别沿用营业总收入、归母净利润、合并经营现金流及原有资产负债权益定义。
- 新增 16 个存量按最新可见报告期末取值；cash_equivalents 虽来自现金流量表，仍是期末存量。新增 19 个流量全部采用显式 TTM 作者名，包含三个核心流量 TTM。
- revenue_ttm 与 revenue 使用相同收入范围；net_profit_ttm 与 net_profit 使用相同归母范围；operating_cash_flow_ttm 与原经营现金流字段使用相同合并范围。operating_revenue_ttm、consolidated_net_profit_ttm 分别保持营业收入和合并净利润的独立定义。
- rd_expense_ttm 是损益表研发费用，与供应商 rd_exp 的研发投入合计分开；货币资金不自动等于无限制现金，一年内到期非流动负债不自动等于全部有息债务，经营现金流减资本支出不宣称是严格 FCFF 或 FCFE。
- fina_indicator 的 163 项保留供应商已核实的单季、累计、年化、同比或较年初等定义，不整体改成 TTM，不在空值时改用三表推算。先按固定的字段期间合同选择最新可见报告记录，再取该列；选中列为空就缺失，不寻找更早的非空值。
- 三表按逐字段核定的合并范围和公司类型处理。fina_indicator 没有来源保证的 report_type、comp_type 或修订时间时，不填造这些元数据，也不借另一接口的同期间记录冒充来源证据。
- 新金额目标为 CNY，股数为 shares，每股金额为 CNY/share；倍数和天数保持自己的单位。新百分比字段的 DSL 值统一为小数比例，界面可显示百分比；PE/PB 等倍数不缩放，来源已是小数比例时不再除以 100。所有转换逐列有证据，原始值保留，不能凭列名或浮点类型批量转换。

### 4. TTM 计算、Seed Facts 与缺失

- 对每个字段独立选择研究时点最新可见的目标报告期。年末直接使用全年流量；中期使用本期累计加上年度全年，再减上年同期累计，得到截至目标报告期的最近十二个月。
- 三项组成必须匹配股票、科目、单位与报告范围，且各自版本已在该 Research Session 可见。任一必要记录或值缺失，TTM 就缺失；不回退到年报、上一期 TTM，也不按每日填充值滚动求和。
- 目标报告、上年年报、上年同期报告任一组成出现可见更正，都触发相应 TTM 重算；不能只监听目标报告期变化。
- Financial Seed Facts 保留整个 Coverage 内计算所需的 pre-start 依赖闭包，与原年报/存量需要的种子取并集。2010 起点可能需要 2008 年报和 2008 三季报；随后计算 2010 一季报仍需 2009 一季报。这不扩大到 2010 年之前的研究范围。
- 两个 TTM 流量直接做算术运算时，双方必须有效且覆盖同一十二个月窗口，否则该股票、该研究日的该次运算为缺失。以后完整且同窗口时，从其可见日恢复计算；不利用后来披露补写先前日期。
- 单字段仍独立选择其最新可见报告，不因公式的其他依赖而改用旧期。普通括号、符号或乘除常数不能绕过应有的同期检查；原有字段公式、常数、每日行情、期末存量、显式跨期 Builtin 和截面排名仍遵守各自合同，不追加全公式或全市场统一报告日限制。
- Data 与计算端只传递同期判断所需的最小期间信息；供应商记录和组成版本证据留在 Data。结果沿用已有缺失传播、missing_expression 覆盖统计、因子样本门槛和选股行为，不新增期间差异界面或研究结果诊断协议。缺失本身不触发即时交易，调仓时仍按既有选股和成交规则处理。

### 5. 历史回填、观察与修订

- 日频指标按交易日精确对齐，缺失不前向填充；只在收盘后的信号计算中可用，不用于同日开盘决策。daily_basic 的历史估值值不被宣称为具有完整分母修订历史的 PIT 数据。
- 只有公告日期的财务记录，从公告日后的第一个 Research Session 可用。缺少或无效公告日期时隔离记录，不能用报告期末日期补造可见时间。
- 保存原始响应、报告期、来源公告日、来源更新标记、首次观察时间和内容哈希。同一内容重试去重并保留最早观察证据；实际观察到的更正保留为独立版本。
- 同一逻辑记录、同一公告日后来观察到更正时，更正版最早从其首次观察之后的可用 Session 生效。来源确有独立新披露日期时保留其证据。无法证明先后的冲突版本隔离，不能靠响应顺序、哈希或未经验证的 update_flag 优先级伪造修订次序。
- 冲突源记录仍原样隔离保存。研究读取按同一逻辑报告、公告日和首次观察时间逐字段取共识：所有版本完全一致的字段可用；不同数值或有值/空值不一致的字段为缺失，不从某一版本补值。共识投影遵守同样的公告及后见更正时间边界，单列与多列读取结果一致，不增加前端状态。此规则源于 07 的实际历史验收：不能因 EBIT/EBITDA 的缺漏而丢弃各版本完全一致的收入。
- 允许将首次回填的供应商旧报告按其已知公告日期作历史投影，明确属于 Announcement-Aligned Financial History：不证明原始披露值及完整修订链。从本次采集开始持续保留观察版本，不把有限历史证据包装成完整 PIT。

### 6. 来源采集与完整性

- 复用现有历史证券身份和 Research Calendar，包括研究期间存在但后来退市的股票。新来源记录先映射到相同 Instrument Identity，不建立另一套股票身份或以现存上市名单替代历史范围。
- daily_basic 优先按交易日分片，显式请求来源合同中的 19 个输出列；fina_indicator 使用普通单股接口及有界报告期区间，显式请求 167 个输出列，包括必要 pre-start 报告。身份、日期、标记和分类元数据保存但不计入 226 个数值入口。
- 三表从已保存原始证据重建新增 35 项的投影与 seed；只有证据证明记录存在缺口时补采，不默认重新下载全部报表。
- 按已核对来源合同处理 daily_basic 单次 6000 行、fina_indicator 普通接口单次 100 行上限。达到上限须进一步拆分或验证受支持的分页；不能假定未获保证的 offset/limit 可用。最小分片仍无法证明完整时保留失败证据，不发布为完整数据。
- fina_indicator 的 start_date/end_date 按报告期过滤，不作为公告日期增量游标。公告发现触发受影响股票重查；目标报告尚未出现时保留该来源的 pending。三表成功或无变化不能自动清除指标来源的 pending，旧报告更正还需有界历史核对及独立 reconciliation watermark。
- 来源请求失败、权限不足、限流、超时或目标记录未返回时，利用现有 Operator 重试和检查点恢复，保留已有来源历史与未完成状态。区别采集未完成、来源确实缺失、公司类型不适用；不通过填零、换列或删除历史来制造完整性。
- 逐字段核实单位、期间、适用性和实际覆盖后才声明可用。重点未决事实包括 gross_profit 的金额尺度、equity_yoy 与换手率缩放、impai_ttm 的真实期间、季度/年度披露频率和 update_flag 的证据能力。它们是实施者需完成的来源资格验证，不是要求用户猜测的产品决定。

### 7. 按依赖读取、准入与成本

- Data 的统一读取接口接受冻结的 Generation、所需 Canonical Field References、Research Sessions 和股票集合，返回统一列式 Numeric Series；内部按每日值、三表报告、供应商报告的实际语义解析，不暴露可配置插件或供应商专用 DSL。
- 每次只读取所需列、股票与 Session 分区。财务保留稀疏报告版本，在读取范围内按可见时间对齐；不预先持久化全市场每天 204 列财务值。
- Field Catalog、质量快照与可用字段来自同一次 Dataset Head 读取并携带相同 Generation 身份；提交研究时固定 Head 后再次验证实际依赖。一个来源落后不能冒充所有来源已经更新，也不能阻断只依赖已就绪来源的公式。
- ResearchRun、Research Batch 与 DailyTrack 共用读取和时间对齐实现。共享缓存必须含 Generation 身份、字段和读取范围；不同数据版本不能复用旧值。
- 成本准入根据实际列数、坐标规模和 Calculation Warm-up 计算，不能按旧 12 字段模型遗漏新成本，也不能给仅用一列的公式按全部 226 列计费。
- TuShare 请求只发生在数据准备或刷新，研究计算不联网补取缺失数据。

### 8. Data 页面与 Agent 体验

- 保留 Market data、Financial data、Industry data、Strategy Benchmark 四个顶层区块。行情聚合 7 个价格入口和 15 个每日指标；财务聚合 41 个三表入口和 163 个供应商指标。不新增 Daily basic data、Financial indicator data 卡片或导航。
- 字段列表按权威目录的研究归类聚合多个家族，支持中文/DSL 名搜索和研究用途、来源、期间筛选。22 / 204 是目标数量，实际可用数量按 Generation 声明显示，总数与分类合计一致。
- Overview 在一份当前合同中保留各家族真实覆盖与状态，再生成类别摘要。某家族不满足自身就绪规则时，整个类别不能显示全部 ready；原区块内可给出必要的报表/指标或行情/每日指标状态，不用一个来源的日期代替全组覆盖。
- 字段信息包括含义、单位、固定期间、合并/归母范围、来源、可见规则、适用性和覆盖摘要。百分比可格式化为 15%，公式使用 0.15；不增加逐股票日的 TTM 期间差异展示。
- 公式补全、Data 页、HTTP/MCP 和内置 Agent 使用同一目录。Agent 按类别或名称获取需要的信息，不在每轮提示中注入全部 226 项。页面继续采用现有紧凑、文字可辨识的状态与列表规范。

### 9. 数据组合、发布与刷新

- 新候选复用当前 Generation 中未改变的行情、复权、交易状态、日历、身份、股票池和行业等家族/分区引用；重建三表必要投影与 seed，增加两个新家族，再生成实际字段声明和完整根清单。新旧版本可共用未改变的数据文件。
- 规范化数据按同一股票身份和研究日结合：每日指标精确匹配交易日，财务取当日已经可见的报告。不同接口相似列仍保持固定来源，不用 fina_indicator 覆盖三表科目，也不把报告结束日期直接当作行情连接日期。
- 候选先完成完整性、单位、时间、字段可用性和原字段回归验证，再通过现有生命周期保护与原子比较切换发布 Head。准备期间继续使用当前已发布数据。
- 其他家族并发更新使 Head 改变时，以最新根重组并重新验证，不能覆盖已新增的行情或行业。目标家族自身已变化时，重新构建或验证其继承关系后再发布，不能仅重新挂接陈旧候选。
- 切换前失败不改变 Head；切换已成功但任务完成回执失败时，按已发布坐标对账并补全状态，不误报未发布，也不自动倒退 Head。重复执行应收敛到同一已发布结果。
- 后续所有刷新只更新其负责的数据组，保留其他已验证家族引用、字段声明和各自覆盖。必须修正当前行情刷新只显式保留行业和原财务家族的行为，确保首次扩容后再刷新行情、财务或行业时新增字段仍存在。
- 已准入 ResearchRun 及其重试继续固定原 Generation；新 Run 固定新 Head。DailyTrack 保持 Tracking Origin、字段意义和已发布检查点，各次新 Attempt 使用其固定的当前已验证 Head，不改写既有跟踪历史。

### 10. 一次硬切与实施顺序

- 内部按来源资格与字段合同、daily_basic 完整链路、三表新增字段与 TTM、fina_indicator 完整链路、消费者和发布验收逐步完成。每层形成可运行的闭环；对外一次切换到最终当前合同，不长期运行两套实现。
- Data、Alpha Catalog、读取与准入、HTTP/MCP、Worker 和 Web 在统一部署窗口切换。暂缓新的研究准入、刷新发布与 DailyTrack 推进，按既有完成或恢复语义处理在途 Attempt；完成部署、Head 核对和就绪验证后恢复入口。
- 历史原始数据、结果和必要研究输入继续保留。原、新 Generation 在同一现行格式下声明不同字段子集，使用同一套校验与读取规则；修正全局 FINANCIAL_FIELDS 扩容导致旧根 readiness 校验失败的问题。旧快照缺少新字段时明确拒绝该依赖，不附加新字段或回退到当前 Head。
- 如数据库表或持久化格式确需升级，提供明确起止版本、备份、执行记录、重复执行行为与失败回滚验证的一次性迁移。不得修改 schema 指纹绕过检查、自动清库、原地改写被引用的不可变数据，或增加运行时旧版本分支。
- 开发和验证以 main 为集成基准；实际部署遵守仓库部署分支和发布规则。本规格整理不执行线上暂停、采集、迁移或切换。

## Testing Decisions

### 验收行为与验证边界

下表中的预期由固定输入、来源合同和已确认行为给出，不能由待测实现反算。纯计算和目录规则在公开模块接口验证；发布、状态、权限和引用保护使用真实依赖。

| 编号 | 可观察行为与独立预期 | 验证边界 / 层次 | 主要风险 |
| --- | --- | --- | --- |
| T01 | 226 个唯一合法作者名，19 个新增 TTM；原有 12 项意义不变；close_raw 仅有一个既有价格身份；日期/标记不计入数值入口 | Field Catalog、Alpha 编译公开接口；模块测试 | 重复身份、改写旧字段、目录数量虚增 |
| T02 | 同证券/期间/口径的来源对照证明每列单位与含义；源百分数 15 规范为 0.15，已为 0.15 的来源不再缩放，PE 15 保持 15；未获证字段不能声明可用 | 来源资格证据与规范化公开接口；离线模块测试＋有界真实接口核验 | 百倍尺度错误、金额/比率/期间误读 |
| T03 | 三表本期累计 60、上年全年 100、上年同期 50 得到 TTM 110；年末直接取全年；归母与合并利润、营业总收入与营业收入保持不同 | Data 财务读取公开接口；使用最小版本 Fixture 的模块测试 | TTM 算法、归属范围、源科目混用 |
| T04 | 上例任何必要项缺失则 TTM 缺失；上年全年更正为 105 后，从更正版可见日起变为 115；先前 Session 仍为 110；最新报告空值不回退 | Data 报告选择与读取；模块测试 | 隐式补值、未重算组成修订、未来信息泄漏 |
| T05 | TTM 流量分别截止三月底/六月底时比值缺失，同窗口时才计算；乘除常数或加括号不绕过；旧字段、显式跨期和截面排名合同保持 | Alpha 计算公开接口；模块测试，覆盖实际列式执行 | 混期运算、范围过宽、表达式改写绕过 |
| T06 | 公告当日不可用，下一 Research Session 可用；无公告日隔离；重复内容保留首次观察；同公告日后见更正不回填过去；冲突不凭排序选胜者 | 来源版本投影与 Data 读取；模块测试 | 公告/报告期混淆、修订伪造、非确定去重 |
| T07 | 起点和首年后续目标期所需 pre-start 报告都可读取；保留原年报/存量种子，且不允许 pre-2010 研究；覆盖历史退市证券 | 财务候选生成、Generation 重开与读取；真实文件的模块测试 | 缺少上年同期、存活偏差、范围虚增 |
| T08 | 返回恰达 6000/100 行时继续验证完整性；最小分片仍不确定则失败；超时、限流、无权限、缺字段、空目标报告保持未完成；重试不丢旧证据；指标 pending 不被三表成功清掉 | 采集公开服务＋Operator Worker；供应商 Fake 的模块测试与真实存储/数据库集成测试 | 截断误报成功、错误增量游标、重试和待更新状态错误 |
| T09 | daily_basic 缺少当日值时缺失，不借前日填充；财务按可见时间关联同一股票；只用 close 的研究可在指标未就绪时准入，使用未就绪 roe 时明确拒绝 | Data 读取、依赖解析、研究准入；模块测试＋HTTP/MCP 合同测试 | 错误关联、全局开关放宽或阻塞 |
| T10 | 同一 Generation、范围和字段在单次、Batch、DailyTrack 读取中一致；只读所需列/坐标，不跨 Generation 命中缓存；研究执行在禁用供应商网络时仍完成 | 公共 Data 读取、成本估算和既有 I/O 指标；模块测试及定向集成 | 全量展开、版本污染、计算时联网 |
| T11 | 无变化家族复用引用；扩容后再次行情、三表、指标或行业刷新仍保留非目标家族、新字段和真实覆盖；旧 12 字段根可重开，旧根不能使用新字段 | Mounted Generation / Refresh 公共接口；真实文件模块测试＋刷新集成 | 首发后字段消失、错误继承、旧根被全局目录破坏 |
| T12 | 其他家族抢先推进 Head 后重组不丢更新；同目标家族变化拒绝陈旧覆盖；CAS 前失败保持旧 Head；CAS 后回执失败恢复为已发布结果，重试无重复发布 | Dataset Lifecycle、Head 和 Operator Worker；真实数据库、文件/对象存储集成测试 | 并发覆盖、部分发布、错误回滚、回执不一致 |
| T13 | 新代码重试旧 Run 仍使用其冻结数据；新 Run 使用新 Head；Track 新 Attempt 采用固定的新 Head 并保留 Origin、既有检查点；被引用字节在准备、失败和清理期间受到保护 | ResearchRun / DailyTrack / Publication Lifecycle；真实依赖集成 | 研究意义改变、历史被覆盖、引用数据过早回收 |
| T14 | 最终 Alpha 缺失不进入有效样本或排序，覆盖损失正确；低于现有样本门槛时统计缺失；调仓仍按既有规则处理，普通缺失日不额外触发交易 | Factor / Strategy / Tracking 公开计算边界；模块测试 | 把缺失当零、统计虚增、新增隐式交易 |
| T15 | 页面仍四块；已验证全部字段时行情 22、财务 204，总数 226；只有三表或只有行情时明确部分就绪；搜索、补全、HTTP/MCP 展示一致，旧字段仍可提交 | Data 页面组件与目录合同；组件/浏览器测试＋少量 E2E | 表格漏新家族、假报 ready、多个目录漂移 |
| T16 | 硬切后所有消费者只使用当前合同；Operator 权限边界保持；如需迁移，旧数据升级、重复执行、失败恢复及引用完整性均有记录 | 当前 HTTP/MCP 合同、权限、Schema 生命周期与迁移；真实依赖集成；涉及启动时加镜像验收 | 隐藏兼容分支、越权发布、破坏旧数据或启动失败 |

TTM 所需报告完全缺失、供应商字段不适用与采集尚未完成必须分别有 Fixture 或来源证据；字段存在、目录可见和全历史非空不能用同一个断言代替。

### 复用现有测试与入口

- Data 模块优先扩展 `test_financial_series.py`、`test_financial_candidate.py`、`test_financial_collection.py`、`test_mounted_generation_store.py`、`test_dependencies.py` 和 `test_alpha_expression_contract.py` 中已覆盖报告选择、来源证据、字段准入和家族引用的 Fixture。
- 真实依赖复用 `test_data_refresh.py`、`test_daily_financial_refresh.py`、`test_data_refresh_worker.py`、`test_dataset_lifecycle_fence.py` 与 ResearchRun / DailyTrack / Publication 既有集成入口，不另建共享开发环境测试路径。
- Web 复用 `DataPage.test.tsx`、Research 组件浏览器测试和现有 Operator / MCP E2E 拓扑。端到端只覆盖关键闭环：查看实际目录并提交混合来源公式；发布新版后再刷新，旧研究与新字段仍可访问。纯 TTM 数学边界不在每一层重复。
- 用固定数据比较 1 列和多列公式的读取范围、I/O 与峰值内存，并校验实际字段成本准入；性能敏感改动再执行仓库性能入口，不凭字段总数估计吞吐。

| 时机 | 入口或证据 |
| --- | --- |
| 财务和字段规则迭代 | `uv run --project apps/core pytest -c apps/core/pyproject.toml --rootdir . apps/core/tests/data/test_financial_series.py apps/core/tests/data/test_financial_candidate.py apps/core/tests/data/test_mounted_generation_store.py apps/core/tests/data/test_dependencies.py apps/core/tests/kernel/test_alpha_expression_contract.py` |
| Data 页面组件与类型 | `pnpm --dir apps/web test:shell src/data/DataPage.test.tsx`、`pnpm --dir apps/web typecheck`；交互改变时 `pnpm test:browser` |
| 持久化、刷新、权限与恢复 | 仓库隔离 `pnpm test:integration`；必要的定向选择沿用其现有运行器 |
| 关键产品闭环 | `THESISTRACE_TEST_PLAYWRIGHT_GREP='本次新增用例名称' pnpm test:e2e`；另用真实浏览器验收当前 Data 页面和提交行为 |
| 跨模块最终交付 | `pnpm check`，按根测试规则组织；已验证且未变化的阶段不无故反复运行 |
| 真实 TuShare 来源资格 | 扩展并使用 `pnpm check:live-tushare` 的有界探针，保存脱敏字段 schema、请求分片、截断检查、单位对照、年份/公司类型覆盖和错误证据 |
| 启动、镜像或恢复边界变化 | 按影响选择 `pnpm test:image-smoke` 或 `pnpm test:image:qualification`；只有实际发布资格验证才使用 `pnpm check:release` |

工具版本按仓库固定环境执行。集成、E2E 和镜像测试使用既有隔离身份、数据库和对象存储；不得清理共享开发 Dataset Head 或数据卷。确定性测试使用供应商 Fake / Replay，真实接口凭据仅由既有安全配置提供，保存证据不含凭据。

### 来源资格与完成门槛

1. 逐字段核实 226 项的来源、名称、范围、期间、单位及适用性，记录支持与实际可用范围；不能由一个年报样本推定所有季度覆盖。
2. 对两个新来源保存分片完成账本、历史证券覆盖、按字段/年份/公司类型的非空统计与缺口原因，确认必要 TTM 组成和 seed。历史证据不足按已接受范围披露，不补造原始版本链。
3. T01–T16 的相关验证通过；完整候选、旧数据读取、刷新后保留新家族以及发布恢复闭环均有可核查证据。
4. 真实来源资格未通过时，不将受影响字段标为可用，不以减少清单或临时换源宣布 226 项完成；记录具体事实阻碍。这里尚无待用户决定的产品问题，未知来源事实由实施者调查。
5. 只有实施、验证、必要 review、提交和功能最终门禁完成后，才能按本地 tracker 规则标记 complete。本文仍为 ready-for-agent。

## Out of Scope

- 超出 226 清单的资金流、龙虎榜、融资融券、额外银行专用字段、额外原始单季计算、披露年龄或其他供应商数据。
- 修改原有年报字段为 TTM、同义别名、通用量纲推理、自动报告对齐回退、跨来源补值或财务缺失填零。
- 声称所有字段全市场全历史非空、所有公司类型都可比，或回填历史具备完整 PIT 修订链。
- 新的顶层 Data 卡片、导航、独立数据服务、用户配置采集插件、字段编辑平台、逐股票日的期间差异界面。
- 新策略类型、配权、调仓、交易或账户规则；新增字段缺失仅进入已有研究与交易规则。
- 双版本运行时、双读双写、旧 API fallback、自动清库、丢弃来源历史或被引用研究数据。
- 本轮规格整理中的采集、应用实现、提交、部署或生产切换；这些是后续按规格执行的工作。

## Further Notes

- **权威范围附件**：[226 字段中文清单](../../docs/research/dsl-field-catalog-226-2026-09-12.md)、[CSV](../../docs/research/dsl-field-catalog-226-2026-09-12.csv)、[结构化清单](dsl-field-inventory-226.json)。逐项名字和来源以这些同范围附件为准，实施不得另起一份人工目录。
- **三表范围附件**：[32 项定义](statement-extension-32.json)、[三个核心 TTM](core-flow-ttm-3.json)。新增 35 个三表入口的源列已经出现在保存列清单中；这只证明列存在，不证明每个值和全部历史已完整。
- **来源和讨论证据**：[来源约束核查](223-source-design-review.md)、[三表来源核查](three-statement-extension-review.md)、[原始接口探针](live-tushare-field-probe.json)、[grill 决定树与代码证据](grill.md)。核查基线为 2026-09-12，生产样本截止 2026-09-09；本次整理没有重新请求真实接口。
- **已确认决定**：[ADR-0243：显式 TTM 与必要组成](../../docs/adr/0243-give-statement-derived-ttm-flows-distinct-field-identities.md)、[ADR-0244：历史回填证据范围](../../docs/adr/0244-admit-announcement-aligned-financial-history-with-evidence-limits.md)、[ADR-0245：小数比例](../../docs/adr/0245-express-new-alpha-percentage-fields-as-decimal-ratios.md)、[ADR-0246：不同 TTM 窗口运算缺失](../../docs/adr/0246-return-missing-for-misaligned-ttm-flow-arithmetic.md)。
- **既有约束**：沿用 ADR-0014 / ADR-0191 的字段身份与作者名分离、ADR-0016 / ADR-0018 的可见时间与真实来源证据、ADR-0179 的原有年报/存量语义、ADR-0181 / ADR-0183 的家族独立覆盖和单一 Head、ADR-0190 的 ResearchRun 固定 Generation。ADR-0243 将 ADR-0184 对旧字段的起点 seed 规则扩展为新增 TTM 在整个覆盖范围内需要的最小依赖集合，保留 2010 年起研究的边界。
- **产品与工程规范**：[领域词汇](../../CONTEXT.md)、[页面设计](../../DESIGN.md)、[测试与发布规则](../../AGENTS.md)、[本地 issue tracker](../../docs/agents/issue-tracker.md)。本功能不改动并行的策略账户规格或其尚未落地的规则。
- **文档优先级**：本文负责需求、实现边界与验收；226 清单负责逐项字段；grill 和来源核查保留讨论与事实。191 / 223 清单及已经撤回的期间展示提案不得作为新的实施范围。
