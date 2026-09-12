# 04 — 提供 19 个 TTM 流量及不同期缺失规则

**What to build:** Researcher 能用明确的最近十二个月流量研究收入、利润和现金流；系统从可见三表重构 TTM，组成缺失或两个 TTM 直接运算的窗口不同就沿用现有缺失行为，无需新增前端期间差异展示。

**Blocked by:** 01 — 统一现有字段目录、准入和家族合同

**Status:** complete

**Execution contract:** 在从 main 创建并核实的新 worktree 中，严格按 01→08 串行执行。每票开始实现前先记录 Plan；完成实现后逐项验收，进行代码审查、修复及复审，更新 tracker 并形成该票独立 git commit，完成后才开始下一票。审查同样串行，不并行委派实现或审查。

**Latest user decision:** 按用户最新要求，直接实现当前合同，不做兼容、版本迁移或 vXX 升级链；这覆盖母规格中有条件引入迁移的旧提议。保留数据、原有字段语义与必要研究引用的要求继续有效，不将“不迁移”解释为允许清库。

**Execution order:** 04；必须先完成 03 的验收、复审、tracker 更新和独立提交。

- [x] 接入三项核心字段 revenue_ttm、net_profit_ttm、operating_cash_flow_ttm，以及权威三表扩展清单的 16 项 TTM：cash_paid_capex_ttm、cash_received_sales_ttm、cash_paid_goods_ttm、cash_received_asset_disposals_ttm、cash_paid_acquisitions_ttm、cash_paid_investments_ttm、cash_received_borrowing_ttm、cash_paid_debt_repayment_ttm、operating_revenue_ttm、consolidated_net_profit_ttm、operating_cost_ttm、rd_expense_ttm、investment_income_ttm、fair_value_gain_ttm、nonoperating_income_ttm、nonoperating_expense_ttm。
- [x] 原 revenue、net_profit、operating_cash_flow 仍取最新可见年报。三个核心 TTM 分别沿用原收入、归母和合并现金流范围；营业收入与总收入、合并与归母利润、研发费用与供应商研发投入保持独立含义。逐列有来源、单位、合并范围和适用性证据。
- [x] 对各字段独立选择最新可见目标报告，年末直接取全年；中期取本期累计加上年全年减上年同期累计。股票、源科目、单位、报告范围和可见版本必须匹配，不能将每日填充序列滚动求和。
- [x] 任何组成记录或值缺失就返回缺失，不退到旧报告、年报、上一期 TTM 或其他来源；本期、上年全年、上年同期任一可见更正都触发重算。后来的完整数据或修订不能改写之前 Session。
- [x] 从已存原始报表重建投影，只有确证缺口才补采。种子覆盖整个声明 Coverage 所需 pre-start 依赖闭包，并与原年报/存量种子取并集；起点可能需要 2008 年报/三季报，计算 2010 一季报仍保留所需 2009 一季报，不扩大研究起始边界。
- [x] Data 返回 Numeric Series 时附带同期判断所需的最小期间信息；组成和供应商证据留在 Data。两个 TTM 流量直接算术运算时，只有双方有效且十二个月窗口一致才计算，否则该股票日的运算缺失。
- [x] 括号、正负号及乘除常数不能绕过应有的同期检查。单字段仍选自己的最新报告；常数、每日行情、期末存量、原有公式、显式跨期 Builtin 和截面排名保留现有语义，不增加全公式或全市场统一报告日限制。
- [x] 以独立预期验证本期 60、上年全年 100、上年同期 50 得到 110；全年更正为 105 后，仅从更正可见日起得到 115。另覆盖年报直取、必要项缺失、目标为空、跨来源范围不同及首年后续种子。
- [x] 同窗 TTM 运算有结果，三月底与六月底窗口运算缺失，并覆盖列式执行中的括号和常数变形。单次、Batch、DailyTrack 使用同一读取和对齐逻辑，缓存不跨 Generation，研究不联网补取。
- [x] 最终 Alpha 缺失不进入有效样本或排序，沿用 missing_expression、现有样本门槛和调仓规则；普通缺失日不产生即时交易，也不被当成零。经营现金流减资本支出不自动命名为严格 FCFF/FCFE。
- [x] 19 项能在 Financial data、补全、HTTP/MCP 和 Agent 中按其固定 TTM 含义查询和提交；演示一个同窗组合公式以及不同窗时的既有缺失结果，不增加期间差异 UI。
- [x] 后续 Financial Refresh 保留来源版本、TTM 所需组成与其他家族；公开计算、真实文件候选重开、受影响合同和关键研究路径的验证通过。

**Verification:** 母规格 T01、T02、T03、T04、T05、T06、T07、T10、T14、T15。与 03 无业务前置关系；本票完整拥有 TTM 读取到表达式缺失的边界，不拆成只有计算或只有前端的任务，不单独上线。

## Comments

- 2026-09-12：用户确认发布工单。已纳入最新的串行执行、每票 Plan / 验收 / 审查修复复审 / tracker / 独立提交，以及不兼容、不做版本迁移的要求。

## Plan — 2026-09-13

前置03已完成验收、串行Standards/Spec修复复审及独立提交2f60bdb7。核实工作树仅余历史研究草案，无未提交实现；继续同一隔离worktree，05—08不开始。

1. 核对19个固定TTM身份、源列和金额/报告范围证据；跟踪Data Numeric Series到Alpha行式/列式计算的实际期间传递边界，采用最小内部期间信息，不新增UI合同或版本分派。
2. 先建立公开读取失败回归：60+100−50=110；上年全年可见更正105后才为115；年报直取、任何组成/目标空缺、跨范围不匹配、目标与依赖独立修订、原年报字段不变。实现同一稀疏报表读取中的TTM计算，并保持仅请求列/股票/Session范围。
3. 从保存原始回执重建TTM所需pre-start依赖闭包，与03原年报/存量种子并集。覆盖2010起点及首年后续目标，保留历史退市身份、旧不可变根和来源证据；只补确证缺口，不重采全部三表。
4. 在统一Numeric Series和Alpha算术中传递/检查TTM窗口。先测试同窗有值、异窗缺失及括号/符号/常数变形不能绕过；保持非TTM、显式跨期Builtin和rank的现有语义，沿用missing_expression与样本门槛。Run/Batch/Track共用一条读取与计算规则。
5. 贯通19项目录/补全/HTTP/MCP/Agent和Financial Refresh；验证同窗混合公式及异窗既有缺失行为，Data仍四块，不增加期间差异界面。此时目标目录63=22 Market+41三表Financial。
6. 运行相关计算/候选/真实Worker与页面验收，按Standards→Spec串行审查、修复复审、tracker更新和独立提交，再开始05。全历史采集与统一上线仍由07/08负责。

## TTM reading first implementation — 2026-09-13

- 已核实03独立提交2f60bdb7及04 Plan，串行开始实现。按权威附件静态接入19个TTM定义（总63作者入口），来源单位/公司适用性资格仍需逐列完成，不能将目录注册视为就绪。
- 公开行式/列式读取先2 failed（FINANCIAL_FIELD_UNSUPPORTED）；接入TTM稀疏状态转换后两入口均能保持原年报值、年报直取、60+100−50=110、上年全年可见更正105后115、新目标空值转缺失。额外覆盖缺年报、缺上年同期、目标为空及组成公司范围不一致。
- 每个可见事件更新报告期状态后重算当前最新目标，因此旧组成修订也生效；相同报告/公司范围不足或任一金额缺失时不回退旧TTM。列式按Arrow证券分组后只将单证券所需稀疏报告转行，避免全切片建立Python行对象。仍需更广列式/成本及期间链路验收。
- 全Series组最终22 passed / 0.74秒，session60429终态exit0，JUnit /tmp/thesistrace-issue04-series-first.xml；Ruff/diff check通过。此前中文长行lint失败已修复，未称首轮全绿。
- 未完成：TTM pre-start依赖闭包、窗口元数据在统一Research Series与Alpha算术的传递/缺失规则、来源资格、候选/刷新与全入口合同同步、真实研究/页面验证、串行审查与独立提交。现有其他测试的22/44字段断言及完整源Fixture尚未全部更新，不声明全回归通过。下一步先完成种子和期间表达式边界。05—08未开始。

## Coverage-wide TTM seed closure — 2026-09-13

- 用完整Raw→Candidate→公开resolver回归证实旧种子仅保留20081231/20090930，丢掉起点需要的20080930及首年后续2010Q1需要的20090331；首轮1 failed。
- TTM种子按每个端点/证券收集起点最新报告及Coverage内目标报告所需组成，选择各报告期/公司范围最后可见的pre-start版本，并与原年报/存量种子去重合并；保留后上市证券必要历史，不扩大研究日期。保存旧根仍通过独立事实完整性入口，不重写旧种子或引入版本分派。
- 实际候选重开/重复物化及行式列式读取验证2010-01-04/2010-04-20/2010-04-21为150/120/130，pre-2010请求被拒绝。更早且不再需要的2007报告不进入新投影，原始回执保留。
- 首次候选+Series全组67 passed/11 failed：完整源Fixture未含新增流量列、旧seed描述断言及按金额跨证券计数预期失效。同步Fixture明确列集合、seed描述和按目标证券计数，保留生产严格合同；将后上市证券保留的900种子纳入预期。
- 复跑78 passed / 12.92秒，session74273终态exit0，JUnit /tmp/thesistrace-issue04-seeds.xml；Ruff/diff check通过。只覆盖候选/Series，不声称HTTP/MCP或全刷新通过。
- 下一步完成最小TTM窗口信息在统一Research Series和Alpha行式/列式算术的传递与缺失规则；来源资格、全入口、真实Worker/页面、串行审查和独立提交仍未完成。05—08未开始。

## TTM window propagation and arithmetic — 2026-09-13

- 三个公开计算入口的同期/常数变形先6 failed（窗口参数尚不存在）。增加最小结束报告期窗口数组：0表示无有效窗口；普通算术保留窗口，双方都是TTM时要求正值且相等，缺失沿原路径传播。正负号及常数乘除保留约束，abs/log/sign保留窗口；显式lag/其他跨期Builtin及rank产物不施加TTM窗口一致性限制。未增加全市场报告日或前端期间协议。
- 读取端窗口列回归先1 passed/1 failed（缺列）。FinancialSeriesResolver在实际TTM对齐表附带ttm_window_end字段列；row composite与ColumnarResearchData携带窗口，切片保留，Data identity含非空窗口证据。Alpha行式、截面矩阵及列式执行共用同一节点窗口规则；列式仍随最后一次消费释放临时窗口，避免全计划保留中间数组。
- 新test_ttm_research_series通过实际行式/列式ResearchData验证同窗结果5、不同窗结果缺失且missing_expression=1，切片后值/覆盖/校验和一致；窗口不同影响数据身份。此用例覆盖Data→Alpha接口，不等同完整HTTP/Worker端到端验收。
- 增加行情混算、lag、rank、abs边界测试，防止将期间限制扩大到非TTM或显式变换。最终候选+Series+TTM ResearchData+SeriesPlan+AlphaExpression组135 passed / 12.60秒，session99291终态exit0，JUnit /tmp/thesistrace-issue04-windows.xml。
- 仍未完成逐字段来源资格、完整目录/Fixture及HTTP/MCP/页面同步、真实刷新与Run/Batch/Track验证、串行审查和独立提交；05—08未开始。

## Catalog, browser, and HTTP Worker verification — 2026-09-13

- 同步公开HTTP目录的19项TTM身份断言和浏览器公共catalog Fixture为63字段（22 Market+41 financial）；AlphaLanguage/HTTP合同组68 passed / 0.54秒。目录数量不代表来源资格或全历史采集完成。
- Data浏览器先2 failed：搜索营业总收入实际还匹配operating_revenue_ttm说明中的范围区分，共3项；保存的error-context核对结果正确，修正预期不修改搜索规则。复跑1280/390两宽度2 passed / 8.3秒，session46380终态exit0；验证63字段、现金流来源11项、盈利12项、TTM期间19项、旧存量期间19项及四块布局。
- 既有HTTP完整候选Fixture新增19流量来源所需列，保持原源值；新mismatched_ttm场景添加可见2009Q1/2010Q1收入，收入TTM窗口为20100331而现金流TTM仍20091231。实际通过HTTP提交含常数变形的rank((revenue_ttm*2)/(operating_cash_flow_ttm*2))并由独立Worker执行，同窗最终持仓，异窗最终空仓；两种都固定正确Generation并成功提交结果。
- 隔离运行20260912t190023z-29752-7eb06b86最终3 passed / 9.667秒，session56198终态exit0，cleanup_status=0。包含上述两场景及既有每日字段HTTP Run/Track回归。以evidence/pytest.xml、run.txt为证；不包含依赖重启阶段或完整Batch/TTM Track验收。Ruff和diff check通过。
- 仍需MCP/Batch/Track的TTM场景、Financial Refresh完整源Fixture同步、逐字段单位/范围来源资格、必要全链路回归及串行Standards→Spec审查修复复审和独立提交。05—08保持未开始。

## MCP and financial refresh verification — 2026-09-13

- 已核对独立 worktree 的前三票提交，继续 04；原 checkout 的工单副本不代表隔离实现进度。
- MCP 参数化存量和 TTM：通过实际 stdio 查询、提交，断开后独立 Worker 执行，再连接读取成功结果。隔离运行 20260912t190303z-31283-044ba183 为 2 passed / 12.661 秒，退出与清理均为 0。
- 完整财务刷新 Fixture 补齐明确的 TTM 来源列；公开读取核验候选与发布后经营现金流 TTM 为 6、窗口为 20091231。原 session97750 已确认终态 exit0：49 passed / 18.16 秒，运行 20260912t190425z-31979-cc9aeb3c，隔离资源已清理。此结果不包括独立依赖重启阶段。
- 下一步扩展实际 TTM Run 验收到 Track：新 Head 交换同窗/异窗状态，核对推进结果及旧检查点、Origin、冻结 Run 保留；新增断言尚待运行。Batch、来源资格、审查及提交仍未完成。

## TTM Track progression — 2026-09-13

- 将同窗/异窗 HTTP Run 验收延伸至真实 DailyTrack Worker：先冻结原研究并启动 Track，再发布交换窗口状态的新 Generation，推进两 Session。原先同窗持仓转为空仓，原先异窗空仓恢复持仓；旧 Run 仍引用原 Generation，Origin 与既有检查点内容保持不变。
- 定向集成运行 20260912t190904z-38345-e352c918 的 pytest 报告为 3 passed / 15.26 秒（含原每日字段 Run/Track），Ruff 与 diff check 通过。测试结束后的资源清理状态另按运行记录核对。
- 本轮有新增验收与证据，尚未完成 04 的 Batch、逐字段来源资格、串行审查及独立提交；不开始 05。

## Batch acceptance and bounded source observations — 2026-09-13

- 新增实际 Strategy Sweep 两个策略复用 TTM Alpha 的验收，比较 daily 子研究结果与单次研究完整结果，另断言同窗持仓、异窗空仓及冻结 Generation。首轮运行 20260912t191050z-43630-cb2dbd02 为 2 failed / 1 passed：两个 Batch 状态均 failed，尚未到结果等价断言；不能据此声称共享计算通过。
- 改为输出完整 JSON 失败响应后启动同一隔离入口诊断复跑，运行 20260912t191207z-44636-e3365489，session97196。需继续观察该进程，不因等待而另起重复运行。
- observe_statement_flows.py 使用已有明确来源清单和安全配置发起 4 公司类别 × 年报/Q1 × income/cashflow 共 16 次有界只读请求，全部 observed 且 missing_columns 为空。保存 statement-flow-source-observations.json；包括来源多版本与空值，未改 Head。该证据仅证明观察到源列和值，逐项独立金额/单位/范围资格仍未完成。
- 前次 Run/Track 运行 20260912t190904z-38345-e352c918 的 run.txt 已核实 status=0、cleanup_status=0。04 仍未完成，05—08 未开始。

## Batch window contract fix — 2026-09-13

- 诊断复跑 20260912t191207z-44636-e3365489 确认 Shared Alpha-and-Factor 计算失败。代码核查发现 Batch 的共享列式视图未实现新增 ttm_window_matrices，因而不满足当前 ColumnarResearchSeries 合同。补齐一次准备的窗口矩阵及按证券/Session 选择；切片复用同一准备数据，无兼容或回退分支。
- 修复后 20260912t191344z-52383-8f34196d 的两个 Batch 均 succeeded，继续验收时发现测试误用必须关联普通 Run Attempt 的查询读取 Batch 子研究，返回 None。修正测试直接查询实际结果记录，保留完整结果和冻结 Generation 对照。
- 最终隔离运行 20260912t191503z-55022-6ceed923：3 passed / 19.33 秒，session53337 终态 exit0，隔离资源已清理。同窗/异窗两种共享计算均成功，daily 子研究完整结果与普通 Run 相等；另一策略持仓符合窗口规则，Track 新 Head 推进保留旧研究及检查点。未宣称完整 Batch 回归或依赖重启通过。
- 对照贵州茅台 2025 官方合并利润表/现金流量表（印刷页 61、62、64、65），16 个非空源金额与 TuShare 完全一致，已保存 statement-flow-unit-crosscheck.json（含来源链接及独立预期）。余下 n_disp_subs_oth_biz、c_recp_borrow、c_prepay_amt_borr 及公司类型范围仍需核查，不以空值视作资格完成。
- 04 仍需剩余来源资格、必要回归、串行 Standards→Spec 审查修复复审、tracker 与独立提交；05—08 未开始。

## Remaining source amount qualification — 2026-09-13

- 平安 2026Q1 官方合并现金流量表（PDF 页 23—24）以人民币百万元列借款收到 19990、偿还债务支付 184195；与 TuShare CNY 值对应，支付来源为正金额，保留供应商符号。statement-flow-financing-crosscheck.json 保存独立对照。
- 追加一次中国建筑 2025 年 cashflow 有界请求。其官方合并财报附注 69(2)，PDF 页 151／印刷页 149，取得子公司及其他营业单位支付净额 7425135 千元，与来源 7425135000 元一致；statement-flow-acquisition-crosscheck.json 保存来源 URL、PDF SHA-256、页码和金额。网页 PDF 读取失败后用同一已知官方 URL 下载临时 PDF 并读取文本，无 Head 写入。
- 19 个 TTM 源科目均有非空独立金额对照，statement-flow-qualification.md 汇总逐字段证据及边界。TuShare 官方 cashflow 文档确认 n_disp_subs_oth_biz 为收购支付，区别于 n_recp_disp_sobu 处置收入。观察样本含工业、银行、保险、证券年报和 Q1；金融公司空的成本／研发列不换成总营业支出，不宣称跨公司类型完全可比。全历史资格与覆盖仍归 07。
- Batch 分块生命周期和 TTM Data 切片定向组 3 passed / 0.38 秒。开始 pnpm test 跨模块快速检查，之后再进入串行 Standards→Spec 审查；本票尚未提交。

- 快速检查进程 session53456（mise exec -- pnpm test）仍在运行；工具测试 29 passed、Ruff 通过，Python 全组已超过 93% 并出现失败标记，尚未输出完整失败汇总。必须继续观察同一 session 并修复受影响回归，不能宣称快速检查通过或开始完成审查。

- session53456 已终止 exit1：Python 全组 1294 passed / 12 failed / 123.11 秒。11 项为分块测试的 _ColumnarFixture 缺少当前窗口接口，已补显式空窗口（Fixture 无 TTM）；另 1 项发现 composite 表转字典时过滤了 daily_basic 已存在行的显式 None，已保留表内空值，不填充不存在坐标。后续 TypeScript/Web 阶段未运行。
- 启动两个受影响文件定向复跑，JUnit /tmp/thesistrace-issue04-quick-fixes.xml，需核对终态再继续快速检查剩余阶段及审查。

## Quick checks resolved and Standards review started — 2026-09-13

- 首次定向修复复跑 81 passed/1 failed：直接保留所有对齐空值会将无来源行的补齐坐标写入稀疏行字典。改为 daily_basic 对齐表携带 source_row_present，composite 保留非空值和确有来源行的显式空值，不制造不存在记录。修复后两个受影响文件 82 passed / 9.14 秒（session16501 exit0；JUnit /tmp/thesistrace-issue04-quick-fixes.xml）。
- 最新全 Python Ruff 通过。首次 pnpm test 的工具测试29通过、Python1294通过的证据，与上述12失败所在完整文件复跑共同记录；未声称重新执行整个 Python 组。
- 按 quickCommands 原顺序续跑未执行阶段：Agent648、离线预检11、Auth200、Web355全部通过，Agent/Auth/Web及tests TypeScript类型检查通过，session77126 exit0。Web部分组件仍输出socket hang up但其断言通过；未将其当独立网络验收。
- 已固定工单04工作树审查快照 /tmp/thesistrace-issue04-review-fbgjb244（scope.json、staged/unstaged diff、文件及哈希，排除旧研究草案）。Standards子审查 issue04_standards 已开始；严格等其结束后再进行 Spec，不并行审查或实现下一票。审查期间尚未标 complete 或提交。

## Standards R1 and probe deduplication — 2026-09-13

- Standards R1: 0 documented hard violations, 1 P3 judgement smell (duplicated source probes). Production paths had no additional reported issues. Consolidated both bounded observation sets into observe_statement_flows.py; --construction selects the one-company annual cashflow request and dedicated output. Removed the newly created duplicate script, retained all original observation evidence. py_compile/diff check passed, no repeat remote requests needed for this script consolidation.
- Fixed R2 snapshot /tmp/thesistrace-issue04-review-r2 records current file hashes and removed duplicate; incremental Standards rereview dispatched to issue04_standards. Spec review not started concurrently.
- Latest source-row-presence product rerun 20260912t192630z-68743-3b65cd4f has 3 passed / 12.02 seconds. Covers Run/Batch/Track with matching/mismatching windows plus daily-field lifecycle after the null-coordinate fix. Confirm cleanup from session20232/run.txt before final handoff.

- Standards R2 复审结束：P3 Duplicated Code 已关闭，新增硬性问题0、smell0，未关闭 findings0；生产哈希保持R1。随后单独启动 issue04_spec，在同一R2快照按母规格和04验收审查，不并行审查。
- 最新产品 session20232 已确认终态exit0，隔离容器/卷清理完成。尚待Spec报告，04未提交、05未开始。

## Final review and delivery — 2026-09-13

- Spec R2 completed with 0 actionable findings against the captured implementation, ticket, parent specification and ADR-0243/0246. Standards R2 has 0 open findings; the duplicated probe finding is closed. Both reviews were serial.
- Revalidated all non-tracker file hashes against the reviewed R2 snapshot. Latest Run/Batch/Track integration run 20260912t192630z-68743-3b65cd4f has status=0 and cleanup_status=0. Verification scope and earlier repaired failures are recorded above; full history remains ticket 07.
- All 12 acceptance criteria are satisfied. This tracker update is included in the independent ticket commit `feat(data): add nineteen TTM flow research fields`; no production publication or push performed.
