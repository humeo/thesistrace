# 本轮 DSL 字段完整目标清单

> 范围：保留现有 12 个字段，接入 daily_basic 和 fina_indicator，开放两接口的数值字段。本文是待实施清单，不表示新字段已上线；不是所有已存三表原始列的开放计划。
> 本次只更新清单，不执行采集、发布或应用代码修改。

| 范围 | 数量 | 状态 |
| --- | ---: | --- |
| 原有行情 | 6 | 已开放，含义保持不变 |
| 原有三表财务 | 6 | 已开放，含义保持不变 |
| daily_basic 数值字段 | 16 | 拟新增；原始收盘价复用已有数据身份 |
| fina_indicator 数值字段 | 163 | 拟新增 |
| **合计** | **191** | **新增 179 个 DSL 入口** |

数量按不同 DSL 名计，不代表 191 个独立经济信息维度，也不代表每个股票/报告期都有值。元数据不计入。

## 名称和语义

- 延续当前全局唯一的小写 snake_case 名，例如 `rank(roe) - rank(pb)`；不引入当前编译器不接受的点号访问。
- 原有 `revenue`、`net_profit`、`operating_cash_flow` 保留最新可见年报含义，不改成累计、单季或 TTM。
- 新字段尽量沿用常用来源名称；下文对毛利金额、利息费用、较年初增长等易误读名称作一对一调整，不同时提供别名。
- fina_indicator 字段标注为供应商指标。季度、同比、较年初、年化、加权等口径分别解释，不假设所有指标都是 TTM；不在源字段为空时改用三表自算值。
- 清单锁定拟开放的名称、来源和含义。市值/股本按官方明确单位转换；其他字段在接入时逐项核对金额、倍数、百分数和适用范围，不统一除以 100。单位和覆盖验证通过后才发布。

依据：[当前字段定义](../../apps/core/src/thesistrace/data/fields.py)、[作者名称与内部引用分离](../adr/0191-separate-authoring-identifiers-from-canonical-field-references.md)、[不可变字段语义](../adr/0014-keep-canonical-field-definitions-immutable.md)。

## 现有字段：12 个

| DSL 字段 | 中文含义 | TuShare 接口.列 | 口径说明 |
| --- | --- | --- | --- |
| `open` | 复权开盘价 | `daily.open` | 交易日；结合 adj_factor 得到复权值 |
| `high` | 复权最高价 | `daily.high` | 交易日；结合 adj_factor 得到复权值 |
| `low` | 复权最低价 | `daily.low` | 交易日；结合 adj_factor 得到复权值 |
| `close` | 复权收盘价 | `daily.close` | 交易日；结合 adj_factor 得到复权值，保持原有含义 |
| `volume` | 成交股数 | `daily.vol` | 交易日；已规范为股 |
| `amount` | 成交金额 | `daily.amount` | 交易日；已规范为人民币元 |
| `revenue` | 营业总收入 | `income.total_revenue` | 最新可见年报；不是营业收入列，也不是 TTM |
| `net_profit` | 归母净利润 | `income.n_income_attr_p` | 最新可见年报；不是 TTM |
| `operating_cash_flow` | 经营现金流净额 | `cashflow.n_cashflow_act` | 最新可见年报；不是 TTM |
| `assets` | 总资产 | `balancesheet.total_assets` | 最新可见季度或年度报告 |
| `liabilities` | 总负债 | `balancesheet.total_liab` | 最新可见季度或年度报告 |
| `equity` | 归母股东权益 | `balancesheet.total_hldr_eqy_exc_min_int` | 最新可见季度或年度报告；不含少数股东权益 |

## daily_basic：16 个

包含该接口全部 16 个 float 列。`close_raw` 是未复权价格，原有 `close` 是复权价格；不覆盖原名。已有行情也保存原始收盘价，实施时复用既有 Canonical 身份并核验来源一致性。

| DSL 字段 | 中文含义 | TuShare 来源列 | 口径说明 |
| --- | --- | --- | --- |
| `close_raw` | 未复权收盘价 | `close` | 元/股。已有行情也保存原始价，实施时复用 price.close.raw 身份并核对来源一致性。 |
| `total_mv` | 总市值 | `total_mv` | 来源万元；DSL 规范为人民币元。 |
| `circ_mv` | 流通市值 | `circ_mv` | 来源万元；DSL 规范为人民币元。 |
| `total_share` | 总股本 | `total_share` | 来源万股；DSL 规范为股。 |
| `float_share` | 无限售流通股本 | `float_share` | 来源万股；DSL 规范为股。 |
| `free_share` | 自由流通股本 | `free_share` | 来源万股；DSL 规范为股；不同于 float_share。 |
| `turnover_rate` | 无限售流通股换手率 | `turnover_rate` | 分母为无限售流通股数；比例缩放结合实际量/股本样本锁定。 |
| `turnover_rate_f` | 自由流通股换手率 | `turnover_rate_f` | 分母为自由流通股数；不与 turnover_rate 合并。 |
| `volume_ratio` | 供应商量比 | `volume_ratio` | 保留供应商值；文档未明确完整均值窗口。 |
| `pe` | 供应商年度市盈率 | `pe` | 倍数；亏损时来源可为空。 |
| `pe_ttm` | 供应商 TTM 市盈率 | `pe_ttm` | 倍数；不等于已提供独立的 net_profit_ttm。 |
| `pb` | 供应商市净率 | `pb` | 倍数；供应商净资产分母扣除其他权益工具。 |
| `ps` | 供应商年度市销率 | `ps` | 倍数；分母为最新年度营业收入。 |
| `ps_ttm` | 供应商 TTM 市销率 | `ps_ttm` | 倍数；保留供应商定义。 |
| `dv_ratio` | 供应商年度股息率 | `dv_ratio` | 百分数；上一年发生除息的派现口径。 |
| `dv_ttm` | 供应商滚动股息率 | `dv_ttm` | 百分数；除息日和分红报告期均有供应商近 12 个月约束。 |

来源：[daily_basic 官方文档](https://tushare.pro/document/2?doc_id=32)。

## fina_indicator：163 个

按研究用途逐项分组。所有值来自供应商；本轮不额外推导源接口没有独立提供的 `revenue_ttm`、`net_profit_ttm`、`operating_cash_flow_ttm` 等字段。

| 类别 | 数量 |
| --- | ---: |
| 每股指标 | 15 |
| 利润与现金流基础值 | 14 |
| 资产与资本基础值 | 10 |
| 营运效率 | 9 |
| 盈利能力 | 14 |
| 收入与利润结构 | 18 |
| 现金流与资本支出比率 | 5 |
| 财务结构与偿债 | 30 |
| 单季度指标 | 23 |
| 同比增长 | 12 |
| 较年初增长 | 3 |
| 单季度增长 | 10 |
| **合计** | **163** |

### 每股指标（15）

| DSL 字段 | 中文含义 | TuShare 来源列 | 口径说明 |
| --- | --- | --- | --- |
| `eps` | 基本每股收益 | `eps` | 沿用该供应商指标定义。 |
| `dt_eps` | 稀释每股收益 | `dt_eps` | 与期末摊薄每股收益 diluted2_eps 分开；不自行视为相同口径。 |
| `total_revenue_ps` | 每股营业总收入 | `total_revenue_ps` | 营业总收入与 revenue_ps 的营业收入是不同源口径。 |
| `revenue_ps` | 每股营业收入 | `revenue_ps` | 不能与 total_revenue_ps 自动互换。 |
| `capital_rese_ps` | 每股资本公积 | `capital_rese_ps` | 沿用该供应商指标定义。 |
| `surplus_rese_ps` | 每股盈余公积 | `surplus_rese_ps` | 沿用该供应商指标定义。 |
| `undist_profit_ps` | 每股未分配利润 | `undist_profit_ps` | 沿用该供应商指标定义。 |
| `diluted2_eps` | 期末摊薄每股收益 | `diluted2_eps` | 源说明限定期末摊薄，不是 dt_eps 的稀释口径别名。 |
| `bps` | 每股净资产 | `bps` | 沿用该供应商指标定义。 |
| `ocfps` | 每股经营现金净流量 | `ocfps` | 沿用该供应商指标定义。 |
| `retainedps` | 每股留存收益 | `retainedps` | 保留留存收益口径，不与每股未分配利润合并。 |
| `cfps` | 每股现金净流量 | `cfps` | 源说明未限定经营活动；不同于 ocfps。 |
| `ebit_ps` | 每股息税前利润 | `ebit_ps` | 沿用该供应商指标定义。 |
| `fcff_ps` | 每股企业自由现金流 | `fcff_ps` | 沿用该供应商指标定义。 |
| `fcfe_ps` | 每股股东自由现金流 | `fcfe_ps` | 沿用该供应商指标定义。 |

### 利润与现金流基础值（14）

| DSL 字段 | 中文含义 | TuShare 来源列 | 口径说明 |
| --- | --- | --- | --- |
| `extra_item` | 非经常损益额 | `extra_item` | 沿用该供应商指标定义。 |
| `profit_dedt` | 扣非净利润 | `profit_dedt` | 官方简述未明确归母范围；不直接命名为归母扣非利润。 |
| `gross_profit` | 毛利额 | `gross_margin` | 源说明为毛利，不是毛利率；金额单位未由本次探针核验。 |
| `op_income` | 经营活动净收益 | `op_income` | 与营业利润、经营现金净流量是不同源概念。 |
| `valuechange_income` | 价值变动净收益 | `valuechange_income` | 沿用该供应商指标定义。 |
| `interest_expense` | 利息费用 | `interst_income` | 保留供应商列名拼写；官方含义是费用，不能按 income 后缀解释为利息收入。 |
| `daa` | 折旧与摊销 | `daa` | 沿用该供应商指标定义。 |
| `ebit` | 息税前利润 | `ebit` | 沿用该供应商指标定义。 |
| `ebitda` | 息税折旧摊销前利润 | `ebitda` | 沿用该供应商指标定义。 |
| `fcff` | 企业自由现金流 | `fcff` | 供应商 FCFF 口径，不等同于未经调整的经营现金流减资本支出。 |
| `fcfe` | 股权自由现金流 | `fcfe` | 供应商 FCFE 口径，不与 FCFF 或经营现金流减资本支出合并。 |
| `profit_prefin_exp` | 扣财务费用前营业利润 | `profit_prefin_exp` | 沿用该供应商指标定义。 |
| `non_op_profit` | 非营业利润 | `non_op_profit` | 不按列名自行替换为单独的营业外收入。 |
| `rd_exp` | 研发投入总额 | `rd_exp` | 本接口说明为研发投入合计；不自动等同于 income.rd_exp 的研发费用。 |

### 资产与资本基础值（10）

| DSL 字段 | 中文含义 | TuShare 来源列 | 口径说明 |
| --- | --- | --- | --- |
| `current_exint` | 无息流动负债 | `current_exint` | 沿用该供应商指标定义。 |
| `noncurrent_exint` | 无息非流动负债 | `noncurrent_exint` | 沿用该供应商指标定义。 |
| `interestdebt` | 有息债务额 | `interestdebt` | 沿用该供应商指标定义。 |
| `netdebt` | 净债务额 | `netdebt` | 沿用该供应商指标定义。 |
| `tangible_asset` | 有形资产额 | `tangible_asset` | 沿用该供应商指标定义。 |
| `working_capital` | 营运资金额 | `working_capital` | 沿用该供应商指标定义。 |
| `networking_capital` | 营运流动资本 | `networking_capital` | 供应商与 working_capital 分列；未展开公式，不能擅自合并或改写计算口径。 |
| `invest_capital` | 全部投入资本 | `invest_capital` | 沿用该供应商指标定义。 |
| `retained_earnings` | 留存收益额 | `retained_earnings` | 沿用该供应商指标定义。 |
| `fixed_assets` | 固定资产合计 | `fixed_assets` | 沿用该供应商指标定义。 |

### 营运效率（9）

| DSL 字段 | 中文含义 | TuShare 来源列 | 口径说明 |
| --- | --- | --- | --- |
| `invturn_days` | 存货周转天数 | `invturn_days` | 沿用该供应商指标定义。 |
| `arturn_days` | 应收账款周转天数 | `arturn_days` | 沿用该供应商指标定义。 |
| `inv_turn` | 存货周转率 | `inv_turn` | 沿用该供应商指标定义。 |
| `ar_turn` | 应收账款周转率 | `ar_turn` | 沿用该供应商指标定义。 |
| `ca_turn` | 流动资产周转率 | `ca_turn` | 沿用该供应商指标定义。 |
| `fa_turn` | 固定资产周转率 | `fa_turn` | 与 total_fa_trun 的固定资产合计周转率保持不同源身份。 |
| `assets_turn` | 总资产周转率 | `assets_turn` | 沿用该供应商指标定义。 |
| `turn_days` | 营业周转周期 | `turn_days` | 官方定义为营业周期，不自动解释为已扣除应付账款周期的现金转换周期。 |
| `total_fa_trun` | 固定资产合计周转率 | `total_fa_trun` | 保留供应商 trun 拼写；不静默并入 fa_turn。 |

### 盈利能力（14）

| DSL 字段 | 中文含义 | TuShare 来源列 | 口径说明 |
| --- | --- | --- | --- |
| `net_profit_margin` | 销售净利率 | `netprofit_margin` | 沿用该供应商指标定义。 |
| `gross_profit_margin` | 销售毛利率 | `grossprofit_margin` | 这是比率字段；gross_margin 是毛利额。 |
| `roe` | 净资产收益率 | `roe` | 供应商报告期口径；官方未标 TTM、年化或加权平均，不能自行赋予这些含义。 |
| `roe_waa` | 加权平均净资产收益率 | `roe_waa` | 不以简单期初期末权益平均的自算比率替代。 |
| `roe_dt` | 扣非净资产收益率 | `roe_dt` | 源说明为扣除非经常损益的回报率，未标 TTM。 |
| `roa` | 总资产报酬率 | `roa` | 与总资产净利率、年化总资产收益率分列，不擅自合并。 |
| `npta` | 总资产净利润指标 | `npta` | 官方简述为总资产净利润，未展开公式；不据缩写自动等同于 ROA。 |
| `roic` | 投入资本回报率 | `roic` | 供应商口径，未标 TTM；投入资本和利润构造不由本清单推定。 |
| `roe_yearly` | 年化净资产收益率 | `roe_yearly` | 年化不等于 TTM，保留供应商年化方式。 |
| `roa2_yearly` | 年化总资产收益率 | `roa2_yearly` | 与 roa_yearly 的年化总资产净利率不同。 |
| `roe_avg` | 增发条件平均净资产收益率 | `roe_avg` | 官方说明带有增发条件限定；不是普通两点平均权益 ROE 的别名。 |
| `roa_yearly` | 年化总资产净利率 | `roa_yearly` | 与 roa2_yearly 的年化总资产收益率不同，不能按相近列名合并。 |
| `roa_dp` | 杜邦总资产净利率 | `roa_dp` | 沿用该供应商指标定义。 |
| `roic_yearly` | 年化投入资本回报率 | `roic_yearly` | 年化不等于 TTM，也不与 roic 自动互换。 |

### 收入与利润结构（18）

| DSL 字段 | 中文含义 | TuShare 来源列 | 口径说明 |
| --- | --- | --- | --- |
| `cogs_of_sales` | 销售成本占比 | `cogs_of_sales` | 沿用该供应商指标定义。 |
| `expense_of_sales` | 销售期间费用占比 | `expense_of_sales` | 沿用该供应商指标定义。 |
| `profit_to_gr` | 净利润/营业总收入 | `profit_to_gr` | 官方未进一步明确净利润的归属范围，不擅自改为归母净利润。 |
| `saleexp_to_gr` | 销售费用/营业总收入 | `saleexp_to_gr` | 沿用该供应商指标定义。 |
| `adminexp_of_gr` | 管理费用/营业总收入 | `adminexp_of_gr` | 沿用该供应商指标定义。 |
| `finaexp_of_gr` | 财务费用/营业总收入 | `finaexp_of_gr` | 沿用该供应商指标定义。 |
| `impai_ttm` | 资产减值损失/营业总收入 | `impai_ttm` | 列名带 ttm，但当前官方描述没有标明 TTM；不靠列名补充时间口径。 |
| `gc_of_gr` | 营业总成本/营业总收入 | `gc_of_gr` | 沿用该供应商指标定义。 |
| `op_of_gr` | 营业利润/营业总收入 | `op_of_gr` | 沿用该供应商指标定义。 |
| `ebit_of_gr` | 息税前利润/营业总收入 | `ebit_of_gr` | 沿用该供应商指标定义。 |
| `opincome_of_ebt` | 经营活动净收益/利润总额 | `opincome_of_ebt` | 沿用该供应商指标定义。 |
| `investincome_of_ebt` | 价值变动净收益/利润总额 | `investincome_of_ebt` | 官方分子为价值变动净收益，不能按 investincome 名称直接解释为投资收益。 |
| `n_op_profit_of_ebt` | 营业外收支净额/利润总额 | `n_op_profit_of_ebt` | 官方与 nop_to_ebt 的非营业利润分别列示，不自行视为相同数值。 |
| `tax_to_ebt` | 所得税/利润总额 | `tax_to_ebt` | 沿用该供应商指标定义。 |
| `dtprofit_to_profit` | 扣非净利润/净利润 | `dtprofit_to_profit` | 保留供应商利润口径，不自行限定为归母。 |
| `op_to_ebt` | 营业利润/利润总额 | `op_to_ebt` | 沿用该供应商指标定义。 |
| `nop_to_ebt` | 非营业利润/利润总额 | `nop_to_ebt` | 不静默并入 n_op_profit_of_ebt 的营业外收支净额比率。 |
| `profit_to_op` | 利润总额/营业收入 | `profit_to_op` | 官方分母是营业收入，不是按 op 后缀猜测的营业利润。 |

### 现金流与资本支出比率（5）

| DSL 字段 | 中文含义 | TuShare 来源列 | 口径说明 |
| --- | --- | --- | --- |
| `salescash_to_or` | 销售及劳务收现/营业收入 | `salescash_to_or` | 分子是销售商品、提供劳务收到的现金，不是经营现金流净额。 |
| `ocf_to_or` | 经营现金净流量/营业收入 | `ocf_to_or` | 沿用该供应商指标定义。 |
| `ocf_to_opincome` | 经营现金净流量/经营活动净收益 | `ocf_to_opincome` | 分母是经营活动净收益，不是营业收入或营业利润。 |
| `capitalized_to_da` | 资本支出/折旧摊销 | `capitalized_to_da` | 官方给定资本支出与折旧摊销之比，不是研发资本化率。 |
| `ocf_to_profit` | 经营现金净流量/营业利润 | `ocf_to_profit` | 官方分母为营业利润，不是净利润。 |

### 财务结构与偿债（30）

| DSL 字段 | 中文含义 | TuShare 来源列 | 口径说明 |
| --- | --- | --- | --- |
| `current_ratio` | 流动比率 | `current_ratio` | 沿用该供应商指标定义。 |
| `quick_ratio` | 速动比率 | `quick_ratio` | 沿用该供应商指标定义。 |
| `cash_ratio` | 保守速动比率 | `cash_ratio` | 官方名称为保守速动比率，不据 cash_ratio 自行替换成其他现金比率公式。 |
| `debt_to_assets` | 资产负债比率 | `debt_to_assets` | 沿用该供应商指标定义。 |
| `assets_to_eqt` | 权益乘数 | `assets_to_eqt` | 沿用该供应商指标定义。 |
| `dp_assets_to_eqt` | 杜邦权益乘数 | `dp_assets_to_eqt` | 保留杜邦分析口径，不直接与 assets_to_eqt 合并。 |
| `ca_to_assets` | 流动资产占总资产比 | `ca_to_assets` | 沿用该供应商指标定义。 |
| `nca_to_assets` | 非流动资产占总资产比 | `nca_to_assets` | 沿用该供应商指标定义。 |
| `tbassets_to_totalassets` | 有形资产占总资产比 | `tbassets_to_totalassets` | 沿用该供应商指标定义。 |
| `int_to_talcap` | 有息债务/全部投入资本 | `int_to_talcap` | 沿用该供应商指标定义。 |
| `eqt_to_talcapital` | 归母权益/全部投入资本 | `eqt_to_talcapital` | 沿用该供应商指标定义。 |
| `currentdebt_to_debt` | 流动负债占总负债比 | `currentdebt_to_debt` | 沿用该供应商指标定义。 |
| `longdeb_to_debt` | 非流动负债占总负债比 | `longdeb_to_debt` | 官方分子为非流动负债，不是仅长期借款或有息长期债务。 |
| `ocf_to_shortdebt` | 经营现金净流量/流动负债 | `ocf_to_shortdebt` | 官方分母是流动负债，不能由 shortdebt 推断为短期借款。 |
| `debt_to_eqt` | 产权比率 | `debt_to_eqt` | 当前官方简述未展开权益范围，本清单不自行指定为归母权益。 |
| `eqt_to_debt` | 归母权益/负债合计 | `eqt_to_debt` | 沿用该供应商指标定义。 |
| `eqt_to_interestdebt` | 归母权益/有息债务 | `eqt_to_interestdebt` | 沿用该供应商指标定义。 |
| `tangibleasset_to_debt` | 有形资产/负债合计 | `tangibleasset_to_debt` | 沿用该供应商指标定义。 |
| `tangasset_to_intdebt` | 有形资产/有息债务 | `tangasset_to_intdebt` | 沿用该供应商指标定义。 |
| `tangibleasset_to_netdebt` | 有形资产/净债务 | `tangibleasset_to_netdebt` | 沿用该供应商指标定义。 |
| `ocf_to_debt` | 经营现金净流量/负债合计 | `ocf_to_debt` | 沿用该供应商指标定义。 |
| `ocf_to_interestdebt` | 经营现金净流量/有息债务 | `ocf_to_interestdebt` | 沿用该供应商指标定义。 |
| `ocf_to_netdebt` | 经营现金净流量/净债务 | `ocf_to_netdebt` | 沿用该供应商指标定义。 |
| `ebit_to_interest` | 息税前利润/利息费用 | `ebit_to_interest` | 沿用该供应商指标定义。 |
| `longdebt_to_workingcapital` | 长期债务/营运资金 | `longdebt_to_workingcapital` | 保留官方长期债务口径，不自行缩窄为长期借款。 |
| `ebitda_to_debt` | 息税折旧摊销前利润/负债合计 | `ebitda_to_debt` | 沿用该供应商指标定义。 |
| `cash_to_liqdebt` | 货币资金/流动负债 | `cash_to_liqdebt` | 沿用该供应商指标定义。 |
| `cash_to_liqdebt_withinterest` | 货币资金/有息流动负债 | `cash_to_liqdebt_withinterest` | 沿用该供应商指标定义。 |
| `op_to_liqdebt` | 营业利润/流动负债 | `op_to_liqdebt` | 沿用该供应商指标定义。 |
| `op_to_debt` | 营业利润/负债合计 | `op_to_debt` | 沿用该供应商指标定义。 |

### 单季度指标（23）

| DSL 字段 | 中文含义 | TuShare 来源列 | 口径说明 |
| --- | --- | --- | --- |
| `q_opincome` | 单季经营活动净收益 | `q_opincome` | 沿用该供应商指标定义。 |
| `q_investincome` | 单季价值变动净收益 | `q_investincome` | 官方定义是价值变动净收益，不按列名简化为投资收益。 |
| `q_dtprofit` | 单季扣非净利润 | `q_dtprofit` | 官方简述未明确归母范围；不擅自改成归母扣非。 |
| `q_eps` | 单季每股收益 | `q_eps` | 官方未进一步注明基本、稀释或期末摊薄方式，保留源口径。 |
| `q_net_profit_margin` | 单季销售净利率 | `q_netprofit_margin` | 沿用该供应商指标定义。 |
| `q_gross_profit_margin` | 单季销售毛利率 | `q_gsprofit_margin` | 沿用该供应商指标定义。 |
| `q_exp_to_sales` | 单季销售期间费用占比 | `q_exp_to_sales` | 沿用该供应商指标定义。 |
| `q_profit_to_gr` | 单季净利润/营业总收入 | `q_profit_to_gr` | 沿用该供应商指标定义。 |
| `q_saleexp_to_gr` | 单季销售费用/营业总收入 | `q_saleexp_to_gr` | 沿用该供应商指标定义。 |
| `q_adminexp_to_gr` | 单季管理费用/营业总收入 | `q_adminexp_to_gr` | 沿用该供应商指标定义。 |
| `q_finaexp_to_gr` | 单季财务费用/营业总收入 | `q_finaexp_to_gr` | 沿用该供应商指标定义。 |
| `q_impair_to_gr_ttm` | 单季资产减值损失/营业总收入 | `q_impair_to_gr_ttm` | 官方明确为单季度，不能因列名 ttm 后缀标成 TTM。 |
| `q_gc_to_gr` | 单季营业总成本/营业总收入 | `q_gc_to_gr` | 沿用该供应商指标定义。 |
| `q_op_to_gr` | 单季营业利润/营业总收入 | `q_op_to_gr` | 沿用该供应商指标定义。 |
| `q_roe` | 单季净资产收益率 | `q_roe` | 单季度源指标，不是 TTM，也不自动年化。 |
| `q_dt_roe` | 单季扣非净资产收益率 | `q_dt_roe` | 沿用该供应商指标定义。 |
| `q_npta` | 单季总资产净利润指标 | `q_npta` | 官方简述未展开公式；不自动等同于单季 ROA。 |
| `q_opincome_to_ebt` | 单季经营活动净收益/利润总额 | `q_opincome_to_ebt` | 沿用该供应商指标定义。 |
| `q_investincome_to_ebt` | 单季价值变动净收益/利润总额 | `q_investincome_to_ebt` | 分子按官方价值变动净收益解释，不直接改成投资收益。 |
| `q_dtprofit_to_profit` | 单季扣非净利润/净利润 | `q_dtprofit_to_profit` | 沿用该供应商指标定义。 |
| `q_salescash_to_or` | 单季销售及劳务收现/营业收入 | `q_salescash_to_or` | 分子是销售商品、提供劳务收到的现金，不是经营现金流净额。 |
| `q_ocf_to_sales` | 单季经营现金净流量/营业收入 | `q_ocf_to_sales` | 官方分母为营业收入；不是 q_ocf_to_or 的同义字段。 |
| `q_ocf_to_or` | 单季经营现金净流量/经营活动净收益 | `q_ocf_to_or` | 官方分母为经营活动净收益；与 q_ocf_to_sales 的营业收入分母不同，也不同于非单季 ocf_to_or 的命名对应。 |

### 同比增长（12）

| DSL 字段 | 中文含义 | TuShare 来源列 | 口径说明 |
| --- | --- | --- | --- |
| `basic_eps_yoy` | 基本每股收益同比增长率 | `basic_eps_yoy` | 沿用该供应商指标定义。 |
| `dt_eps_yoy` | 稀释每股收益同比增长率 | `dt_eps_yoy` | 沿用该供应商指标定义。 |
| `ocfps_yoy` | 每股经营现金净流量同比增长率 | `cfps_yoy` | 官方说明指每股经营活动现金净流量，不能按前缀认定为 cfps 的一般现金净流量同比。 |
| `op_yoy` | 营业利润同比增长率 | `op_yoy` | 沿用该供应商指标定义。 |
| `ebt_yoy` | 利润总额同比增长率 | `ebt_yoy` | 沿用该供应商指标定义。 |
| `netprofit_yoy` | 归母净利润同比增长率 | `netprofit_yoy` | 官方明确归属于母公司股东，不是未限定归属的净利润。 |
| `dt_netprofit_yoy` | 归母扣非净利润同比增长率 | `dt_netprofit_yoy` | 官方明确归母和扣非范围；不能倒推 profit_dedt 的未说明范围也一定相同。 |
| `ocf_yoy` | 经营现金净流量同比增长率 | `ocf_yoy` | 沿用该供应商指标定义。 |
| `roe_yoy` | 摊薄净资产收益率同比增长率 | `roe_yoy` | 官方为摊薄 ROE 的同比增长率，不是 ROE 的百分点变化，也不证明分子等于 roe。 |
| `tr_yoy` | 营业总收入同比增长率 | `tr_yoy` | 沿用该供应商指标定义。 |
| `or_yoy` | 营业收入同比增长率 | `or_yoy` | 营业收入与 tr_yoy 的营业总收入范围不同。 |
| `equity_yoy` | 净资产同比增长率 | `equity_yoy` | 官方为同比，未进一步说明归母范围；不要与 eqt_yoy 的归母权益较年初增长合并。 |

### 较年初增长（3）

| DSL 字段 | 中文含义 | TuShare 来源列 | 口径说明 |
| --- | --- | --- | --- |
| `bps_ytd_growth` | 每股净资产较年初增长率 | `bps_yoy` | 虽名为 yoy，官方比较基点是年初，不是上年同期。 |
| `assets_ytd_growth` | 总资产较年初增长率 | `assets_yoy` | 虽名为 yoy，官方比较基点是年初，不是上年同期。 |
| `equity_parent_ytd_growth` | 归母权益较年初增长率 | `eqt_yoy` | 官方说明为归母权益相对年初增长，与 equity_yoy 的净资产同比不同。 |

### 单季度增长（10）

| DSL 字段 | 中文含义 | TuShare 来源列 | 口径说明 |
| --- | --- | --- | --- |
| `q_gr_yoy` | 单季营业总收入同比增长率 | `q_gr_yoy` | 沿用该供应商指标定义。 |
| `q_gr_qoq` | 单季营业总收入环比增长率 | `q_gr_qoq` | 沿用该供应商指标定义。 |
| `q_sales_yoy` | 单季营业收入同比增长率 | `q_sales_yoy` | 与 q_gr_yoy 的营业总收入范围分开。 |
| `q_sales_qoq` | 单季营业收入环比增长率 | `q_sales_qoq` | 与 q_gr_qoq 的营业总收入范围分开。 |
| `q_op_yoy` | 单季营业利润同比增长率 | `q_op_yoy` | 沿用该供应商指标定义。 |
| `q_op_qoq` | 单季营业利润环比增长率 | `q_op_qoq` | 沿用该供应商指标定义。 |
| `q_profit_yoy` | 单季净利润同比增长率 | `q_profit_yoy` | 官方未进一步注明归属范围；与明确归母的 q_netprofit_yoy 分开。 |
| `q_profit_qoq` | 单季净利润环比增长率 | `q_profit_qoq` | 官方未进一步注明归属范围；与明确归母的 q_netprofit_qoq 分开。 |
| `q_netprofit_yoy` | 单季归母净利润同比增长率 | `q_netprofit_yoy` | 沿用该供应商指标定义。 |
| `q_netprofit_qoq` | 单季归母净利润环比增长率 | `q_netprofit_qoq` | 沿用该供应商指标定义。 |

来源：[fina_indicator 官方文档](https://tushare.pro/document/2?doc_id=79)。中文含义为文档事实的简述，不表示已独立复算供应商公式或确认所有字段的历史覆盖。

## 与来源名称不同的 DSL 名

| DSL 名 | 来源列 | 区分原因 |
| --- | --- | --- |
| `gross_profit` | `gross_margin` | 来源指毛利金额，不是毛利率。 |
| `gross_profit_margin` | `grossprofit_margin` | 毛利率，与金额分开。 |
| `net_profit_margin` | `netprofit_margin` | 统一单词分隔。 |
| `interest_expense` | `interst_income` | 文档定义为利息费用。 |
| `bps_ytd_growth` | `bps_yoy` | 每股净资产相对年初增长。 |
| `assets_ytd_growth` | `assets_yoy` | 总资产相对年初增长。 |
| `equity_parent_ytd_growth` | `eqt_yoy` | 归母权益相对年初增长。 |
| `ocfps_yoy` | `cfps_yoy` | 文档定义为每股经营现金流同比。 |
| `q_gross_profit_margin` | `q_gsprofit_margin` | 统一毛利率名称，保留单季口径。 |
| `q_net_profit_margin` | `q_netprofit_margin` | 统一净利率名称，保留单季口径。 |

这些调整仅针对拟新增字段，不改动现有名称。

## 保存但不直接作为数值因子的字段

| 来源 | 字段 | 用途 |
| --- | --- | --- |
| daily_basic | `ts_code`、`trade_date` | 证券和日期关联。 |
| daily_basic | `limit_status` | 分类码，0–6 不表示连续经济量；本轮不按普通数值字段开放。 |
| fina_indicator | `ts_code`、`ann_date`、`end_date`、`update_flag` | 证券、报告期、可见时间、版本处理。 |

所有三表已存原始列不会因此自动全部开放。本轮保留原有六个三表字段，新增入口以本表为准。自算 TTM、原始单季收入/利润/经营现金流、披露年龄、新行业/交易状态字段不计入这 191 个。

## 发布与使用要求

- daily_basic 按交易日读取，收盘后数据用于后续执行，不进入同日开盘决策。
- fina_indicator 先选择当时已可见的来源版本，再按报告期取值；不能在报告期结束当天提前使用。选中版本中缺失的列保持缺失，不按列回退旧报告或填零。
- 原始输出列连同身份、日期和更新标记都需保存。字段目录、Generation 可用字段和研究准入同步发布；回测与 DailyTrack 使用同一合同。
- 现有研究保留原 Generation。样本请求成功证明权限和字段形状，不证明全历史非空覆盖；新增字段经过单位、覆盖和历史可见性验证后发布。

新增字段接入后的公式示例：

~~~text
rank(roe) - rank(pb)
rank(netprofit_yoy) + rank(ocf_yoy)
rank(roe) - rank(debt_to_assets)
-rank(total_mv) + rank(amount)
rank(q_netprofit_yoy) + rank(q_roe)
rank(dv_ttm) - rank(pe_ttm)
~~~

示例依赖尚未上线的新字段，当前运行环境仍只有原有 12 个字段。

## 核验依据

2026-09-12 使用生产现有账户进行小样本读取：daily_basic 返回全部 19 个输出列、fina_indicator 返回全部 167 个输出列，其中 float 列分别为 16 和 163。本清单已对齐全部 float 列，并检查 DSL 名合法性、唯一性及与 Builtin 的冲突。

- [实际接口字段探针](../../.scratch/data-field-expansion-20260912/live-tushare-field-probe.json)
- [官方字段名称与类型](../../.scratch/data-field-expansion-20260912/official-field-schema.json)
- [生产现有 DSL 字段](../../.scratch/data-field-expansion-20260912/runtime-evidence.json)
- [逐字段 CSV](dsl-field-catalog-2026-09-12.csv)
- [完整扩展研究](tushare-field-expansion-2026-09-12.md)
