# Tushare 日频策略探索字段扩展研究

> 状态：研究建议，不是已批准 ADR，也不表示已实现。官方文档核对日期：2026-09-12。
>
> 范围：A 股日频横截面选股、因子探索。证据包括 Tushare 官方文档、当前 main checkout（HEAD `2daf193`）的相关数据代码、生产 MCP 目录与覆盖状态，以及用户授权后的生产/开发数据卷只读核验。后续为澄清实际可获取字段，使用现有生产账户执行了 5 次小样本 TuShare API 读取；未启动回填或修改数据集。
>
> 本文补充 [财务 PIT 接入研究](tushare-financial-data-pit.md)，以本次实际打开的官方页面核对接口事实。文中“建议”“应”“可推导”属于设计分析；带来源链接的字段、限制、更新说明属于文档事实。

> 后续讨论将本轮方案收敛为：先接入 daily_basic 与 fina_indicator，使用供应商现成指标。对应的 [DSL 完整目标清单](dsl-field-catalog-2026-09-12.md) 为现有 12 个字段加新增 179 个入口，共 191 个；下文三表 TTM/单季自算及其他来源仍是扩展分析，不是本轮必须先完成的工作。

## 结论与扩展顺序

应优先补公司规模、估值分母、报告期运算和经济口径匹配。扩展需要发布新的 Data Generation，并对新接口做历史回填、对财务补足投影依赖；现有行情、行业、基准和已保留财报具备复用基础，没有全库清空或全部重新下载的必要。具体依据见第 0、8 节。

| 优先级 | 研究能力 | 最小扩展 | 来源路径 |
| --- | --- | --- | --- |
| P0 | 规模、换手、可交易性控制 | 总/流通市值，总/流通/自由流通股本，两种换手率；保留上市、停牌、涨跌停等研究准入信息 | `daily_basic`；复用或补齐参考数据 |
| P0 | 价值、成长、盈利改善 | 原有收入、归母利润、经营现金流的 TTM、单季、同报告期同比；与这些期间匹配的资产/权益 | 三表报告期投影；不是新拉一套“技术因子” |
| P1 | 盈利质量、资产质量、财务稳健 | 营业收入与成本、合并净利润、资本支出、现金、应收、存货、商誉、流动资产/负债；扣非利润需单独确认口径 | 三表 + 经核对的 `fina_indicator` |
| P1 | 股息与分红持续性 | 供应商股息率可作独立字段；可解释的分红研究需要分红事件、实施状态与日期 | `daily_basic` + `dividend` |
| P1 | 行业相对强弱、风格控制、基准暴露 | 历史行业成员、行业/市场收益、历史指数成分与权重 | `index_classify`、`index_member_all`、`sw_daily`、`index_daily`、`index_weight` |
| P2 | 交易行为、拥挤与融资需求 | 分类主动成交净额、供应商净流入、融资余额与净买入、两融资格 | `moneyflow`、`margin_detail`、`margin_secs` |
| P2 | 事件驱动的业绩变化 | 预告上下限、事件修订、快报值、距公告时间 | `forecast`、`express`；`disclosure_date` 用于计划和发现 |
| 后置 | 股权集中、筹码结构、解禁压力 | 十大股东集中度、股东人数变化、当时已知的未来解禁量 | `top10_holders`、`top10_floatholders`、`stk_holdernumber`、`share_float` |

优先级按“扩大研究空间、复用现有数据、能够说清历史可见性”综合判断，不是预期收益排序。字段数量不作为交付目标。

## 0. 当前系统和生产库存：本次已核实

### 0.1 生产状态

2026-09-12 通过配置指向 `https://thesistrace.com/mcp` 的 `get_research_context`、`get_alpha_catalog` 读取：

- 行情、行业、独立基准覆盖均为 2010-01-04 至 2026-09-09。
- 财务覆盖起点 2010-01-04；公告发现完整推进到 2026-09-09，`ready`，pending instrument / discovery gap 均为 0。
- 财务历史对账水位仍是 2026-08-13，此后是公告驱动更新；ready 不代表每一天重新全市场对账，也不代表每个字段无缺失。
- 开放 12 个 Alpha 字段和 12 个运算函数；没有市值、股本、换手率、TTM、单季、同比等新增研究字段。

证据：[线上目录与覆盖快照](../../.scratch/data-field-expansion-20260912/runtime-evidence.json)。

用户授权后的生产只读脚本进一步确认，Head 指向 Generation `17f5694f6a9d47b915ffde326928b919a55181e75a4908cb661934850ac8c983`，截止 2026-09-09，检查前后 Head 相同。其财务家族保留的来源列如下，列数包含来源身份、日期等元数据，不等于可研究数值字段数量：

| 财务表 | 生产保存的来源列数 | 已保存但尚未开放的典型列 |
| --- | ---: | --- |
| income | 85 | `revenue`、`n_income`、`oper_cost`、`operate_profit`、`ebit`、`ebitda`、`rd_exp`、各项期间费用 |
| balancesheet | 152 | `money_cap`、`accounts_receiv`、`inventories`、`goodwill`、流动资产/负债、短借/长借/债券、合并权益 |
| cashflow | 97 | `c_pay_acq_const_fiolta`、`c_fr_sale_sg`、`net_profit`、`free_cashflow` 等 |

来源合同中没有 `lease_liab`，三表中也没有 `fina_indicator.profit_dedt`。它们属于需要新增来源或扩充采集合同的候选，不能与上表已有列一起宣称只需开放。

生产财务证据索引有 23,808 条记录。抽查 000001.SZ、600519.SH 各三表的最早保留批次，六份样本都包含 2007—2009 年的季度报告期。它证明原始历史确实留存，不证明所有股票、每个候选列在这些期间都非空，也不证明供应商历史修订完整。

证据：[生产 Manifest 与原始批次摘要](../../.scratch/data-field-expansion-20260912/production-mounted-evidence.json)、[只读核验脚本](../../.scratch/data-field-expansion-20260912/inspect_mounted_dataset.py)。证据只记录字段名、日期、计数和哈希，不包含凭证或财务数值。

开发环境是另一个 Head：行情截止 2026-08-27，财务发现截止 2026-08-19。其三表来源列数和生产一致，但日期不能混用。[开发环境证据](../../.scratch/data-field-expansion-20260912/local-mounted-evidence.json)

### 0.2 当前代码能力

三表采用独立的宽版本表，来源字段进入 nullable 列；原始响应及 first-observed 证据留存。现有日频财务解析器只实现最新可见年报流量和最新报告期存量。所有这些列都已入库，不等于解析器已支持任意报告期运算。[宽表合同](../../apps/core/src/thesistrace/data/financial_candidate.py#L2495)、[当前投影规则](../../apps/core/src/thesistrace/data/financial_series.py#L44)

当前只接受核心行情家族、可选行业及财务家族的固定组合；列式研究读取也只分行情/财务两路。新增 daily_basic 家族必须补采集、存储、解析、依赖和准入验证；不能往目录加一行就使用。[家族验证](../../apps/core/src/thesistrace/data/generation_store.py#L2545)、[列式读取](../../apps/core/src/thesistrace/data/generation_store.py#L1018)、[依赖声明](../../apps/core/src/thesistrace/data/dependencies.py)

现有行业成员和行业中性化可复用；基准已有独立快照，当前并非任意可写入 Alpha 的市场字段。现有价格/成交量足以计算的均值、收益率、波动率应保留为公式，不必新增供应商数据。

### 0.3 明确数量：供应商提供、账号实际返回、已保存、公式开放

2026-09-12 04:48 UTC，使用生产采集容器现有账户，以 600519.SH 的 2025 年报、2026-09-09 日频数据执行 5 次只读请求。显式请求每个接口文档中的全部输出列，五次均 HTTP 200、来源 code 0，各返回一行，字段无遗漏、行宽一致。以下只统计这五个核心接口，不是 TuShare 全平台字段总数，跨接口同名列没有去重。

| 接口 | 官方列数 | 本次账号实际返回列数 | 生产已保存来源列数 | 其中数值列数 | 已开放公式字段数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| income 利润表 | 94 | 94 | 85 | 77 | 2 |
| balancesheet 资产负债表 | 158 | 158 | 152 | 144 | 3 |
| cashflow 现金流量表 | 97 | 97 | 97 | 89 | 1 |
| daily_basic 每日指标 | 19 | 19 | 0 | 0 | 0 |
| fina_indicator 财务指标 | 167 | 167 | 0 | 0 | 0 |
| **五接口合计** | **535** | **535** | **334** | **310** | **6** |

“其中数值列数”指已保存来源列中按官方类型归类的数值项，不表示全部非空。535 列里有 505 个数值/状态项，其余为证券代码、日期、报表类型和更新标记等。当前公式另外开放 6 个行情字段，所以总数是 12；行情、行业、日历、交易状态、基准等其他数据不计入表内 334。

官方依据：[income](https://tushare.pro/document/2?doc_id=33)、[balancesheet](https://tushare.pro/document/2?doc_id=36)、[cashflow](https://tushare.pro/document/2?doc_id=44)、[daily_basic](https://tushare.pro/document/2?doc_id=32)、[fina_indicator](https://tushare.pro/document/2?doc_id=79)。核验清单：[官方字段名称与类型](../../.scratch/data-field-expansion-20260912/official-field-schema.json)、[实际返回字段及状态](../../.scratch/data-field-expansion-20260912/live-tushare-field-probe.json)、[只读请求脚本](../../.scratch/data-field-expansion-20260912/probe_tushare_fields.py)。

三表并未保存官方所有可选列，目前明确缺少 15 个：

- 利润表 9 个：`net_after_nr_lp_correct`、`credit_impa_loss`、`net_expo_hedging_benefits`、`oth_impair_loss_assets`、`total_opcost`、`amodcost_fin_assets`、`oth_income`、`asset_disp_income`、`end_net_profit`。
- 资产负债表 6 个：`oth_eq_invest`、`oth_illiq_fin_assets`、`oth_eq_ppbond`、`receiv_financing`、`use_right_assets`、`lease_liab`。
- 现金流量表的 97 个文档列均已保留；这只说明列名齐，不证明全历史每个单元格完整。

原因也能从当前采集代码看到：初次用空 `fields` 探测默认返回列，再把探测结果锁定为后续采集合同。默认返回列不等于文档中全部可显式请求列。[探测入口](../../apps/core/src/thesistrace/data/financial_collection.py#L1077)

实际返回 schema 也不等于全部有值。本次茅台样本，三表非空列数分别为 46/94、65/158、64/97；daily_basic 为 19/19，fina_indicator 为 162/167。其他公司类型专用项、未披露或缺失数据都可能为空。这不是全市场缺失率统计，不能用单一公司判断来源质量。

所以当前同时存在三类缺口：**已保存但未开放的列、尚未采集的来源/可选列，以及尚未实现的报告期运算。** “无需整库重建”表示现有数据可复用，不表示现有数据已经足够或完全齐备。

## 1. 规模、流动性与估值：先接好 daily_basic

| 研究字段 | 确切 Tushare 输出列 | 推荐处理 |
| --- | --- | --- |
| 总市值、流通市值 | `total_mv`、`circ_mv` | 来源为万元；规范到 CNY |
| 总股本、流通股本、自由流通股本 | `total_share`、`float_share`、`free_share` | 来源为万股；规范到 shares；流通和自由流通不能互换 |
| 流通换手、自由流通换手 | `turnover_rate`、`turnover_rate_f` | 来源给出不同分母；不能当同义别名 |
| 供应商量比 | `volume_ratio` | 文档只写 VOL/MA，未写完整均值窗口；不能声称与自算 5 日量比等价 |
| 供应商 PE / PB / PS | `pe`、`pe_ttm`、`pb`、`ps`、`ps_ttm` | 可保留为 vendor-derived，显示原始口径和缺失规则 |
| 供应商股息率 | `dv_ratio`、`dv_ttm` | 来源为百分比；年度与滚动口径分开 |

以上字段、单位与定义来自 [daily_basic](https://tushare.pro/document/2?doc_id=32)。当前页面的换手率描述写出分子分母，未逐列标明百分数缩放；接入时用实际样本核对后锁定单位合同。

该接口有几个会影响使用的具体差异：亏损公司的 PE/PE_TTM 为空；PB 的分母扣除其他权益工具；PS 使用最新年度营业收入；`dv_ratio` 按去年发生除息的派现统计，`dv_ttm` 还对分红报告期施加近 12 个月条件。它们不能自动等同于自建的盈利收益率、账面市值比或现金分红收益率。[daily_basic](https://tushare.pro/document/2?doc_id=32)

建议同时形成一组可解释的研究公式：归母利润 TTM / 总市值、匹配股东权益 / 总市值、营业收入 TTM / 总市值、经营现金流 TTM / 总市值。原始市值和财务值规范到同一货币单位，再由公式相除；亏损值是否参与排序由因子规则决定。供应商比率与自算比率应使用不同字段 ID，不能补缺时相互替代。

估值需要当时的真实名义价格与股本。不要用累计复权 `close × 股本` 重算市值；`daily` 的原始行情是未复权价格，其成交量单位为手、金额为千元。`amount / volume` 可以作为均价研究的基础，但首先要统一单位与价格复权口径。[daily](https://tushare.pro/document/2?doc_id=27)

对收盘后计算、后续交易日执行的策略，先使用收盘数据即可。确实需要当日盘前股本时，另评估 `stk_premarket`：它提供 `total_share`、`float_share`、`pre_close`、`up_limit`、`down_limit`，需要独立权限；不能假定已有 5000 积分就能访问。[stk_premarket](https://tushare.pro/document/2?doc_id=329)

## 2. 财务扩展：原始报表列、报告期投影、研究公式分三层

### 2.1 三表中的源字段

以下是围绕研究问题挑选的列，未列出整个财报 schema。

| 来源 | 源字段 | 对应研究用途 |
| --- | --- | --- |
| `income` | `total_revenue`、`revenue` | 营业总收入和营业收入是不同口径，保持不同身份 |
| `income` | `n_income_attr_p`、`n_income` | 归母利润用于母公司股东回报；含少数股东损益的合并净利润用于与合并资产/现金流匹配 |
| `income` | `oper_cost`、`operate_profit`、`rd_exp`、`sell_exp`、`admin_exp`、`fin_exp_int_exp` | 毛利、经营盈利、研发与费用强度、利息覆盖的组成项 |
| `balancesheet` | `total_assets`、`total_liab`、`total_hldr_eqy_exc_min_int`、`total_hldr_eqy_inc_min_int` | 规模、杠杆、股东权益与合并权益的匹配 |
| `balancesheet` | `money_cap`、`accounts_receiv`、`inventories`、`goodwill`、`total_cur_assets`、`total_cur_liab`、`oth_eqt_tools` | 流动性、应收与存货占用、商誉风险、普通权益口径 |
| `balancesheet` | `st_borr`、`lt_borr`、`bond_payable`、`non_cur_liab_due_1y`、`lease_liab` | 有息债务研究的候选组成项；不能不加会计范围定义就全部机械相加 |
| `cashflow` | `n_cashflow_act`、`c_pay_acq_const_fiolta`、`c_fr_sale_sg` | 经营现金流、购建长期资产现金支出、销售收现 |

对应来源：[income](https://tushare.pro/document/2?doc_id=33)、[balancesheet](https://tushare.pro/document/2?doc_id=36)、[cashflow](https://tushare.pro/document/2?doc_id=44)。三表页面没有对上述每一列都逐一标明货币单位；新增列必须与已有来源合同及实际报表样本核对，不能把万元的事件接口套入同一转换规则。

如果当前 `revenue` 已表示 `total_revenue`，新增 `income.revenue` 时应取另一个清晰名称，不能改写老字段含义。`n_income_attr_p` 与 `n_income` 同样必须并存且明确命名。[income](https://tushare.pro/document/2?doc_id=33)

先复用已保留的三表原始事实，再增加按报告期解析的能力。某列已经存在于原始响应，不代表已在 Canonical 中保留了所需历史，也不代表已经能够写入 Alpha。

### 2.2 必须由报告期解析器提供的能力

| 能力 | 建议明确的定义 | 不能用来代替的操作 |
| --- | --- | --- |
| TTM 流量 | 对同一口径：本期累计 + 上年度全年 − 上年同期累计；所有输入版本在研究时点均已可见 | 对日频填充值做 252 日求和 |
| 单季度流量 | 一季报直接使用；二/三季用本年相邻累计相减；四季为年报减三季累计。也可选择经验证的源单季表，但合同须固定 | 把半年报或三季报累计值称作单季 |
| 同比 | 同报告期、同累计或单季口径比较；保留基期和本期来源 | `pct_change(财务每日序列, 252)` |
| TTM 的平均资产/权益 | 明确采用期初/期末两点平均，或另一种有固定定义的平均方式 | 最新年报利润 / 任意最新季末权益 |
| 成长加速 | 先按报告期计算本季度同比，再比较前季度同比 | 对日频阶梯序列做任意交易日差分 |
| 资产增长、应收增长 | 明确“较年初”与“较上年同季”，两者各自使用不同字段 | 只看到名称中有 `yoy` 就认定为同比 |

这些是建议的研究合同。三表文档区分最新合并、单季合并、调整单季、调整合并、调整前合并及母公司口径，因此组合计算必须先筛选同一会计范围。存在 `report_type=2` 不证明全部公司、所有历史季度均有可用单季表。[income](https://tushare.pro/document/2?doc_id=33)、[cashflow](https://tushare.pro/document/2?doc_id=44)

同比基期为零或负数时，常规百分比可能失去直观含义。建议首版把“正基数增长率”与“扭亏/转亏状态”分开，明确零、负基数和缺期的处理；不要为避免空值临时换一种增长算法。TTM 的任一组成报告缺失，也应呈现缺失，而不是退回年报。

### 2.3 fina_indicator 能提供什么，何时值得使用

| 类型 | 确切输出列示例 | 使用建议 |
| --- | --- | --- |
| 盈利与质量 | `roe`、`roe_waa`、`roe_dt`、`grossprofit_margin`、`netprofit_margin`、`roic` | 供应商指标；与自算 TTM/两点平均比率分开 |
| 扣非与债务 | `profit_dedt`、`q_dtprofit`、`interestdebt`、`netdebt` | 用于新增信息或交叉核验；逐项确认会计范围和单位 |
| 同比 | `tr_yoy`、`or_yoy`、`netprofit_yoy`、`dt_netprofit_yoy`、`ocf_yoy` | 明确收入总额/营业收入、归母/扣非口径 |
| 单季改善 | `q_sales_yoy`、`q_netprofit_yoy`、`q_roe`、`q_gsprofit_margin` | 独立命名为供应商单季指标 |

来源：[fina_indicator](https://tushare.pro/document/2?doc_id=79)。该页还存在容易误读的名称：`gross_margin` 是毛利金额描述，`grossprofit_margin` 才是毛利率；`assets_yoy`、`eqt_yoy` 的说明是相对年初；`ocf_to_profit` 的分母是营业利润。应按说明建立语义，不能按英文缩写猜测。

该接口有公告日和报告期，但不像三表一样提供完整 `report_type` / `comp_type` / `f_ann_date`。直接接入已经计算好的 ROE 很省计算成本，但不能因此声称已获得比三表更完整的历史版本血缘。对扣非利润，文档的 `profit_dedt` 简述未明确是否归母，须核对真实样本后再授予“归母扣非”字段身份。[fina_indicator](https://tushare.pro/document/2?doc_id=79)

### 2.4 质量公式应保持经济范围匹配

建议先提供可组合基础值和明确的期间投影，再给研究者以下公式示例：

- 毛利率：一般工商企业的 `(营业收入 TTM − 营业成本 TTM) / 营业收入 TTM`。
- 现金利润匹配：合并经营现金流 TTM / 合并净利润 TTM；或 `(合并净利润 TTM − 合并经营现金流 TTM) / 平均合并资产`。
- 归母权益回报：归母利润 TTM / 匹配期间的平均归母权益，标明平均方法；不能命名成供应商加权平均 ROE。
- 资本支出后的经营现金剩余：经营现金流 TTM − 购建长期资产现金支出 TTM。
- 资产质量：应收 / 营业收入 TTM、存货 / 营业收入 TTM、商誉 / 匹配权益；按行业判断适用性。

上述公式是建议，分母有效性、负值和适用公司类型应进入字段/公式合同。“经营现金流减资本支出”不直接命名成严格 FCFF 或 FCFE；供应商也分别提供 `free_cashflow`、`fcff`、`fcfe`，不能把它们视为同一数值的别名。[cashflow](https://tushare.pro/document/2?doc_id=44)、[fina_indicator](https://tushare.pro/document/2?doc_id=79)

银行、保险、证券、多元金融要有适用范围。三表当前 `comp_type` 文档列出 `1` 一般工商、`2` 银行、`3` 保险、`4` 证券、`7` 多元金融。经营现金流、存货周转、毛利率和一般工业企业的债务定义不宜跨这些类型直接排名。[balancesheet](https://tushare.pro/document/2?doc_id=36)

## 3. 股息、行业与交易行为

### 3.1 股息研究需要事件链

`dividend` 提供 `cash_div_tax` / `cash_div`（每股税前/税后分红）、`stk_div`、`div_proc`、`ann_date`、`imp_ann_date`、`record_date`、`ex_date`、`pay_date`、`base_share`。它足以承载已实施现金分红、连续分红、分红增长等研究的源事实。[dividend](https://tushare.pro/document/2?doc_id=103)

建议先做税前、已实施、按除息日归属的现金分红，再明确是否扩展公告预案策略。预案、决案与实施状态不能累计重复计数；实施数据也不能提前写回预案公告日。跨送转股的每股分红相加前需要统一股本基准，或使用总现金派发量与市值的明确口径。税后分红不宜当所有投资者的统一实际税负。

现金流量表的 `c_pay_dist_dpcp_int_exp` 同时包含分配股利、利润和偿付利息的现金，不能当作普通股现金分红来构造股息率。[cashflow](https://tushare.pro/document/2?doc_id=44)

### 3.2 行业与基准属于参考数据和环境序列

| 来源 | 确切字段 | 可支持的能力与边界 |
| --- | --- | --- |
| `index_classify` | `index_code`、`industry_code`、`level`、`parent_code`；输入 `src=SW2014/SW2021` | 分类体系身份；不能混用两个版本的同名行业 |
| `index_member_all` | `l1_code`、`l2_code`、`l3_code`、`ts_code`、`in_date`、`out_date`、`is_new` | 按历史成员归属进行分组、行业中性化；默认 `is_new=Y` 只请求最新，需要显式处理历史 |
| `sw_daily` | `close`、`pct_change`、`pe`、`pb`、`float_mv`、`total_mv` | 行业动量、估值环境；默认 2021 版，不能由此推断历史分类当时已存在 |
| `index_daily` | `close`、`pct_chg`、`vol`、`amount` | 市场/基准收益、波动、相对强弱；不包含申万行业行情 |
| `index_weight` | `index_code`、`con_code`、`trade_date`、`weight` | 历史成分与权重；官方为月度数据，不是每日成员变化或公告时间序列 |

来源：[行业分类](https://tushare.pro/document/2?doc_id=181)、[行业成员](https://tushare.pro/document/2?doc_id=335)、[申万日线](https://tushare.pro/document/2?doc_id=327)、[指数日线](https://tushare.pro/document/2?doc_id=95)、[指数权重](https://tushare.pro/document/2?doc_id=96)。

分类 ID 不应作为可做大小比较的数值因子。历史有效成员信息与历史公告可见性也不同：这些接口的日期不能自动证明当时已经公布。指数历史回算值与真实发布后的值应区分；具体起点和修订完整性需实测。

### 3.3 资金流与两融独立接入

`moneyflow` 的首批候选列：`buy_lg_amount`、`sell_lg_amount`、`buy_elg_amount`、`sell_elg_amount`、`net_mf_amount`。前四列可计算自定义大额主动成交差额，再除以当日成交额或市值；供应商净流入独立保留。官方按主动买卖单、订单金额分桶，明确提示 `net_mf_amount` 不能由大小单总和简单相减复刻，也不能把大单等同于机构身份。[moneyflow](https://tushare.pro/document/2?doc_id=170)

`margin_detail` 的首批候选列：`rzye`、`rzmre`、`rzche`、`rqye`、`rqyl`、`rzrqye`，可派生融资净买入和融资余额/市值。金额列为元、`rqyl` 为股；`rqmcl` 的文档单位混合股/份/手，先限定证券类型再标准化。[margin_detail](https://tushare.pro/document/2?doc_id=59)

必须关联历史两融标的状态，避免把“非两融标的无数据”填成零余额。`margin_secs` 提供按交易日、股票、交易所的资格列表，覆盖沪深京并包含 ETF，需要按当前 A 股股票范围过滤。[margin_secs](https://tushare.pro/document/2?doc_id=326)

## 4. 预告、快报和股权结构：后续独立能力

| 数据组 | 确切字段 | 推荐研究方式 |
| --- | --- | --- |
| 业绩预告 | `type`、`p_change_min`、`p_change_max`、`net_profit_min`、`net_profit_max`、`last_parent_net`、`ann_date`、`first_ann_date` | 增长区间、扭亏、预告修订；不要把区间中点当正式财报 |
| 业绩快报 | `revenue`、`operate_profit`、`total_profit`、`n_income`、`total_assets`、`total_hldr_eqy_exc_min_int`、`ann_date`、`is_audit` | 单独的提前披露值及其后来与正式报告的差异 |
| 披露计划 | `pre_date`、`actual_date`、`ann_date`、`modify_date` | 公告发现、预计财报事件距离；计划日不等于财务数据已知 |
| 十大股东/流通股东 | `hold_amount`、`hold_ratio`、`hold_float_ratio`、`holder_type`、`ann_date`、`end_date` | 集中度和结构变化；股东身份归并、持股范围需要固定合同 |
| 股东人数 | `holder_num`、`ann_date`、`end_date` | 已公布户数的变化，不能假定每个季度都覆盖 |
| 限售股解禁 | `float_share`、`float_ratio`、`ann_date`、`float_date`、`holder_name`、`share_type` | 在研究时点已公告、未来指定区间的解禁压力 |

来源：[forecast](https://tushare.pro/document/2?doc_id=45)、[express](https://tushare.pro/document/2?doc_id=46)、[disclosure_date](https://tushare.pro/document/2?doc_id=162)、[top10_holders](https://tushare.pro/document/2?doc_id=61)、[top10_floatholders](https://tushare.pro/document/2?doc_id=62)、[stk_holdernumber](https://tushare.pro/document/2?doc_id=166)、[share_float](https://tushare.pro/document/2?doc_id=160)。

预告利润上下限为万元，快报的主要金额列为元；预告页面仅把 `last_parent_net` 明确称为归母，快报 `n_income` 的说明也仅写净利润，不能未经核对就与 `income.n_income_attr_p` 合并为同一事实。[forecast](https://tushare.pro/document/2?doc_id=45)、[express](https://tushare.pro/document/2?doc_id=46)

预告修订必须使用该版本的公告日，不能统一使用 `first_ann_date`。尚未到解禁日并不表示该事件一定未知：只要相关预告在研究时点已公布，可研究已知未来事件；需要保存当时计划版本，避免用后续修订替换历史。十大流通股东接口中 `hold_change` 空值还可能表示新进，不能一律作为零变化。[forecast](https://tushare.pro/document/2?doc_id=45)、[share_float](https://tushare.pro/document/2?doc_id=160)、[top10_floatholders](https://tushare.pro/document/2?doc_id=62)

## 5. 官方提取边界、覆盖与更新时间

本表记录官方文档承诺，不是当前账号已验证能力。“未载”表示本次所查接口页未给出该信息。历史起点应最终细化到列、证券与日期；官方写“全部历史”不能证明退市证券或每个字段从同一天起完整。文档更新时间按来源原述记录，入库可用时间仍须保存实际观察证据。

| 接口 | 历史与更新说明 | 权限 | 单次提取与切分边界 |
| --- | --- | --- | --- |
| [daily_basic](https://tushare.pro/document/2?doc_id=32) | 可按日取历史；未给统一最早日期；交易日 15–17 点 | 2000；5000 无总量限制 | 6000 行；代码或交易日二选一；长历史按交易日分片 |
| [income](https://tushare.pro/document/2?doc_id=33)、[balancesheet](https://tushare.pro/document/2?doc_id=36)、[cashflow](https://tushare.pro/document/2?doc_id=44) | 总表写全部历史/实时更新，未承诺统一起始年或完整修订链 | 普通接口 2000；`*_vip` 5000 | 普通接口按单股；VIP 可按报告期全市场；页面未给统一行数上限；三表 `start_date/end_date` 按公告日 |
| [fina_indicator](https://tushare.pro/document/2?doc_id=79) | 总表写全部历史/随财报更新；逐列起点未载 | 2000；VIP 5000 | 普通页声明 100 行；按日期缩小请求；`start_date/end_date` 按报告期；VIP 全市场的完整性需独立验证 |
| [dividend](https://tushare.pro/document/2?doc_id=103) | 详细页起点 2000-01-01；每日 20–21 点 | 2000 | 2000 行；代码/公告/登记/除息/实施公告日期至少一个；未公布通用分页合同 |
| [moneyflow](https://tushare.pro/document/2?doc_id=170) | 2010 年起，描述为沪深 A 股；总表写交易日 19 点 | 2000 起 | 6000 行，支持单日全市场；量为手、金额为万元 |
| [margin_detail](https://tushare.pro/document/2?doc_id=59) | 总表写 2010 年起；详细页写约次日 8:30 发布；深/北周五数据下周一上午更新 | 2000 | 6000 行；按交易日和证券切分；不能用于原交易日收盘即已知的信号 |
| [forecast](https://tushare.pro/document/2?doc_id=45) | 总表写全部历史；详细页写每日 20–21 点 | 2000；VIP 5000 | 3500 行；普通页同时给精确公告日示例和单股/VIP提示，批量边界必须实测，不能把默认结果当全量 |
| [express](https://tushare.pro/document/2?doc_id=46) | 总表写全部历史/实时更新，具体起点未载 | 2000；VIP 5000 | 普通单股、VIP 报告期全市场；行数上限未载 |
| [disclosure_date](https://tushare.pro/document/2?doc_id=162) | 总表写全部历史/定期更新 | 2000 | 6000 行；可按报告期、代码、计划/实际日期切分 |
| [index_classify](https://tushare.pro/document/2?doc_id=181) | 提供 SW2014/SW2021 分类；刷新频率未载 | 2000 | 层级与分类来源切分；行数上限未载 |
| [index_member_all](https://tushare.pro/document/2?doc_id=335) | 有纳入/剔除日期；统一起点、更新频率未载 | 2000 | 2000 行；按三级行业或股票切分；含历史时明确 `is_new` |
| [sw_daily](https://tushare.pro/document/2?doc_id=327) | 默认 SW2021；交易日 18:30；统一起点未载 | 5000 | 4000 行；代码/日期切分；成交量为万股、金额/市值为万元 |
| [index_daily](https://tushare.pro/document/2?doc_id=95) | 逐指数历史；页内未给统一起点、固定入库时间 | 2000；5000 频次更高 | 按指数/日期；页内未声明统一行数上限；量为手、金额为千元 |
| [index_weight](https://tushare.pro/document/2?doc_id=96) | 月度，统一历史起点未载 | 2000 | 按指数与月份；不可假定月内每个交易日都有快照 |
| [top10_holders](https://tushare.pro/document/2?doc_id=61)、[top10_floatholders](https://tushare.pro/document/2?doc_id=62) | 报告期快照+公告日；统一起点、刷新频率未载 | 2000；5000 频次更高 | 单股、报告期范围；行数上限未载；持股数量为股，比率为百分比 |
| [stk_holdernumber](https://tushare.pro/document/2?doc_id=166) | 不定期公布；统一起点未载 | 2000 | 3000 行；日期范围按公告日 |
| [share_float](https://tushare.pro/document/2?doc_id=160) | 总表写定期更新；起点未载 | 详细页 120，与总表 3000 冲突，待实测 | 6000 行；日期范围按解禁日；股数单位为股，不能沿用 daily_basic 的万股 |
| [margin_secs](https://tushare.pro/document/2?doc_id=326) | 盘前每日；统一起点未载 | 2000；5000 无总量限制 | 6000 行；交易所/证券/日期切分，包含 ETF |
| [stk_premarket](https://tushare.pro/document/2?doc_id=329) | 每日 9:00、18:10 两次；起点未载 | 独立开通，与积分无关 | 8000 行；日期/代码切分；股本为万股 |

表中“总表”为 [Tushare 数据更新及权限说明](https://tushare.pro/document/1?doc_id=108)。`dividend` 的旧示例出现 2000 年前记录，但应以详细页起点说明作为计划边界，不能据示例宣称更早年份完整。[dividend](https://tushare.pro/document/2?doc_id=103)

平台级额度当前为：2000 以上每分钟 200 次、每天每 API 100000 次；5000 以上每分钟 500 次、常规数据无每日总量限制。单独权限与积分权限是两套机制，接口自身的行数/频次约束仍存在。本次已实测第 0.3 节五个普通接口成功，但未读取账号积分档位、验证其他接口或 VIP 权限，也不据此估算确定的全量回填耗时。[积分与频次](https://tushare.pro/document/1?doc_id=290)

提取实现应按接口选择固定切分方式并验证完整性：检查返回达到上限的情况、证券范围、日期覆盖、去重前后行数和重复版本。上述页面没有给出统一 `limit/offset` 保证；某个参数被服务器接受也不能证明没有截断。不能用“只取第一页”或“出错后换接口”的方式产生看似完整的研究数据。

## 6. 历史可见性和数据质量是扩展的一部分

1. **保存来源版本。** 公告日、实际公告日、报告期、报表类型、公司类型和 payload 身份要保留。官方说明重复财务记录可能来自修订，`update_flag=1` 只是修正后/较新标志；不能只保留今天最新版本再回填到过去。[官方 FAQ](https://tushare.pro/document/1?doc_id=122)
2. **分清报告期、有效期与首次观察时间。** 2019 年报数据在 2020 年披露，不在 2019 年末即可使用。对后来才观察到、没有可靠历史修订日期的新 payload，只能按现有系统的观察修订规则进入后续时间。公开 API 文档没有承诺完整的逐次历史发布档案。
3. **对每个派生值记录组成输入。** TTM、单季、同比和平均资产需要多个报告；先在研究时点选择当时已知且匹配的版本，再做期间计算。扩大日期窗口不允许把未来修订版本带回早期交易日。
4. **盘后与次日信息区别处理。** 收盘行情、晚间资金流、晚间预告、次日两融需要各自的可用时间。单纯存在 `trade_date` 或 `ann_date` 不足以证明当日决策前已经获得数据。[资金流更新时间](https://tushare.pro/document/1?doc_id=108)、[预告](https://tushare.pro/document/2?doc_id=45)、[两融](https://tushare.pro/document/2?doc_id=59)
5. **历史证券池不能由现存股票反推。** `stock_basic` 默认是当前上市状态 L，也能查询退市等状态及上市/退市日；历史研究应包含当时存续的证券。其当前 `industry`、实控人等属性不能默认为完整历史序列。[stock_basic](https://tushare.pro/document/2?doc_id=25)
6. **交易约束优先复用。** 涨跌停、停牌和上市年龄首先用于股票池与执行模型，再决定哪些允许作者引用。`stk_limit` 提供当日涨跌停价，`suspend_d` 有停复牌和日内停牌段；日频无法由单个涨停价断言全天一定无法成交。[stk_limit](https://tushare.pro/document/2?doc_id=183)、[suspend_d](https://tushare.pro/document/2?doc_id=214)
7. **空值要能解释。** 至少区分未上市、不适用、尚未披露、缺源、权限失败、分页不完整。晚上市股票没有 TTM、非两融标的没有融资余额、亏损公司的供应商 PE 为空，都不是填零理由。
8. **显示逐字段覆盖。** 目录应显示实际覆盖起点/终点、研究股票池内覆盖率、缺失原因、最新报告期与观察时间、单位、公司类型适用范围和来源版本。不能用家族总体 ready 代替每个新增字段的数据质量说明。

`bak_basic` 的历史股票快照从 2016 年起，5000 积分、7000 行，并含不同单位的财务/股本字段；可作为交叉核验来源，不能覆盖 2010 年起的所有历史，也不建议作为 `daily_basic` 或财报缺失时的自动替代。[bak_basic](https://tushare.pro/document/2?doc_id=262)

## 7. 首轮交付建议和重建判断所需证据

首轮建议交付两个闭环：

- **规模/价值闭环**：日频股本与市值、换手率；三项核心财务流量的 TTM；明确权益口径；能研究“价值 + 盈利改善”和“规模 + 流动性”而不混淆分母。
- **成长/质量闭环**：单季与同比、平均资产/权益、营业收入/成本、合并净利润、资本支出后的现金剩余；能比较“增长加速”“现金利润匹配”“高盈利能力 + 低负债”。

供应商 ROE/PE/PB、资金流和事件指标可以扩展，但应保持来源和口径可辨识。既有量价运算能计算的动量、波动、均价偏离等先用公式示例，不再为每个窗口复制一套数据字段。

从来源角度，重建问题需要逐组判定：

| 计划变化 | 先检查什么 | 可能需要的数据工作 |
| --- | --- | --- |
| 增加已采集的三表列 | 原始响应、Canonical 是否都保留该列及有效来源版本 | 注册字段 + 新投影/解析；可能复用原始数据 |
| 增加 TTM、单季、同比 | 数据集起点前是否保留足够季度/年度种子，且当时已可见 | 从已保留的原始历史补足种子并重做相关投影；源历史不足才重新采集 |
| 增加 daily_basic | 当前是否已采集并保存整个目标历史 | 新增日频家族回填，再发布带新家族的数据版本 |
| 增加 fina_indicator、分红、资金流、两融、预告 | 是否已有这些接口的来源对象及完整性证据 | 缺失组各自采集/回填，建设自己的日期、版本和缺失合同 |
| 新增纯公式 | 所有输入是否已可用且语义不变 | 通常不需要重新向 Tushare 取数 |

上表是来源层的工作分类；结合第 0 节实际库存，可以把当前系统的实施范围进一步缩小如下。

## 8. 当前数据集到底需要怎样重建

### 8.1 结论：新增家族回填，财务局部重投影，再发布新 Generation

目前不存在必须清空数据库、删除旧数据卷、重拉整套行情的依据。现有发布模型已允许在一个 Head 下独立刷新家族，并通过不可变 Manifest 引用复用未变化对象。[ADR-0181](../adr/0181-refresh-dataset-families-independently-under-one-head.md)、[财务组合逻辑](../../apps/core/src/thesistrace/data/generation_store.py#L578)

| 变化 | 当前证据 | 需要做的工作 | 可复用的部分 |
| --- | --- | --- | --- |
| 开放已有财务列，沿用年报/最新报告期口径 | 生产三表存在这些来源列 | 字段声明、适用性和缺失校验、序列解析与新 root 的字段清单；没有新历史依赖时无需重新下载或重写宽表 | 原财务对象、行情、行业、基准 |
| 增加 TTM/单季/同比并从 2010 开始研究 | 当前 Canonical pre-start seeds 不足；原始样本保留更早季度 | 根据新字段报告期依赖，从已留原始批次补种子，重投影受影响财务分区，发布新 Financial family 和 root；缺少必要来源时才补采 | 原始批次及其观察证据，未变化财务分区、行情、行业、基准 |
| 增加市值/股本/换手率 | 当前生产 Generation 没有 daily_basic 家族，代码也未接入 | 建设日频家族，按交易日回填声明覆盖区间，再接日更；扩展当前 reader/validation/准入 | 原有历史标的、日历、行情与全部其他家族 |
| 增加扣非利润/租赁负债等未保留列 | `profit_dedt` 需 fina_indicator；当前 BS 来源合同没有 `lease_liab` | 新来源或新字段合同的采集、历史可用性与完整性核对；不得让新 schema 默默混入旧合同 | 旧来源对象与已发布研究继续保留 |
| 增加分红、资金流、两融、预告等 | 当前生产家族列表不含这些能力 | 各组独立采集/回填、可用时间规则、研究序列解析，再组合发布 | 行情、财务、行业等已有家族 |
| 新增动量、波动、负债率等纯公式 | 输入字段及现有运算已可满足 | 保存新 Alpha/研究定义；输入与语义不变时不需要新数据 Generation | 当前数据版本 |

新字段只有进入新 Generation 的 `field_availability` 后才可用于新研究。当前准入已经拒绝不在此清单内的字段，因此发布目录也要与该清单、家族/字段覆盖同步；只部署新的字段常量会出现“目录显示了，提交仍被拒绝”的问题。[字段准入](../../apps/core/src/thesistrace/research_run/service.py#L3827)、[Generation 字段清单](../../apps/core/src/thesistrace/data/generation_store.py#L618)

### 8.2 2010 年起点的种子数据是实际要补的部分

当前 `_retain_coverage_versions` 的规则是：可用时间在覆盖起点及以后的版本保留；更早版本只为起点已经在股票范围内的证券保留种子。每个 endpoint × instrument 最后只留下一个 `report_type=1` 的种子，利润表和现金流还要求年报。[当前代码](../../apps/core/src/thesistrace/data/financial_candidate.py#L1866)、[ADR-0184](../adr/0184-start-financial-coverage-in-2010-with-minimal-pre-start-seeds.md)

例如，假设 2010-01-04 当时最新披露的期间是 2009Q3：

```text
TTM(2009Q3) = FY2008 + YTD2009Q3 − YTD2008Q3
Q3(2009)    = YTD2009Q3 − YTD2009Q2
Q3同比     = Q3(2009) / Q3(2008) − 1   （这里假设基期为正）
```

仅保留 FY2008 无法给出上述结果。若还提供 TTM 同比，需要比较 2008Q3 的 TTM，依赖可能继续延伸到 FY2007、YTD2007Q3。种子保留深度必须从字段依赖推导，不能简单固定“多保留上一年”或把所有早期缺值补零。

生产样本确实保存了这些更早报告期的原始行，因此应先重用 Raw，而不是重新抓全部历史。实施前仍需做全目标证券的依赖完整性盘点；不满足依赖的字段/证券保持缺失或声明更晚有效起点。当前 ready 与 2010 的家族起点不保证新增 TTM/同比能从首日全覆盖。

重新投影必须保留原始 checkpoint 的 `first_observed_at`、来源发布日期、原始 hash 和修订关系；不能把重建时间当作第一次观察，也不能只取一个最新 raw batch 丢弃旧版本。TTM 任一组成报告发生修订时，其后结果也要随该版本的有效可用日更新。报告期和版本日期分开查询是已有成熟 PIT 模型的基本做法。[现有版本投影](../../apps/core/src/thesistrace/data/financial_candidate.py#L1831)、[Qlib 官方 PIT 设计](https://qlib.readthedocs.io/en/stable/advanced/PIT.html)

具体哪些 Parquet 可原样复用，要以新分区与种子校验结果为准；无需预设财务三表全部重写，更不需要重算未变化的行情家族。

### 8.3 要改动的是明确的数据边界

- **财务解析**：当前只把投影分成 `annual` 和 `latest_reported`。必须实现真实的报告期选择和组合运算；仅把 metadata 写成 TTM 会继续走原有选择路径。[financial_series.py](../../apps/core/src/thesistrace/data/financial_series.py#L44)
- **新家族**：新增日频股本/市值来源应有自己的 schema、coverage、collector 和读取分支；沿用现有 family/reader 边界，补完整的成功与拒绝行为，不引入通用插件体系。
- **可用性**：扩展 DataDependencies、admission、批量研究和 DailyTrack 的依赖检查。新字段不能因行情 ready 就被放行，也不能因某个可选新接口未覆盖而阻塞纯行情研究。
- **公司类型**：官方文档现有 `comp_type=7`，当前财务读取限定 1–4。新增类型和非金融专用字段要显式验证适用性；现有 raw 允许保存不等于 Alpha reader 已经支持。[当前筛选](../../apps/core/src/thesistrace/data/financial_series.py#L312)
- **不可变性与升级**：现有 `revenue`、`net_profit` 继续保留 latest FY 意义；TTM、单季建立新字段身份。已有 Run/Result 不自动重算，新研究 pin 新 Generation。若改变种子/持久化合同，需要显式、可验证、保留数据的升级，并验证旧 pin 读取和旧字段结果等价；不能直接改全局 seed 校验常量、schema 指纹或覆盖旧对象来绕过验证。[字段不可变](../adr/0014-keep-canonical-field-definitions-immutable.md)、[Run 固定 Generation](../adr/0190-freeze-data-generation-at-researchrun-admission.md)、[当前种子覆盖校验](../../apps/core/src/thesistrace/data/financial_candidate.py#L2794)、[仓库迁移与测试约束](../../AGENTS.md)

这里的“新 Generation 发布”和“数据库 schema 迁移”是两个不同动作。增加源数据家族可能只涉及新对象、Manifest 和必要的队列状态；是否要改 PostgreSQL schema 应由具体实现决定，不应为字段扩展直接重建数据库。

## 9. 建议的实际交付顺序

### 第一批：日频规模与估值基础

新增七项：总市值、流通市值、总股本、流通股本、自由流通股本、流通换手率、自由流通换手率。来源统一为 `daily_basic`，完成历史回填、日更和 coverage 后发布独立家族。与现有年报利润、权益组合，可以先研究清晰标记为年报口径的盈利收益率和账面市值比。

供应商 PE/PB/PS/股息率可在同一来源批次留存，但开放时使用明确的来源身份；其财务分母历史版本不透明，不能默认为自行构建的 PIT 估值。`volume_ratio` 无完整窗口说明，不是首批依赖。

### 第二批：财务期间和质量基础

| 子组 | 首批研究值 | 来源/处理 |
| --- | --- | --- |
| TTM | 营业总收入 TTM、归母利润 TTM、经营现金流 TTM | 现有三项流量的多报告期投影 |
| 单季与成长 | 三项流量的单季值；营业总收入、归母利润的同季度同比；明确同报告期的资产增长 | 累计差分与跨年报告期比较 |
| 利润与成本口径 | 营业收入 TTM、营业成本 TTM、合并净利润 TTM | 已存 `revenue`、`oper_cost`、`n_income` |
| 平均资本 | 与利润期间匹配的两点平均归母权益、合并资产 | 已存 BS 的同期间起止报告值 |
| 现金与资产质量 | 资本支出 TTM、货币资金、应收账款、存货、商誉、流动资产/负债 | 已保存列的期间投影或最新报告期值 |

在这些研究值上提供 ROE、毛利率、现金利润匹配、资产负债率、资本支出后经营现金剩余等公式示例。对平均资本、不同表的截止期间选择、负分母和金融企业，先固定合同再开放。扣非利润、租赁负债等当前未保存的列另立数据采集项，不阻塞已存列的交付。

### 第三批：股息及其他研究方向

先完成 dividend 的实施事件和可见日期，再做股息持续性；有明确研究任务时，分别接资金流/两融、预告/快报、股东/解禁。行业中性化和已有基准继续复用，新增行业收益或基准序列进入公式属于另一项明确的输入能力。

验收应按研究问题，而非字段条数：

1. 能表达并提交“规模 + 流动性”“年报估值”“TTM 价值 + 盈利改善”“现金利润匹配 + 低负债”。
2. 在 2010 起点、Q1/Q4 切换、晚披露、历史修订、缺报和负基数上与独立报告期算例一致；行式/列式、回测/跟踪使用同一合同。
3. 未变旧字段在新旧 Generation 的共同区间结果等价；旧 pin 能读取，未发布字段拒绝，Head 并发变更不能发布过期组合。
4. 每项新来源有自身的历史覆盖、缺失分布、日更恢复和发布证据；不以家族 ready 替代字段有效样本检查。测试选择遵循 [AGENTS.md](../../AGENTS.md#testing)，本次为研究文档和只读检查，未执行实现测试或数据回填。

现有股票池是 Top300/1000/2000/3000 流动性 Universe；新增市值后研究的是这些池内的规模效应。若目标是全 A 小市值或其他资产轮动，还需要独立定义历史股票池/资产范围。分组排名、条件筛选、市场序列访问也有各自运算边界，不能把“新增字段”自动解释为完整支持任意策略。

当前最值得开展的工程范围是前两批：**daily_basic 独立家族 + 已有三表的报告期解析与种子补齐**。生产原有数据可作为这次扩展的基底，保留旧对象，准备和验证新候选后再按现有发布流程切换 Head。
