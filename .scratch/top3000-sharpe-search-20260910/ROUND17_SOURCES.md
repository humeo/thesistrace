# Round 17：三个尚未充分检验的方向与一手证据

核对日期：2026-09-10。对照了当前 [factors.csv](factors.csv)、[round7-plan.json](round7-plan.json) 和 [round13-plan.json](round13-plan.json)：已有现金应计、ROA、现金流/资产、净利润率、现金利润率、资产增长、收入增长、MAX、低波动、缩量、WQ 价量、日夜均值和年度高点。因此只保留以下三个**待测方向**；它们尚无本轮策略收益证据，也不等于三个独立风险来源。

| 顺序 | 限定假设 | 与已测方向的关系 | 固定候选公式 |
|---|---|---|---|
| 1 | 相比252交易日前当时可见信息，收入/资产比改善的股票，后续表现较好 | 经营效率变化；不是重复 ROA 水平，但仍与质量、收入及资产增长有关 | `rank(revenue / assets - lag(revenue / assets, 252) + 0 * log(assets) + 0 * log(lag(assets, 252)))` |
| 2 | 成交活动更稳定的股票，后续表现较好 | 检验相对离散程度，不是低成交额或5/60缩量；仍归流动性/交易活动家族 | `-rank(ts_std(amount, 60) / ts_mean(amount, 60))` |
| 3 | 日线估计价差较低的股票，在交易费用后更有优势 | 市场微观结构代理；不同于 Amihud 的绝对收益/成交额，但仍属流动性家族 | 下文 `-rank(Q + abs(Q))`；`Q` 必须展开，不能直接作为 DSL 字段提交 |

全部使用信号日收盘前已知值，下一交易日开盘才可执行。表中窗口是本次限定选择，不是文献给出的最优参数；公式尚未通过远端诊断，不能标记已运行。

Piotroski（2000）研究美国 Compustat/CRSP 的高账面市值比公司，样本1976–1996；资产周转率为销售收入/年初资产，考察与上年的变化。组合从财政年结束后的第五个月初开始，持有一年，并报告两年结果。这支持检验效率改善，但不是针对整个 A 股 TOP3000 的短期结论。[原始论文 §2.3.3、§3，Ivey 大学存档](https://www.ivey.uwo.ca/media/3775523/value_investing_the_use_of_historical_financial_statement_information.pdf)；[作者提交记录](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=249455)

这里的 `revenue/assets` 使用当时可见 FY 收入和资产字段，`lag(...,252)` 是交易日距离，**不是精确同期财报变化**；无法复现年初资产配对、高账面市值比筛选或完整九项 F-score。正资产过滤只处理分母经济含义；金融与非金融公司的资产周转率仍不直接可比。应先检查行业分布与财报有效覆盖，不能把报告切换造成的跳变解释为真实经营加速。若希望做最小分解对照，可使用 `rank(revenue / assets + 0 * lag(revenue / assets, 252) + 0 * log(assets) + 0 * log(lag(assets, 252)))`，保持相同历史可用性；该对照不算第四个家族。

Chordia、Subrahmanyam、Anshuman（2001）在美国 NYSE/AMEX 1966–1995 月度数据中研究成交活动及其变动与股票收益，报告成交额/换手率变异与收益的负向关系。[出版商摘要及数据预览](https://www.sciencedirect.com/science/article/pii/S0304405X00000805)；[作者机构记录](https://research.iimb.ac.in/fac_pubs/1268/) 但不能把该关系直接搬成60日人民币成交额规则：Flora、Gianstefani、Renò（2025，2024年12月在线发表）用美国1998–2018数据说明，方向随聚合窗口、观察频率而改变；分钟数据下转为正向，计成本的组合也未胜过单纯成交额排序。其原文确认旧 CSA 变量使用此前36个月的月成交额变异系数，本文日频60窗口并非复现。[开放原文 §1、§3、§5](https://onlinelibrary.wiley.com/doi/full/10.1111/jtsa.12802)

2025年 Lei–Zhou 的中国研究也观察到日成交量变异与未来收益的负向关系，但机构与大户持仓加速可令关系减弱或翻转。当前没有这些持仓字段，不能宣称已表达其条件信号；本次只读到出版商摘要、引言和预览，未核实完整样本起止、精确估计窗口及建仓日。[出版商原文预览](https://www.sciencedirect.com/science/article/pii/S0927538X25002434) 因此60日 `amount` 变异只是一项独立定义的无条件检验：使用人民币成交额而非换手率或股数成交量；均值为零时保留无效，不能加常数把停牌股票变成“稳定”。正反排序须同时留档，亦应与低成交额候选检查持仓/收益相关性。

Abdi–Ranaldo（2017）用收盘、最高、最低对数价估计有效买卖价差，主要验证美国 NYSE/AMEX/NASDAQ，2003年10月–2015年12月，并向1993年扩展。论文验证的是月度价差估计与 TAQ 的一致性，**不是选股收益异常**，没有可继承的赚钱方向或持有期。原式为 `2*sqrt(E[(c_t-eta_t)*(c_t-eta_(t+1))])`，`eta=(log(high)+log(low))/2`；负样本矩可在取均值后截为零。[作者机构原稿 §I.A–B、§III](https://ux-tauri.unisg.ch/RePEc/usg/sfwpfi/WPF-1604.pdf)；[正式出版页](https://academic.oup.com/rfs/article/30/12/4437/4047344)

为避免未来数据，收盘日 `t` 只估计到 `t-1` 收盘：

```text
Q = ts_mean(
  (lag(log(close), 1) - (lag(log(high), 1) + lag(log(low), 1)) / 2)
  * (lag(log(close), 1) - (log(high) + log(low)) / 2),
  20
)
```

完整可提交候选表达式：

```text
-rank(ts_mean((lag(log(close), 1) - (lag(log(high), 1) + lag(log(low), 1)) / 2) * (lag(log(close), 1) - (log(high) + log(low)) / 2), 20) + abs(ts_mean((lag(log(close), 1) - (lag(log(high), 1) + lag(log(low), 1)) / 2) * (lag(log(close), 1) - (log(high) + log(low)) / 2), 20)))
```

`Q+abs(Q)=2*max(Q,0)`，与非负平方价差同序，所以排名不需 DSL 缺少的平方根。这是滚动20日、先平均后截零的改写，不能声称复现逐两日截零再开方平均的另一版本。零值并列可能来自截断，不表示实际价差为零；还须检查复权高低价、零振幅、缺失和涨跌停影响。当前没有逐笔报价，不能用它替换账户实际滑点。建议保留高价差正向对照，检验可能的流动性补偿与交易成本之间的取舍。

下一步只需对以上固定公式做诊断和有限方向对照；先看完整覆盖与分组排序，再以同一持仓数/调仓频率做真实策略回测。因子 IC 不等于 Sharpe，排序反号和窗口变体不增加经济家族数。即使原生回测 Sharpe 达到1.2，也需另验10万元、20%回撤与最新日期，文献不能替代这些证据。本笔记只读已有研究与公开资料，唯一写入本文件；没有提交 MCP 任务、传输远端行情或修改产品。
