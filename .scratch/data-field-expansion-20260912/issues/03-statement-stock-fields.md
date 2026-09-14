# 03 — 开放三表的 16 个期末存量字段

**What to build:** Researcher 能直接组合应收、存货、现金和负债余额研究资产负债结构；数据复用已存三表原始记录，并在正确公告可见时间进入原有 Financial data 区块和研究公式。

**Blocked by:** 01 — 统一现有字段目录、准入和家族合同

**Status:** complete

**Execution contract:** 在从 main 创建并核实的新 worktree 中，严格按 01→08 串行执行。每票开始实现前先记录 Plan；完成实现后逐项验收，进行代码审查、修复及复审，更新 tracker 并形成该票独立 git commit，完成后才开始下一票。审查同样串行，不并行委派实现或审查。

**Latest user decision:** 按用户最新要求，直接实现当前合同，不做兼容、版本迁移或 vXX 升级链；这覆盖母规格中有条件引入迁移的旧提议。保留数据、原有字段语义与必要研究引用的要求继续有效，不将“不迁移”解释为允许清库。

**Execution order:** 03；必须先完成 02 的验收、复审、tracker 更新和独立提交。

- [x] 按权威清单开放 monetary_funds、accounts_receivable、notes_receivable、other_receivables、prepayments、inventories、accounts_payable、contract_assets、contract_liabilities、goodwill、short_term_borrowings、long_term_borrowings、bonds_payable、noncurrent_liabilities_due_1y、other_equity_instruments、cash_equivalents，共 16 项，归入 equity.financial_pit。
- [x] 逐列核实源科目、CNY 单位、合并范围和公司类型适用性，保持每个 Canonical Field 的独立定义。货币资金不自动解释为无限制现金，一年内到期非流动负债不自动等于全部有息债务。
- [x] 每项按固定期间合同选择最新可见报告的期末余额；cash_equivalents 虽来自现金流量表也按存量处理，不能被年报流量过滤或转换成 TTM。选中报告该列为空就缺失，不寻找旧非空值或相近来源列。
- [x] 从已保存原始证据生成新投影，并保留现有 6 个财务字段语义、原始版本和所需种子。只有可证明的原始记录缺口才补采，不默认重新下载三张报表。
- [x] 必要的 pre-start 期末种子可在声明 Coverage 起点正确读取，包括来自现金流量表的存量；保留原年报/存量种子，不允许由此提交 pre-2010 研究，历史退市证券仍使用相同身份。
- [x] 无有效公告日期的记录隔离；有效日期从下一 Research Session 可用。保留原始值、首次观察和版本证据；去重不抹掉最早观察，后见更正不回填过去，无法排序的冲突不能按响应顺序选胜者。
- [x] Financial Refresh 在保留既有来源证据的前提下更新这些字段，并保留其他家族及其覆盖。来源未完成、原值缺失与不适用分别记录，不通过填零制造可用性。
- [x] 目录、Financial data、公式补全、HTTP/MCP 和 Agent 展示一致的中文含义、单位、来源、期间和实际覆盖；不新增顶层卡片或逐日财务期间界面。
- [x] 用最新报告空值、现金流量表期末余额、公告日边界和修订 Fixture 验证读取；演示一个存量与原有 assets 组合的公式从目录发现到研究完成，并证明旧 Generation 不会被赋予这些新字段。

**Verification:** 母规格 T01、T02、T04、T06、T07、T09、T11、T15 的存量部分。与 04 无业务前置关系；两票集成后共同组成扩展的三表家族。本票不单独上线。

## Comments

- 2026-09-12：用户确认发布工单。已纳入最新的串行执行、每票 Plan / 验收 / 审查修复复审 / tracker / 独立提交，以及不兼容、不做版本迁移的要求。

## Plan — 2026-09-13

前置02已完成验收、串行复审与独立提交de55453；当前隔离worktree HEAD已核实，除先前研究草案外无未提交实现。04—08保持未开始。

1. 核对权威16项清单、源科目/金额单位/合并范围与现有财务采集、版本、种子、投影及读取入口，保存逐列映射和适用性证据；复用已存三表，不默认重采。
2. 先通过公开入口建立最新报告空值、现金流量表季度期末余额、公告下一Session、后见更正与起点种子的失败回归，再扩展同一财务家族和当前读取合同。原6项语义保持；无日期/无法排序冲突隔离，不回退旧非空值。
3. 贯通候选重建及Financial Refresh，保留既有来源证据和其他家族；缺口只按实际证据补采，不引入版本迁移、兼容或自动清库。
4. 同步目录、Financial区块、搜索补全、HTTP/MCP/Agent，通过存量与assets混合公式完成实际研究，验证旧Generation不增加新字段；仅读取所需列。
5. 运行受影响来源、计算、真实存储/Worker与页面验证。严格Standards→Spec串行审查，修复复审后逐项更新tracker并独立提交；完成之前不进入04。

## Field projection first slice — 2026-09-13

- 上轮已完成02提交与03 Plan，属于实际进展。本轮在HEAD de55453上继续，无并行实现或审查。
- 核实FinancialSeriesResolver已有按字段固定期间分组的行式/列式读取，可让同一cashflow来源中的年报流量和季度存量分别选报告。新增公开入口回归先2 failed（FINANCIAL_FIELD_UNSUPPORTED），接入权威16项静态字段后支持季度期末现金余额与原经营现金流同时读取。
- 新回归独立预期：余额40→季度60→新报告空值，原年报经营流量始终100；不会回退旧非空余额，也不读取无关total_assets列。最初预期误用float，核实当前Series返回字符串数值合同后修正，最终2 passed / 0.54s，Ruff通过。仅证明Series投影边界，未证明完整候选/产品可用。
- 已发现待修复边界：FinancialCandidateStore._retain_coverage_versions目前对非balancesheet只保留年报起点种子，会丢cashflow季度余额；需要保留最新季度存量及既有年报流量种子的并集。尚未修改该逻辑，下一步先建立真实候选起点回归。
- 16项目前按权威设计清单接入字段定义，逐列来源资格/适用性仍需核实；既有固定6项目录断言及其他调用方尚待同步。候选重建、原始证据与冲突、刷新/来源状态、HTTP/MCP/页面、混合公式研究验收均未完成。本票不标complete、不提交，04—08未开始。

## Start-seed retention regression — 2026-09-13

- 真实FinancialCandidateStore物化回归先1 failed：现金流来源只有20081231年报种子，缺少20090331季度余额种子。按实际FINANCIAL_FIELDS的固定期间分组选择起点版本，取年报流量和最新报告存量并集，按来源行身份去重。新回归1 passed / 1.53s，候选重复构建、重开、validate均通过，研究起点保持2010-01-04。
- 当前seed_policy描述同步改为annual-flow-and-reported-stock-facts，未增加格式版本或旧合同读取分支；集成Fixture中两处描述同步。原六字段目录语义断言保留，新增16项独立源列映射断言。
- 扩大现有financial_series+financial_candidate测试：49 passed、8 failed / 13.32s，session90897已终态exit1。八项均在Financial candidate composite准入失败：现有FULL_EXECUTABLE_FIELDS Fixture仍仅声明原六字段源列，组合入口现在要求当前22项源列。需要区分新候选全量列合同与已发布旧Generation声明子集，不能简单移除准入校验或给旧根补挂字段。
- 下一步核实compose_financial_candidate/现有旧根目录增长回归及Fixture，将新候选完整来源列和旧根子集保留分别验证，再继续起点实际Series与三表来源资格/版本冲突边界。最新测试行长已修正，五个受影响文件Ruff最终通过。03未验收、未审查提交，04—08未开始。

## Complete candidate columns and simultaneous conflicts — 2026-09-13

- 已核对组合准入只约束新候选当前完整源列，旧Generation验证使用自身字段声明。将FULL_EXECUTABLE_FIELDS测试夹具显式补齐16列，没有放宽产品准入；Series+候选57 passed / 15.71秒，session49452终态exit0，包含旧根字段子集及后续刷新保持回归。
- 冲突检查发现FinancialVersionProjector对同公告、同观察时刻的不同值全部标available，后续依赖update_flag/哈希选取；这不满足03无法确定次序的冲突隔离要求。新增正序/倒序公开投影回归先1 failed，证明旧实现仍将冲突标available。
- 现在在去重之后按同逻辑报告/公告/首次观察时刻识别多条不同来源记录，完整保留但标quarantined且无effective session；不将update_flag当修订时间。投影与已有后见更正定向3 passed / 0.51秒，session27350终态exit0，Ruff通过。
- 已启动完整financial_candidate测试检查该修复对旧Fixture/候选保留的影响，session97884活跃，JUnit保存在/tmp/thesistrace-issue03-candidate.xml；不得因观察超时重启。需检查旧Fixture中的同刻冲突预期，并补充真正可排序版本及季度种子实际值验证。03尚未完成/复审/提交，04—08未开始。
- session97884现已终态exit1：45 passed、3 failed / 13.46秒。失败为原稀疏候选的具体版本列表、内存有界测试压缩行数、pre-window版本压缩行数；同刻冲突隔离改变了既有Fixture可见版本和保留种子。明细已存上述JUnit。下一步必须检查压缩是否错误地丢弃隔离证据，以及更新独立业务预期，不能只改计数让测试通过。当前无运行测试句柄。

## Conflict evidence and projected-read verification — 2026-09-13

- 已核查read_financial_table的压缩仅作用于查询投影，read_table和原始回执保留全部隔离来源。未为通过测试移除隔离或修改压缩实现。
- 更新三项独立预期：可用值与隔离原值分别断言，所有隔离项无effective session；候选保存收入5条/余额2条共7条隔离记录。旧年报种子选择已不再采用冲突的80/81，仍可见的70按既有最新可见合格报告规则保留。
- 内存测试继续扫描12000以上物理行并保持4MiB Python峰值限制，改用既有measure_data_io证明实际扫描规模，避免把查询压缩后的输出行数当原始读取规模；同时验证候选保留12000以上隔离记录。
- 完整financial_candidate最终48 passed / 12.49秒，session57263终态exit0，JUnit /tmp/thesistrace-issue03-candidate.xml，Ruff通过。没有在运行测试。
- 已重新打开官方balancesheet/cashflow说明（doc_id36/44），后续继续逐列源单位与公司类型适用性资格核查；尚未从本次浏览提取新的资格结论。03仍需真实源资格、已存原始重建/刷新衔接、页面/HTTP/MCP与混合研究验收以及串行审查提交；04—08未开始。

## Source observations and explicit saved-evidence rebuild — 2026-09-13

- 完成16次有界只读请求（4类公司×年报/一季报×balancesheet/cashflow），全部返回且无缺列。原始响应保存在statement-stock-source-observations.json，脚本observe_statement_stocks.py不保存凭证、不发布Head。各类公司实际非空列数不同，单期亦有多行，不能把API返回成功或某列空值当通用适用性证明；金额单位仍需独立对照资格。
- 官方doc_id36/44已确认各源列含义、report_type=1合并报表及comp_type类别；cashflow.c_cash_equ_end_period明确为期末余额。公司类型7不在当前原有支持范围，不在本轮凭名称扩展。
- 新回归复现显式rebuild对相同原始证据直接返回旧候选，导致新增季度种子无法生成（1 failed，session8667终态）。移除该源证据不变即返回的快捷路径，显式重建按当前投影处理已有回执，未增添迁移/版本分支或供应商调用。
- 重建相关首轮7 passed/1 failed，旧测试把新操作期望成旧候选身份。修正为验证新候选、来源批数/覆盖不变、三张版本表内容相等，禁止深验旧根的断言保留。最终重建相关8 passed / 2.49秒（session41316已终态exit0）；最后变化仍需Ruff与后续整体检查。03未完成或提交，04—08未开始。

## Projection-aware reuse and 44-field contract checks — 2026-09-13

- 扩大到财务来源/候选/Series/Alpha/HTTP/家族合同先138 passed、4 failed；候选精确重放复用与旧目录预期暴露缺口。显式重建不能只按来源没变就跳过，但投影实际相同仍应复用旧候选。
- 将复用判断移动到当前投影和种子物化之后：历史证据先按现有UTC去重规则确认相同，再比较schema、覆盖、隔离摘要和全部表引用；一致时复用原候选，不改变已存根。初次直接比较raw_evidence引用导致跨时区表示测试失败，已改为复用既有语义化证据比较。新增季度种子时仍返回新候选。
- HTTP中文/Canonical映射和浏览器目录Fixture同步到44项（22市场+22财务）。保留原六字段逐项身份断言，新增16项映射，尚需同步浏览器场景断言并实际运行页面验证。
- 最终七文件测试组142 passed / 27.05秒，session79092终态exit0，JUnit /tmp/thesistrace-issue03-contracts.xml；Ruff和diff check通过。此前97320/58843失败已由本轮覆盖；无活跃测试。
- 官方贵州茅台2025年度报告已找到并与已存Tushare响应独立核对：money_cap、accounts_receiv、prepayment、inventories、c_cash_equ_end_period五项金额与合并表人民币元逐值一致。证据statement-stock-unit-crosscheck.json，官方报告URL及页码已记录；只证明这五项，不能替代剩余11项或跨公司适用性证据。官方URL：https://www.moutai.com.cn/mtgf/articleFileDir/2026-04/17/1b9fae59825c41bf9a776892a00565f7.pdf。
- 03仍需其余来源资格、真实刷新/混合研究/页面验收、串行审查修复复审和独立提交；04—08未开始。

## Browser acceptance and HTTP product run — 2026-09-13

- Data真实浏览器组件已同步44字段；1280/390两宽度验证通过（2 passed / 8.5秒，session61579终态exit0）。现金流来源2项、最新报告存量19项、中文货币资金/期末现金搜索、cash_equivalents补全、四个顶层区块及无水平溢出均已验证。
- 当前HTTP产品Fixture补齐22财务字段所需源列，原29项（7价格+22财务）与带daily_basic的44项目录数量同步。新增实际HTTP提交rank((monetary_funds+cash_equivalents)/assets)到Worker成功和冻结Generation断言；保留每日指标Run/Track链路复验。
- 通过临时/tmp/thesistrace-issue03-product-check.mjs复用原隔离TestRun运行器，运行20260912t174048z-73086-3dcc48d9，session72400仍活跃；目标为新增存量HTTP和既有每日字段HTTP/Track两项，不改变永久运行器，不使用共享开发数据。该测试文件Ruff通过。
- 来源观察再次显示需要逐字段适用性审查：601318.SH的contract_liab返回5,360,910,000,000，可能是保险合同负债而非一般收入合同负债；当前统一(1,2,3,4)声明不能直接视为已核实。需查原报表并明确该字段公司类型边界，不能凭空值或数值大小推断后宣布资格完成。
- 03尚未完整验收/复审/提交；04—08未开始。

## Equal-value source flags and independent insurance evidence — 2026-09-13

- 已核实产品运行20260912t174048z-73086-3dcc48d9终态：JUnit 2 passed / 6.870秒，run.txt status=0且cleanup_status=0；上条session仍活跃记录已过时。仅覆盖指定HTTP存量及每日字段Run/Track两项，不含依赖重启阶段。
- 真实响应中发现同值仅update_flag不同的两行。新增公开Projector正序/倒序回归先失败（误隔离），修复同刻冲突判断为比较除update_flag外的内容；两条原始标记和批次证据均保留，不按标记选择金额。真正不同金额冲突仍隔离。完整financial_candidate 50 passed / 14.43秒，session88504终态exit0，JUnit /tmp/thesistrace-issue03-candidate.xml；Ruff及diff check通过。
- 中国平安官方2026一季报的2025年末审计比较列独立核对了货币资金、商誉、短期借款、长期借款、应付债券及contract_liab，人民币百万元乘1000000均与保存响应一致。证据statement-stock-insurance-crosscheck.json。明确确认contract_liab此处实际是保险合同负债，不能当普通收入合同负债开放；下一步必须落实字段适用性及行式/列式读取边界，不能宣布全类型合格。
- 03仍在实施，尚未完整验收、审查或提交；04—08未开始。当前无运行测试。

## Per-field applicability enforced — 2026-09-13

- 以官方保险报表证据落实contract_liabilities的公司类型1/2/4边界；其他既有字段保留1/2/3/4。目录明确该字段是收入合同负债且保险来源可能是保险合同负债，未改变字段数量或创建保险字段别名。
- 新增公开Series行式/列式回归先2 failed，证明原实现将保险数值直接输出。读取使用FieldDefinition的适用类型，在最新报告选定后按字段置缺失；不会跳过最新保险报告退回旧普通公司值，同一报告的assets仍可用。完整Series 12 passed / 1.06秒。
- 同步226清单Markdown/CSV/JSON、32项定义附件和生成的浏览器公共目录。四文件组129 passed、1 failed / 18.58秒，session53174终态exit1，唯一失败是HTTP测试仍要求所有字段四类通用。明确更新该字段独立适用性预期后，HTTP组7 passed / 0.70秒；Ruff和diff check通过。没有将第一次失败称为全绿。
- 茅台官方2025年合并报表继续核实其他应收款、应付账款、合同负债、一年内到期非流动负债，四项人民币元与保存来源逐值一致；该证据文件现含9项金额对照，纠正页码包括58页。结合独立平安核对，共覆盖13个不同新增存量源列；notes_receiv、contract_assets、oth_eqt_tools仍需非空独立单位/科目证据。来源类型和历史完整性仍需分别验证。
- 下一步继续剩余来源资格及实际刷新/MCP链路，之后按串行Standards/Spec审查、修复复审、tracker更新和独立提交；03未完成，04—08未开始。当前无运行测试。

## Remaining units and isolated refresh verification — 2026-09-13

- 补做一次601668.SH/20251231/balancesheet只读请求，原响应statement-stock-construction-observation.json。中国建筑2025年合并报表应收票据3,820,157千元、合同资产588,967,936千元，分别乘1000后与来源一致；平安银行2025年附注32其他权益工具99,953百万元乘1000000后与原响应一致。三个检查保存statement-stock-remaining-crosscheck.json。逐列索引statement-stock-qualification.md覆盖全部16源列，明确仅是非空金额/科目对照，不能替代07全历史账本。
- 财务刷新集成的EXECUTABLE_FIELDS仍是旧六列合同。补齐16存量列和独立Fixture值后，隔离运行20260912t175448z-78396-f3d9cc4b为1 passed/1 failed；每日刷新内嵌来源仍返回旧长度，实际被正确判pending。保留严格来源校验，同步该类完整响应Fixture，不放宽发布成功条件。
- 复跑20260912t175550z-79134-2be5e90d终态exit0，覆盖首次财务发布及每日发现刷新两项；以evidence/pytest.xml和run.txt为证。隔离环境清理完成；未执行依赖重启阶段。Ruff通过。
- 后续需强化新字段刷新后实际读取、MCP入口及剩余相关Fixture合同回归，再串行审查和提交。03仍未完成，04—08未开始。当前无运行测试。

## MCP product path and published values — 2026-09-13

- 新增真实打包stdio MCP链路：按需查货币资金/现金等价物/合同负债，核对CNY、最新报告期间和保险适用性，提交混合存量/assets公式，断开客户端后独立Worker完成，再重连取成功结果。首次运行20260912t175749z-80574-78e48d28失败，新增Fixture漏掉研究者bootstrap导致提交拒绝；目录查询已通过。补齐测试身份后复验，不修改产品准入。
- 财务发布测试增加通过MountedGenerationStore.read_composite_slice读取发布前后根的实际货币资金2、现金等价物3，保留既有非目标家族引用检查。运行20260912t175921z-87474-8b1428c2最终2 passed / 11.87秒，session45841终态exit0并清理成功。Ruff及diff check通过。
- 发现GC候选验收另有独立旧六字段ComposableSource，已移除重复来源并复用当前EXECUTABLE_FIELDS/ExecutableStatementSource；需要财务集成组验证。MCP测试复用既有HTTP完整候选构造，未新增生产读取或兼容路径。
- 下一步扩大financial_collection整文件集成回归，之后串行审查并关闭发现；03未完成，04—08未开始。

- 已启动隔离整文件回归20260912t180056z-91113-b70a1550，当前session74473活跃；临时运行器/tmp/thesistrace-issue03-financial-check.mjs复用原integration入口，-k test_financial_collection，JUnit在该run/evidence/pytest.xml。观察超时不能重启，继续查询原句柄。

## Financial integration and Standards review — 2026-09-13

- 财务采集/刷新整文件20260912t180056z-91113-b70a1550已终态：48 passed / 15.848秒，session74473 exit0，cleanup_status=0。覆盖当前普通集成文件，不包含独立依赖重启阶段。
- 捕获工作树审查输入/tmp/thesistrace-issue03-review/inputs.json和tracked.patch，HEAD de55453；排除历史脚本、223草案及ticket-drafts。Standards代理issue03_standards串行完成：1项P1硬问题，0项smell建议。Spec尚未开始。
- P1：FinancialCandidateStore.validate按当前投影、种子和seed_policy重算未变旧根，违反保留既有不可变Generation要求。调用链已核实：collection._validated_retained_files → validate_generation → financial_store.validate，以及financial_candidate_referenced_files。会阻断GC保留集合校验；open_admission不走此深校验，未声称所有旧Run无法执行。
- 独立复现：/tmp/thesistrace-reproduce-old-candidate.py从git de55453读取原生产模块，在临时目录生成并由原模块校验成功的候选。当前模块随后明确报FINANCIAL_CANONICAL_PROJECTION_INVALID。证据/tmp/thesistrace-issue03-old-candidate.json，manifest afd76a941766d3471ec95a22383a9ce9ce4e10ec558a530b3e2e0c12eacf9917；数据目录/var/folders/py/j9ws8lpn57g_syngj3b58b6h0000gn/T/thesistrace-issue03-old-hunp6gsr/data。初次复现脚本误假设旧模块有FINANCIAL_FIELDS，已移除该假设；最终运行exit0。
- 下一步修复已发布不可变事实完整性校验与新候选当前投影验收的边界，保留哈希、引用、来源证据和失效拒绝，不改写旧根、不添加版本分派或兼容路径。补修改前真实旧根的保留/GC回归，Standards复审关闭后再做Spec。03仍未完成/提交，04—08未开始；当前无运行测试或审查。

## Stored fact integrity repair in progress — 2026-09-13

- 新增FinancialCandidateStore.validate_stored作为已保存不可变事实的完整性操作；Generation验证和候选保留文件集合改用该入口。新候选物化仍执行原validate当前投影验收，没有按版本或旧字段分派。
- 保存事实入口核对内容寻址、Parquet schema/编码/排序/分区/计数、回执列和身份/源值、来源与观察时间、可见时间不早于来源、覆盖账本、父证据并集和隔离摘要；不以当前seed筛选、冲突选择和描述文字重新生成旧表。
- 将de55453原生产模块生成并验证的合成旧候选保存为tests/fixtures/financial-stored-facts/candidate-de55453.zip（50,002字节），README记录生成来源及固定manifest。新增完整、raw损坏、object损坏三种公开保留文件集合回归，并断言完整检查不改任何保存字节。初次raw损坏测试路径写错，纠正为financial/raw后全组三项通过。
- 候选全组首轮53 passed / 12.79秒；补来源时间、覆盖计数、父证据后最新53 passed / 12.17秒，session25700终态exit0，JUnit /tmp/thesistrace-issue03-preserved.xml。Ruff通过。
- P1尚未关闭：还需真正旧Generation根及真实GC保留链路验证、当前daily候选完整性与刷新集成回归，检查新增入口没有削弱伪造数据拒绝和有界读取要求；之后重新捕获输入并请Standards复审，关闭后才开始Spec。03未提交，04—08未开始，当前无运行测试。

## Old Generation GC and calendar-extension boundaries — 2026-09-13

- 使用git archive de55453完整apps/core/src在临时进程生成并验证旧Generation；固定样本generation-de55453.zip及README已保存。root611f1a80a541819b29b57112eed4a2a9d2cef501d2388904e103ee3636f2ef0e含原六财务字段及最小close，空完成回执；非空旧候选另由candidate-de55453.zip覆盖。新增真实数据库GC保留测试，检查回收后原根、字段集合、文件及Head不变。
- 整文件20260912t181420z-96129-1fbea670为44 passed/5 failed（16.41秒），session74100终态并清理。新validate_stored误比较在较短日历中持久化为空的first_observed_session与当前日历重算值。改为逐个验证非空派生Session符合来源时间；不要求已存空值随当前日历被改写。用失败保存根直接验证通过。
- 第二轮20260912t181645z-96977-bf0900b9为45 passed/4 failed（15.88秒），session32769终态并清理。剩余首个错误是零新增回执的合法每日刷新被_validate_evidence_entries判FINANCIAL_ENDPOINT_SET_INVALID；current为空时仍核对现有历史与并集，不强求本次三个端点。失败目录全部后继根已直接validate_generation通过。后续GC缺失根是否为首个失败残留仍待完整复跑证明，不直接视为已修复。
- 当前复跑20260912t181812z-97612-38d7d4a3，session98001已确认活跃，临时运行器/tmp/thesistrace-issue03-financial-check.mjs。继续查询同一句柄，不因观察超时重启。P1未关闭，Standards复审及Spec尚未执行，03未提交，04—08未开始。

## Stored Generation retention regression — 2026-09-13

- 上轮20260912t181812z-97612-38d7d4a3终态48 passed/1 failed，cleanup_status=0。唯一失败为新golden mount继承其他测试遗留的数据库候选保留引用；GC严格拒绝缺失根，产品行为正确。
- 新GC测试复用已有drop_product_schemas，在隔离测试数据库中清理用例前后状态，保证数据库引用与本用例临时mount一致；不改变生产保留规则。
- 整文件复跑20260912t182317z-99501-3d1fea17终态exit0：49 passed/430 deselected，17.47秒；本次容器、卷和网络清理完成。Ruff和diff check通过。未执行独立依赖重启阶段。
- 下一步对保存事实校验修复做Standards复审，随后Spec；P1仍待审查关闭，03未提交，04—08未开始。

## Serial review and quarantined-only reading — 2026-09-13

- Standards R2完成：0 hard/0 smell，原P1已关闭；审查末全部输入哈希与/tmp/thesistrace-issue03-review-r2一致。Spec随后串行完成，只有1项P1：只有隔离/pending记录时，列式resolver过滤后空数组访问group_starts[0]导致IndexError，违反缺失语义；未发现其他缺漏或范围扩张。
- 以真实Raw→Candidate→公开resolver建立行式/列式参数回归，先1 passed/1 failed，稳定复现列式IndexError；候选余额500/501为同刻冲突。过滤后无available行时返回原schema空transitions，保留外层坐标对齐与缺失传播。
- 修复后candidate与series全组67 passed / 13.64秒，session48049终态exit0；JUnit /tmp/thesistrace-issue03-quarantine-fixed.xml。Ruff及diff check通过。之前保存事实最终53 passed / 15.34秒亦已实测，JUnit /tmp/thesistrace-issue03-stored-final.xml。
- 需对这两行产品修复及回归再串行Standards→Spec复审；03仍未提交，04—08未开始。

## Acceptance and delivery — 2026-09-13

- 9项验收完成：静态目录/HTTP合同核对16映射；qualification附件保存全部16科目独立金额及单位对照，保险合同负债排除逻辑经行式/列式验证。
- Candidate与Series覆盖最新报告空值、季度期末余额、旧年报语义、季度/年度种子并集、回执重建、公告下一Session、后见修订、冲突隔离及隔离后缺失，最终67 passed。旧非空候选保持字节及损坏拒绝、原生产Generation经真实GC保留均验证。
- 财务采集刷新整文件49 passed；HTTP存量混合公式与每日字段Run/Track两项通过；MCP存量目录/提交/Worker及发布后实际值读取两项通过。Data浏览器1280/390两用例已通过，验证搜索/来源/期间/补全/四块布局。详细run/JUnit和范围见上文；未声称全历史采齐或生产上线。
- 串行Standards R2关闭原保存事实P1；Spec首次发现隔离空行P1，补失败回归并修复。Standards R3为0 hard/0 smell，Spec R3关闭P1且0新增问题；两者核对全部送审哈希一致。
- 本记录随03独立提交交付，提交消息feat(data): expose sixteen statement stock research fields。04必须在此提交成功后才开始。
