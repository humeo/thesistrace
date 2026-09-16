# TOP3000 Sharpe > 1.2 搜索：研究口径与候选公式

记录日期：2026-09-10。源码基线：`ad16ea9bd8e369c20270d187499cb089b7b7069e`。本笔记核对本地当前实现，供主研究任务在 TOP3000、截止 2026-09-09 的数据上探索；实际 MCP 的 Dataset Release、Data Generation、运行语义版本和截止日仍应从每个 Result 的不可变输入确认。下面的公式通过本地 Alpha 编译器校验，尚不代表获得有效因子或 Sharpe > 1.2；本子任务未提交任何 MCP ResearchRun。

## 1. 最影响结果解释的口径

| 项目 | 当前实现与研究含义 |
|---|---|
| TOP3000 | 每个研究交易日从当天基础股票池，按包含当日在内的最近 20 个交易日平均成交金额降序选择最多 3000 只；同分按 instrument ID。停牌日计 0，窗口要求股票持续在基础池且所需数据完整。数据覆盖最初 19 天用扩展窗口，并限定初始日成员。这是流动性排名，不是市值排名。[构建代码](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/data/canonical_mapping.py:78) |
| 基础股票池 | 沪深交易所的主板、创业板、科创板普通 A 股；按上市、退市日期确定历史资格。这里没有额外的 ST 或盈利过滤条件，不包含北交所。[证券标准化](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/adapters/tushare_provider.py:1675)、[基础池生成](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/adapters/tushare_provider.py:1190) |
| 有效 Alpha 样本 | TOP3000 之后还要求当天有效 raw/adjusted open、正成交金额，以及公式有限值。缺财务值、滚动窗口缺值均可能使每日有效样本少于 3000；不能把声明股票池数当成实际入选数。[市场对齐](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/data/market_series.py:81)、[Alpha 缺失值处理](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/alpha.py:245) |
| 排序方向 | Alpha 越大越优先买入；同 Alpha 按 instrument ID。`rank(x)` 是升序横截面排名，较大原值映射到较高 rank。[策略排序](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:33)、[rank 定义](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/alpha_builtins.py:359) |
| 信号与成交 | 第 t 日收盘后字段形成信号，第 t+1 日开盘按信号选股；固定做多、Top N、目标等权。N 为 1–100，调仓周期为 1–20 个交易日，周期从所选研究起点锚定。先卖再买，受整手、现金和不可成交约束，实际持仓和权重可能偏离目标。[策略执行](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:315)、[信号索引与选股](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:425) |
| 每日估值与最后一天 | NAV 以调整后开盘价估值；最后一日只估值、不新调仓、不强制清仓。因此截止 2026-09-09 的策略终值对应该日开盘，不含该日开盘至收盘收益。原点日从现金开始，下一日才首次建仓。[终值与调仓](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:410)、[持仓估值](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:837) |
| 行业中性化 | `industry` 在每个申万一级行业内部减去当日 Alpha 均值；缺行业和不足 2 个有效成员的行业被剔除。它不是行业等权持仓，也不是市值中性，更不能保证组合行业暴露为零。[实现](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/alpha.py:254) |

过滤之后若有效候选为 k，`target_value = pre_net_nav / max(1, k)`。因此 `0 < k < N` 时按实际 k 只重新等权，仍拟满仓；不会按缺少的名额预留现金。k=0 时已有仓位目标为 0，尝试卖到现金，但卖出仍受停牌/跌停等约束；未到调仓日或处于最后估值日不触发此次退出。个股趋势门控可能减少分散度，不能直接称为组合仓位控制。[目标分母与卖出](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:435)

## 2. Sharpe 的精确复算

从策略日表按 session 顺序取全部净 NAV：`V[0], ..., V[D-1]`。忽略日表首行显示的初始零收益，使用：

```text
r[i] = V[i] / V[i-1] - 1                   i = 1 ... D-1
n = D - 1
mu = sum(r) / n
s = sqrt(sum((r - mu)^2) / (n - 1))        样本标准差，ddof = 1
annualized_volatility = s * sqrt(252)
Sharpe = mu / s * sqrt(252)                固定 risk_free_rate = 0
```

这里使用净收益，包含已扣除的固定交易成本；不是 CAGR/波动率，也不是相对某个指数的超额收益 Sharpe。样本不足两条或波动为零时 Sharpe 为 null。Sharpe 使用整个报告区间的相邻 NAV 收益，不能从首次持仓日再截一段替代；CAGR 则另外使用首次调仓后的投资间隔计算，二者分母口径不同。[完整计算](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:1059)、[CAGR](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:1509)

增量运行维护日收益的一阶和二阶精确矩，最后仍恢复样本标准差及同一 Sharpe；不应因为分块完成而对分块 Sharpe 求均值。[增量路径](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:1366)

最大回撤输出为非负比例 `1 - NAV/running_peak`。换手是包含现金在内的调仓前后权重差绝对值总和的一半；年化换手对全部报告间隔乘 252。[回撤及换手](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:1472)、[年化指标](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:1112)

注意：公式算子 `ts_std` 使用总体标准差 `ddof=0`，这与策略 Sharpe 的 `ddof=1` 不同。[算子定义](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/alpha_builtins.py:439)

## 3. 交易成本、成交约束与可实现性

固定初始资金为 1000 万元。每笔子订单佣金 `max(成交金额 × 0.0003, 5 元)`，双边过户费 `成交金额 × 0.00001`，卖出另收 `成交金额 × 0.0005` 印花税；这些是系统对全部回测日期采用的固定假设，不代表逐日复原历史税率或用户真实佣金。[固定契约](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_run/service.py:276)、[成本公式](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:192)、[按子订单计费](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:951)

毛/净账户复用同一持仓与成交，选股目标和可买数量由净 NAV/净现金约束。毛 NAV 是这条实际交易路径加回累计费用的记账视角，不是把费用设为零后独立再投资、重新生成成交的一条反事实策略。[净 NAV 目标](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:451)、[毛净记账](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:978)

停牌与 data_unavailable 拒绝交易；raw open 达到源数据涨停价时拒绝买入、达到跌停价时拒绝卖出。价格限制取 Canonical evidence，不统一假定所有股票 10%。缺少无法解释的可成交开盘价或价格限制会报错。持仓停牌或 data_unavailable 时沿用上次估值，确认终止上市且无开盘价时按损失清除持仓。[拒单条件](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:208)、[成交前验证](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:883)、[估值延续与退市](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:837)

符合条件的订单全部按开盘成交。模型不包含排队、部分成交、成交量参与率和滑点，所以特别需要区分“固定费用后的模型 Sharpe”和可实现收益。对高换手、小持仓数、偏低流动性候选，后续研究应保留逐日换手、费用拖累、拒单和实际持仓证据，不能仅凭 Sharpe 断言资金容量。[执行 ADR](/Users/koltenluca/code-github/thesistrace/docs/adr/0044-use-a-conservative-full-fill-open-execution-model.md:3)

## 4. 财务 PIT 与字段边界

当前可写字段只有下列 12 个；最终是否允许财务字段还取决于已发布数据的 financial_authoring_ready。[完整字段定义](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/data/fields.py:44)、[财务就绪门控](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/alpha_language/language.py:113)

| 字段 | 含义 |
|---|---|
| `open`, `high`, `low`, `close` | 因果累计调整后的日 OHLC；收盘后可见。 |
| `volume`, `amount` | 当日成交股数、成交金额 CNY。 |
| `revenue`, `net_profit`, `operating_cash_flow` | 最新可见完整年度合并报表的总营业收入、归母净利润、经营活动现金净额；不是 TTM，也不是最新季度数。 |
| `assets`, `liabilities`, `equity` | 最新可见季报或年报合并报表的总资产、总负债、归母权益。 |

源发布日期优先使用 `f_ann_date`，否则 `ann_date`；在其后的第一个研究交易日生效。源公告缺日期的行隔离。相同公告日期、相同逻辑财务组后来才观测到的更正，使用源生效日与首次观测后交易日的较晚者，不能倒灌到旧公告日期。投影按截至该日可见的最新报告期间取值，损益和现金流限制为 12 月 31 日结束的全年报告，合并口径 `report_type=1`。[财务版本投影](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/data/financial_candidate.py:185)、[日期优先级与下一交易日](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/data/financial_candidate.py:2927)、[有效报表筛选](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/data/financial_series.py:310)

由于字段在公告后的研究日才进入该日收盘信号，再在下一日开盘交易，不能把公式新值解释为公告当晚就已经交易。PIT 规则只约束保存下来的源版本；系统不承诺 Tushare 未提供的完整历史更正链。[财务版本 ADR](/Users/koltenluca/code-github/thesistrace/docs/adr/0018-preserve-source-financial-versions-without-inventing-history.md:3)

当前没有市值、总股本、流通股本、EPS 或股息字段。`net_profit/close`、`equity/close` 把公司总量除以每股价格，不是标准 E/P 或 B/P；标准估值分母是市值。`close` 本身为调整价，也不能与 `amount/volume` 的原始成交均价直接混成 VWAP 折溢价指标。[字段目录](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/data/fields.py:44)、[Kenneth French 变量定义](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/variable_definitions.html)

同样，低 `amount` 或较高 `profit/amount` 衡量的是交易活跃度、盈利相对成交金额，不能重命名为“小市值”“低估值”或 E/P。成交金额是市场交易流量，不是公司权益的存量市值；`amount` 低可能关联规模，但现有字段无法验证或剥离这种规模暴露。[成交金额字段](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/data/fields.py:113)、[市值与 E/P 的分母定义](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/variable_definitions.html)

财务比率要按实际字段命名：`net_profit/assets` 是 FY 归母净利/最新总资产的代理，分子分母可能不是同一期；它不是严格平均资产 ROA。最新 FY 收入和现金流也可能因不同报表的可见时间而暂时错期。`-pct_change(assets,252)` 比较两个交易日的最新可见资产，不保证恰好比较连续两个年末报告。[字段选择](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/data/fields.py:162)

质量因子还可能主要选中某些行业而不是选出每个行业的优质公司。例如总资产作分母和净资产作分母，对资产与杠杆结构的依赖不同；现金流/收入口径在不同公司类型间也未做统一调整。应比较行业权重、行业内排序与 `none/industry` 对照。即使去掉行业 Alpha 均值，Top N 组合仍可能集中于少数行业，不能把 `neutralization=industry` 当成中性组合证明。[可适用公司类型与字段口径](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/data/fields.py:130)、[行业处理算法](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/alpha.py:254)

### 正净资产和趋势门控的当前语义

`net_profit/equity` 的负净资产陷阱必须处理：亏损除以负净资产会变成正数，可能被误排为高 ROE。当前可写成 `rank(net_profit / equity + 0 * log(equity))`，让非正/缺失 equity 产生 missing，在 rank 前剔除。`log` 的非正输入返回 missing；行式二元算子任一输入缺失就缺失，列式二元算子要求两侧都 finite，因此 `0 * missing` 不会成为 0，也没有将这段门控常量优化掉。[log 定义](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/alpha_builtins.py:86)、[行式运算](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/series_plan.py:480)、[列式运算](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/series_plan.py:292)

对趋势门控，`signal + 0 * log(close / ts_mean(close, 120) - 1)` 在有效正均价条件下，仅保留 `close > MA120` 的股票。等于、低于 MA、窗口有缺失均输出 missing；这不是把不满足者记 0，也不是用一个很低的分数将其留在股票池。这个门控与上文实际 k 只等权规则共同决定仓位和集中度。[完整窗口规则](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/alpha_builtins.py:411)、[列式有限值运算](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/series_plan.py:292)

最小数值核对同时运行行式 Alpha matrix 与列式 execution matrix，结果完全相同：

| 输入情况 | 无门控的表现 | 正净资产/趋势门控结果 |
|---|---|---|
| profit=-2, equity=-1 | `rank(profit/equity)` 在 5 个有效样本中排 0.75 | 被剔除 |
| equity=0 或缺失 | 比率缺失 | 被剔除 |
| profit=2, equity=10 | 比率 0.2 | 保留 |
| profit=1, equity=0.000001 | 比率 1,000,000、最高 rank | 仍保留且最高 rank；正净资产门控不能解决极薄权益的尾部问题 |
| 120 日窗口前 119 日 close=100，末日 120 | close > MA120 | 保留 `-pct_change(close,5)` 的 -0.2 分数 |
| 同样窗口末日 100、80、0，或窗口缺一条 | 等于/低于 MA 或窗口无效 | 全部剔除 |

以上核对只证明当前表达式和缺失值行为。正权益门控后的指标仍是 FY 利润/最新权益代理，且 `rank` 只压缩数值幅度，不剔除微小正净资产导致的最高分样本。

## 5. Factor 指标能证明什么

三个固定标签期限为 `h = 1, 5, 20`：第 t 日 Alpha 对应 `adjusted_open[t+1+h] / adjusted_open[t+1] - 1`。不是从当日收盘开始的收益；也没有 10 日标签。右边界不足未来开盘价时右删失，不能把未成熟标签记为零。有效入场后确认退市且终点无价时标签为 -1；停牌等已知不可用情况剔除，无解释的数据缺口则报错。[期限及列式标签](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/factor.py:16)、[完整标签边界](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/factor.py:215)

标签不收交易费用，也不执行策略的涨跌停买卖拒单；有有效开盘价就可形成标签。因此具有好 IC 的股票并不一定能按信号方向在该开盘成交。[标签构造](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/factor.py:109)、[策略拒单](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/strategy.py:208)

每日 Pearson IC 是原始 Alpha 与未来标签的横截面相关；Rank IC 是两边平均秩的 Pearson 相关，即 Spearman，平值并列平均秩。每天有效样本少于 30 时不计算。分组 q1 低、q5 高，`top_bottom_return = q5 - q1`。[日指标](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/factor.py:466)

ICIR 是有效日 IC 均值除以样本标准差，没有乘 `sqrt(252)`；`top_bottom_return` 是日分组远期收益差的均值，不是实施了融券、成本和调仓的多空 NAV。5/20 日标签跨日重叠，不能把它们当作独立观测直接乘 `sqrt(252)` 当 Sharpe。Factor evaluation 本身没有策略 Sharpe，必须通过明确的持仓数、调仓周期和费用下的 Strategy Backtest 来确认 >1.2。[汇总计算](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/factor.py:426)、[ICIR](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/factor.py:549)

主任务首轮保存的实时 Result 已提供一个具体反例：`-rank(pct_change(close,5))`，2018-01-02 至 2026-09-09，TOP3000、none、20 只、每日调仓，5 日 Rank IC 为 +0.034095；q1/q2/q3/q4/q5 平均远期收益依次为 -0.2111%/+0.2024%/+0.2162%/+0.2117%/+0.1268%，分组并非单调，q5 不如 q3/q4。策略净 Sharpe 为 -3.319618，净 CAGR 为 -60.1487%，最大回撤 99.9567%，结束时无持仓。这个结果表明全截面平均 IC、五分位 q5 与极端 Top20 是不同问题；不能由正 IC 直接推断 Top20 有正 Sharpe。下一轮可研究避开最极端输家、较温和的反转分位以及与低风险/质量结合，但这些是待验证假设，这些数字本身不构成计算缺陷证据。[实时 Result 留档](/Users/koltenluca/code-github/thesistrace/.scratch/top3000-sharpe-search-20260910/results/run_695cd664ad654723969c.json)

## 6. 15 个可编译的候选

以下方向是先验研究假设，窗口为首轮固定值，不是已经找到的最佳参数。负号已按“大值买入”处理。表中的“独立”是经济测量角度，不承诺结果统计独立；同家族及高度相关候选要在最终数量里去重。财务指标的跨行业经济含义差异大，建议同时保留 `none` 和 `industry` 对照，并明确这只是 Alpha 行业内去均值。

| ID | 经济角度 | Formula | 有效历史长度 | 解释与限制 |
|---|---|---|---:|---|
| M01 | 短期反转/流动性供给 | `-pct_change(close, 5)` | 5 | 买入近期下跌较多者；可能被成本和跌停拒单影响。反转速度与流动性状态相关。[反转原始研究](https://www.nber.org/papers/w30917) |
| M02 | 中期趋势，跳过近月 | `pct_change(lag(close, 20), 120)` | 140 | 衡量 t-140 至 t-20 的涨幅。借鉴排除最近月的动量思路，120 日是本次候选，不是 French 原组合的精确复制。[官方动量构建](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/det_mom_factor_daily.html) |
| M03 | 日内交易压力 | `-ts_mean(close / open - 1, 5)` | 4 | 将 close-close 反转拆成日内部分；方向要在 A 股开盘到开盘组合上实证确认。[原作者昼夜分解研究](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf) |
| M04 | 隔夜跳空压力 | `-ts_mean(open / lag(close, 1) - 1, 5)` | 5 | 检查隔夜跳空的后续回撤；不同于 M03，论文并不直接证明这个 5 日 A 股符号有效。[原作者研究](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf) |
| M05 | 低波动风险 | `-ts_std(pct_change(close, 1), 60)` | 60 | 低总波动代理；不是 beta、行业残差波动或 BAB 复制。[低风险经济机制](https://www.aqr.com/Insights/Research/Journal-Article/Betting-Against-Beta) |
| M06 | 避免彩票型上涨尾部 | `-ts_max(pct_change(close, 1), 20)` | 20 | 月内最大单日涨幅较小者优先；与单纯低波动需做相关性去重。[原作者 MAX 论文](https://pages.stern.nyu.edu/~rwhitela/papers/max%20jfe11.pdf) |
| M07 | 交易热度降温 | `-ts_mean(amount, 5) / ts_mean(amount, 60)` | 59 | 股票自身成交金额相对中期水平收缩；是待验证的注意力/交易压力代理，不是按流通股计算的 turnover ratio。 |
| M08 | 单位资金价格冲击 | `ts_mean(abs(pct_change(close, 1)) / amount, 20)` | 20 | Amihud 类非流动性指标，高值方向测试风险补偿；必须特别核对成交模型的容量边界。[Amihud 原文](https://www.sciencedirect.com/science/article/pii/S1386418101000246) |
| F01 | 盈利相对资产 | `net_profit / assets` | 0 | FY 净利/最新总资产；属于盈利质量代理，不是原论文的 gross profits/assets。[Novy-Marx 原文](https://www.nber.org/papers/w15940.pdf) |
| F02 | 经营现金创造 | `operating_cash_flow / assets` | 0 | FY 经营现金流/最新总资产；方向是现金盈利质量假设。 |
| F03 | 低应计、利润现金支持 | `(operating_cash_flow - net_profit) / assets` | 0 | 现金流相对利润的差额/最新总资产；不是已经对口径和同期性完整校准的 Sloan accrual。 |
| F04 | 收入利润率 | `net_profit / revenue` | 0 | FY 归母净利/总收入；收入为零产生缺失，负收入等异常值需查看覆盖和入选名单。 |
| F05 | 资产使用效率 | `revenue / assets` | 0 | FY 收入/最新资产；与 F01、F04 相关但经济角度不同，须看行业结构与收益相关性。 |
| F06 | 低财务杠杆 | `-liabilities / assets` | 0 | 同一余额表口径的低负债率；银行、保险和工业企业不可直接等同解释。 |
| F07 | 保守资产扩张 | `-pct_change(assets, 252)` | 252 | 低资产扩张强度代理。不是严格年度 INV，先检查财务完整覆盖与历史长度。[官方 Investment 定义](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/variable_definitions.html) |

当前算子为 `abs/log/sign/rank/lag/delta/pct_change/ts_mean/ts_sum/ts_std/ts_min/ts_max`；没有 `mean`、`std`、`corr`。滚动窗口要求完整有限值，`log` 的非正值产生缺失；公式总有效历史长度上限 252。[算子目录](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/alpha_builtins.py:321)、[编译器上限](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/alpha_language/language.py:29)

单因子在 `neutralization=none` 时，单调变换如 `rank(x)` 通常不改变 Top N 排序，不能当成新策略数量；它可能改变 Pearson IC，但保留 Rank IC 的秩。多因子组合可先用各自 `rank(...)` 统一量纲，再在保留单因子收益证据的基础上测试；行业去均值发生在公式输出之后，原值与 rank 后去均值不等价。[rank 语义](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/alpha_builtins.py:359)、[中性化位置](/Users/koltenluca/code-github/thesistrace/apps/core/src/thesistrace/research_kernel/alpha.py:254)

## 7. 用于持续搜索的证据要求

1. 每次试验保存公式、方向、Universe、研究起止日期、neutralization、holdings、rebalance interval、run ID、Result ID、数据版本。保留失败和负结果，最后同时报告总尝试数、超过门槛的配置数、去重后经济家族数。
2. 先在固定的较长共同区间比较，再看预先固定的最近区间和逐年结果。可采用可用历史至 2023 年探索、2024 年验证、2025–2026-09-09 后验留出观察；如果留出已被反复查看和调参，要如实改称验证集，不再声称独立样本外。日期选择是本次研究建议，不是系统内置门槛。
3. 将 >1.2 明确标记为对应区间的净收益 Sharpe。只在上涨年份超过 1.2 仍可作为区间发现记录，但不能升级为跨周期稳定策略。查看净/毛收益差、回撤、正 IC 日占比、5/20 日 Rank IC、拒单、现金比例和实际持仓。
4. 邻近持仓数、调仓周期与不同起点验证的是敏感性，不能将其每一个细小排列都算成独立 Alpha。基础数值核对包括 Alpha 取反、日 NAV 重算 Sharpe/回撤、选取若干日期重算收益/持仓；比较候选的日收益相关性和实际持仓重合，保留确有新增信息者。
5. 一个固定 Sharpe >1.2 阈值在持续增加试验时会产生选择偏差。Bailey 与 López de Prado 的 DSR 同时考虑试验数量、Sharpe 分布、样本长度、偏度和峰度；仅反复使用同一个 holdout 并不能消除这种偏差。若数据足以计算 DSR 或重采样结果，可作为单列证据；当前没有实算时不要宣称通过。[原作者 DSR 论文](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)

这里的实证目标仍是找到尽可能多的、在明确 TOP3000 契约下可重复得到净 Sharpe >1.2 的配置，并持续扩大经济机制覆盖；文献只提供候选和解释，不能替代 MCP 结果。

## 8. 本子任务验证记录

调用当前 `alpha_language.compile` 对上述 15 个公式做本地编译，15/15 通过；effective lookback 与表中一致，estimated work 介于 3 和 73。之后对正净资产门控和趋势门控额外做了小型合成 Alpha 输入计算，行式/列式结果相同；未运行合成策略回测，未创建 ResearchRun，未修改实现代码。上文真实反转结果来自主任务已经保存的 Result JSON，已在本子任务读取确认。

调用入口为 `mise exec -- uv run --no-sync --project apps/core python`，设置 `UV_CACHE_DIR=/private/tmp/thesistrace-research-contract-uv-cache`，再对表内 Formula 逐一执行 `alpha_language.compile(source)`。首次使用默认 uv cache 因沙箱不允许访问 `/Users/koltenluca/.cache/uv/sdists-v9/.git` 退出 2；改用任务专用临时缓存后编译命令退出 0。这项验证证明公式语法、字段与资源上限可接受，不证明数据覆盖、运行成功或研究收益。
