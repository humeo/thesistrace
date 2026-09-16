# ThesisTrace 研究过程中的产品问题记录

记录日期：2026-09-10。范围：Data → Research Runs → 成功策略详情 → Research配置，以及本次真实MCP量化研究链路。

用户目标：TOP3000研究到最新日，寻找尽可能多的Sharpe>1.2策略；加入近期与市场状态适应；现聚焦本金10万元、最大回撤目标20%。本记录随研究持续追加，当前未实施产品修复。

## 首要结论

最先需要补齐的是**真实本金配置与小资金执行验证**。当前产品固定1000万元，无法完成用户的10万元研究。其次是**多窗口/滚动验证和组合状态切换**。这些是该研究目标需要的能力，不能仅靠修改名称、切图或拼接净值代替。

共记录12项（首轮8项、后续4项）；P1为当前研究会受到直接阻碍或误判的事项，P2为明确交互改进或研究范围扩展。问题均单独存放为needs-triage，未声称已修复。独立研究进程已能用本地真实行情检验10万元本金，但不是产品已支持本金配置，且仍采用合成总收益账户。

|项|优先级|发现与影响|证据分类|
|---|---|---|---|
|[01 必须：配置本金与账户可交易范围](issues/01-capital-and-account-constraints.md)|P1|能力缺失；阻塞10万元适配|实际MCP、截图或当前代码|
|[02 必须：区分近期净值切片、独立建仓与滚动样本外](issues/02-multi-window-comparison.md)|P1|能力缺失；当前用户研究所需|实际MCP、截图或当前代码|
|[03 必须：直接表达与检查组合状态切换](issues/03-portfolio-regime-switching.md)|P1|已有公式可表达特定宽度择时；缺少可发现的状态、现金与多策略接口|实际MCP、独立计数与本地账本对照|
|[04 研究列表需要可比较的结果与清晰收益口径](issues/04-run-list-and-metric-context.md)|P1|已复现的交互问题与能力缺失|实际MCP、截图或当前代码|
|[05 MCP净值导出与错误诊断不足](issues/05-agent-results-export-and-errors.md)|P1|已复现的契约可用性问题|实际MCP、截图或当前代码|
|[06 批次进度需要说明已完成工作与等待原因](issues/06-batch-progress.md)|P2|观测到的交互不足；未判断计算卡死|实际MCP、截图或当前代码|
|[07 数据字段与常用算子限制了可验证策略范围](issues/07-fields-and-formula-operators.md)|P2|能力缺失|实际MCP、截图或当前代码|
|[08 研究结果与参数页面的信息优先级需要调整](issues/08-page-priority-and-feedback.md)|P2|截图支持的设计建议|实际MCP、截图或当前代码|

## 后续研究新增

QS28后段继续补强已有问题，未新增重复条目或截图。相同年度新高输入在批次准入被拒、改为单任务后完整成功；效率水平单任务则实际资源失败，说明问题09需要区分两种执行边界。两组非流动性单位变体的公开逐日账户路径精确相同，以及129份来源/71个复用案例的独立核对，进一步支持问题12的实验来源与重复构造标识。证据：[账户差异与执行边界](../ROUND28_SEGMENT3_DIAGNOSTICS.md)、[缩放变体逐日比较](../ROUND28_SCALE_PROOF.md)、[独立清单复核](../ROUND28_INVENTORY_REVIEW.md)。这些是MCP与研究账本证据，没有追加未经截图验证的UI结论。

QS28早先新增[策略结果页两步复核](ROUND28_UI_AUDIT.md)，当时累计9张截图：首屏为冻结参数、名称编辑与正因子摘要；下滚后可读到ROE账户−41.31%收益、51.89%回撤及−1.799 Sharpe，数值与MCP一致。补充问题08的信息优先级证据；问题12另加入109个定义、218个固定账户案例的覆盖清单，区分未测、复用与资源失败。没有新增产品代码修改或把代理滚动错误归责产品。

QS20追加两张真实界面截图，当时累计6张。该次研究列表为484条、25页；943×949面板中长研究名称与Type列重叠，右侧指标被截。因子详情没有呈现MCP已有q1-q5与配对差收益，恰好会影响风险稳定性与低波动对照的选择：后者Rank IC较高但q5略负。已补入问题04/10；详情已有Create a draft入口，问题12因此明确针对来源关系及复用可见性，而非声称没有复制草稿能力。

![本轮研究列表](/Users/koltenluca/code-github/thesistrace/.scratch/top3000-sharpe-search-20260910/product-audit/screenshots/05-round20-research-runs.jpg)

![本轮因子详情](/Users/koltenluca/code-github/thesistrace/.scratch/top3000-sharpe-search-20260910/product-audit/screenshots/06-round20-factor-detail.jpg)

截图原始字节、尺寸与哈希见[本轮清单](round20-screenshot-manifest.json)；完整页面文本为[列表](round20-runs-ax.txt)与[因子详情](round20-factor-ax.txt)。未改动原有草稿，未测试更宽视窗或移动端。

QS19已补齐14个由正向因子筛选得到的实际策略，均未达Sharpe1.2；来源关联目前依靠本地实验记录保留。问题10增加因子到TopN账户表现落差，问题12记录从已完成因子继续策略的来源与实际复用状态缺口。相同冻结条件的因子摘要核对证明已观察范围内的结果可重复，不证明跨批次缓存命中。当前数量和逐项证据见[实际策略结果](../ROUND19_RESULTS.md)、[重复结果核对](../FACTOR_COMPARABILITY.md)。

QS21增加第7张真实截图：效率变化10只策略已资源失败。页面的52%总体进度可由MCP中252日预热与4/242研究日解释，但页面未展示预热计数；失败原因也没有给出用量、预算或保持研究条件的恢复指引。页面已正确显示终态和耗时，未误称仍在计算。两个相同方向的持仓参数均资源失败，没有Result；收入增长方向通过单任务入口恢复后完成但亏损。分别补入问题06/09，不将运行故障记为经济负结果。[本轮研究结果](../ROUND21_RESULTS.md)、[四项恢复证据](round21-capacity-recovery.json)。

![资源失败页](/Users/koltenluca/code-github/thesistrace/.scratch/top3000-sharpe-search-20260910/product-audit/screenshots/07-round21-resource-failure.jpg)

原始截图的哈希、字节数、URL与观察时间见[第7张截图清单](round21-screenshot-manifest.json)，[页面完整文本](round21-failure-ax.txt)保留冻结参数、状态、进度及Create a draft入口。没有覆盖用户草稿或修改研究条件。

最新追加证据：调仓邻近检验中，20只/9日季度Sharpe3.300而全年0.233，四个邻居均未同时通过两个窗口，强化问题02的实验比较需求。状态费用归因将10万元两个账户的费用6475元/11770元与净盈利20348元/23702元分开，补充问题03。问题10还加入并列评分导致q5为空的可复现例子，指出整体分组有效日不足以表达各组与配对差值的样本日期。这些是新MCP、只读代码和独立研究证据，没有新增UI截图或产品修复。

新增附件：[调仓邻近比较](../SWITCH_NEIGHBORS.md)、[状态损益与费用](../REGIME_ACCOUNT_ATTRIBUTION.md)、[分组有效样本诊断](../QUANTILE_COVERAGE.md)。

- [09 批次容量诊断](issues/09-batch-capacity-diagnostics.md)：12项均合法但整批容量不足，拆成6+6后保持TOP3000成功接受。
- [10 因子尾部诊断](issues/10-factor-tail-diagnostics.md)：正IC和正q5不代表极端TopN可盈利，需要匹配集合与执行的对照。
- [11 合成账户与结算说明](issues/11-synthetic-account-and-settlement.md)：复权收益结算不能直接解释成券商现金账本；需明确模型并导出可对账的结算调整。
- [12 从因子继续策略的来源与复用状态](issues/12-factor-to-strategy-lineage.md)：当前已有批内共享与恢复产物；需要保留跨实验筛选来源，明确实际复用范围，不能把相同摘要当作缓存命中证据。

## 页面走查

QS28 新增四步实测：[切换策略首屏、Sharpe、回撤与费用帮助](ROUND28_METRIC_HELP_AUDIT.md)。三个说明均能展开与关闭，内容和现有计算口径一致；关闭后焦点返回原帮助按钮。保留这些准确说明，将优先级与账户假设问题补入既有条目。四张新截图均保存后重新打开确认，当前累计13张截图；不新增重复问题。

|步骤|当前健康度|可保留的优点|主要问题|
|---|---|---|---|
|Data overview|可用，信息层级待改进|行情/财务/行业/基准状态分开；覆盖期与待处理数可读；字段解释清楚|技术详情抢占首屏，尚不能按研究目的看到缺失能力|
|Research Runs|有明显研究效率问题|状态、类型、因子和策略结果分开；页面可到达真实结果|截图当时323条需多页翻查；缺实验比较；窄面板指标在右侧被截；Excess省略年化口径|
|成功策略详情|可用，但账户假设不足|冻结参数、日期、指标帮助、Factor coverage与净值图存在|首屏优先名称编辑和因子；资金/费用/执行假设未就地说明|
|Research配置|常规因子与固定策略可用；10万元需求受阻|单区间可选，1Y/3Y/5Y/Max快捷键，Factor/Strategy区分清楚|无本金/账户范围/组合切换；空参数只给笼统不可运行提示|

## 截图与来源

已保存截图原始字节，并逐一打开本地文件确认：不是仅凭DOM文本推断布局。视窗约943–958像素宽，侧栏展开；这是Codex嵌入面板的实际使用状态，不代表所有桌面尺寸。

### 1. Data

![Data overview](/Users/koltenluca/code-github/thesistrace/.scratch/top3000-sharpe-search-20260910/product-audit/screenshots/01-data-overview.png)

页面：[Data](https://thesistrace.com/data)。截图首屏未覆盖全部字段，字段数/释义同时读取了页面无障碍树及MCP catalog。

### 2. Research Runs

![Research Runs](/Users/koltenluca/code-github/thesistrace/.scratch/top3000-sharpe-search-20260910/product-audit/screenshots/02-research-runs.png)

页面：[Research Runs](https://thesistrace.com/research-runs)。右侧Result summary在当前面板中不能同时显示；不能据此声称较宽视窗也一样。

### 3. Strategy Result

![Strategy result](/Users/koltenluca/code-github/thesistrace/.scratch/top3000-sharpe-search-20260910/product-audit/screenshots/03-strategy-result.png)

页面：[QS5 63s lowvol20 H100 R10](https://thesistrace.com/research-runs/run_96384289b08844dca9dc)。完整无障碍树能读到Strategy Summary：净累计5.53%、年化超额48.87%、回撤5.65%、Sharpe1.401；首屏策略指标在下方。

### 4. Research authoring

![Research configuration](/Users/koltenluca/code-github/thesistrace/.scratch/top3000-sharpe-search-20260910/product-audit/screenshots/04-research-authoring.png)

页面：[Research](https://thesistrace.com/research)。读取用户原有草稿，未覆盖其公式、日期或名称；无本金字段。已有日期快捷键，不能将多窗口比较缺失误写成“不能选时间段”。

## Agent交互与证据边界

- 真正的产品MCP问题：参数limit=100只有通用INVALID_INPUT、没有字段上限说明；limit=50成功；长净值需要43页。完整请求、响应和trace见[mcp-pagination-error.json](mcp-pagination-error.json)。
- 共享因子批次约47分钟仍0/20完成，但任务并非已被证明卡死；需要看子Run进度，不因超时重复提交。该观察记录为进度解释问题。
- 初次浏览器inventory因request-header policy失败，重试后正常；这是Codex浏览器连接层现象，不归责ThesisTrace。一次CUA点击参数格式错误也是agent调用错误，不列为产品缺陷。
- 因子IC不是Sharpe、短窗口年化不是实际收益、个股条件评分不等于组合轮动、历史1000万路径不等于10万路径。报告和agent都必须保持这些语义。
- 浏览器审查以读取与研究提交为主；QS28前段另通过UI更正了10条本次新建研究的名称，未改变冻结公式、账户参数或结果，见[名称修改记录](../round28-name-corrections.json)。后续两段未修改应用元数据。未实测移动端、全键盘流程或屏幕阅读器，未测对比度数值，不能给出正式WCAG结论。
- 保留优点：指标帮助里已有计算公式、成本构成及年化说明；Data已有PIT/单位语义。建议是把关键假设前置，并补研究能力。

量化证据：[研究报告](../REPORT.md)、[10万元约束](../SMALL_ACCOUNT_RESEARCH.md)、[独立净值核验](../nav-audit.csv)。

QS28 后续补充：[三个个股切换公式](../ROUND28_SWITCH_PROOF.md)在固定本地日期共 8,580 个最终评分、20,637 个分支排名与状态值独立核对一致。已将状态层级、排名样本和缺失解释补入[问题03](issues/03-portfolio-regime-switching.md)，不新增重复问题或未经截图确认的界面结论。另有[正 Sharpe 但负复利收益的账户复核](../ROUND28_ACCOUNT_DIAGNOSTICS.md)，摘要与完整净值一致，未发现该案例的汇总计算错误。
