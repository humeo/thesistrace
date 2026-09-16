# 第 26 轮文献核对：均线距离与中期动量

核对日期：2026-09-10。本文是后续候选的来源记录，**不定义或修改已提交的 QS26 原始信号覆盖补全批次**。没有提交 MCP 研究、改产品代码或转移行情数据。

本次只保留 **1 个可供后续预声明的有限假设：连续均线比 MRAT(21,200) 越高，未来收益越高**。来源主要是美国个股研究；没有找到并核实近期 A 股同定义复现。它可以进入 A 股检验，但目前不是已达标策略，也不自动新增独立因子家族。12～7 个月动量暂不提交；2025 年短期均线距离按既有均线反转机制去重。

## 已有信号边界

核对时（QS27提交前）[factors.csv](factors.csv) 共 92 个已收集的不同公式文本。已核对 [原始 MA5 因子](results/run_9eaf564a47ee4bd89037.json)、[MA20 因子](results/run_660a77f4034644c48248.json) 和 [120 日跳过 20 日动量](results/run_ef50af0518ec4f6b90b0.json)，另有以 `sign(MA20/MA120-1)` 切换动量、低波动或低成交额的策略。未发现独立 `rank(MA21/MA200)` 或 12～7 个月累计收益公式。均线的连续幅度与既有二值切换不同，但仍须检查分数、选股和账户收益依赖性，不能仅靠文本不同计数。[已有连续性文献去重](ROUND22_SOURCES.md)

## 保留：连续 MRAT(21,200)，与论文 MAD 组合分开

Avramov、Kaplanski、Subrahmanyam，*Moving Average Distance as a Predictor of Equity Returns*，Review of Financial Economics 39(2)，127–145，2021；2020-09-18 先行发表。[出版记录及摘要](https://onlinelibrary.wiley.com/doi/abs/10.1002/rfe.1118)

本轮读到的是 [40 页原论文作者稿](https://assets.super.so/e46b77e7-ee08-445e-b43f-4ffd88ae0a0e/files/b120ea55-668f-405e-a6b1-1b281d72577a.pdf)，按 §1、§2.1–2.2、表 2–4 和附录 A 核对。该文件在第三方静态托管域名，封面作者及 SSRN 号为 3111334；[作者提交页](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3111334) 的索引记录为 40 页、2020-09-01 修订。**本轮未取得出版商 19 页排版全文，不能声称已逐页核对正式版本。**

作者稿的核心定义为 `MRAT = MA21 / MA200`，使用经拆股及分红调整的日价格；方向为正。美国样本为 1977-07～2018-12，NYSE／AMEX／NASDAQ 普通股，并有正账面权益、月末价格至少 5 美元及历史数据等筛选。表 2A 对连续 MRAT 的次月回归为正，t=4.92；2～6 月 t=3.60；7～12 月 t=1.51。表 3A 的 **MAD 门槛组合**次月多头平均收益 1.81%、空头 0.23%；这些不是 TOP3000 收益，也不是下述无门槛 TopN 的收益。[作者稿 §1、表 2A、表 3A](https://assets.super.so/e46b77e7-ee08-445e-b43f-4ffd88ae0a0e/files/b120ea55-668f-405e-a6b1-1b281d72577a.pdf)

论文 MAD 多头进一步要求：MRAT 属于最高十分组，且 `MRAT > 1 + σ`；空头属最低十分组，且 `MRAT < 1 - σ`。σ 是**当月横截面 MRAT 标准差**。组合按月形成、市值加权，主检验含次月与更长持有期；长持有期使用重叠组合。当前 DSL 没有横截面标准差，`ts_std` 不能替代；原生等权 TopN 和每 20 交易日调仓也不同。因此只检验有独立回归证据的连续 MRAT，不复刻或冒用 MAD 组合的收益。[作者稿 §1、§2.2、表 3–4](https://assets.super.so/e46b77e7-ee08-445e-b43f-4ffd88ae0a0e/files/b120ea55-668f-405e-a6b1-1b281d72577a.pdf)

可供下一轮冻结的单一表达式：

```text
rank(ts_mean(close, 21) / ts_mean(close, 200))
```

它需要 200 个完整价格观察，有效回看为 199 个交易日；信号日收盘后才可知，下一开盘成交，月末收盘到下一开盘这一段不能直接归入本地账户的可得收益。没有为了表现改成 20/120、50/200 或加事后阈值。本次只作代数与字段审阅，尚未代主任务进行原生编译诊断或实测。

建议的比较对象是 **同一 200 日完整历史覆盖下的既有 120 日跳过 20 日动量**，以及当前价格／MA200 的分解对照：

```text
rank(lag(close, 20) / lag(close, 120) - 1 + 0 * ts_mean(close, 200))
rank(close / ts_mean(close, 200))
```

二者只是比较项，不凭结果另开参数搜索。对正价格，`MA21/MA200 = (close/MA200)/(close/MA21)`，所以 MRAT 相对于价格／长均线，消除了当前价格对短均线偏离的一部分影响；这是代数解释，不能当成经济独立性证明。TOP3000、等权、费用、交易延迟、完整窗口覆盖及 10 万元可交易性均须按主任务研究计划单独验证。

## 两份“更新的均线论文”没有提供 A 股同策略证明

**2024 年国际研究的交易对象是国家指数。** Abudy、Kaplanski、Mugerman，*Market timing with moving average distance: International evidence*，研究 92 个市场，1980-06～2020-11（各市场起点依可用数据不同）；出版商可读方法片段明确主定义是 **30／300 自然日**均线比，并将指数值换算为美元。这是跨国市场配置／择时证据，不是 A 股个股 MRAT(21,200) 的横截面复现。完整组合阈值和成交时刻本轮未从全文核实，不移植摘要中的高 Sharpe。[出版商摘要、方法与稳健性片段](https://www.sciencedirect.com/science/article/pii/S1042443124001318)

另有 [UCLA 托管的 77 页较早作者稿](https://anderson-review.ucla.edu/wp-content/uploads/2021/03/Avramov-Kaplanski-Subra_2018_SSRN-id3111334.pdf)。其中表 12 虽含 China 行，但其描述是 **2001-01～2015-11 的市场指数择时**，包含按历史触发频率调整的敞口和 T-bill 头寸；这不能写成 A 股个股检验。该稿对 MAD 的命名、样本与阈值也不同，不与 40 页修订稿混合摘取收益。[较早稿，表 11–12、附录 E](https://anderson-review.ucla.edu/wp-content/uploads/2021/03/Avramov-Kaplanski-Subra_2018_SSRN-id3111334.pdf)

**2025 年 FAJ 的 SMAD 是短期价格反转。** Ko、Wang、Yang，*Short-Term Moving Average Distance and the Cross-Section of Stock Returns*，2025-08-06 在线发表。CFA 官方摘要定义为月末价格与过去 10 日均线的距离，方向为负；它不是两个不同长度均线之间的正向距离。当前已有 MA5／MA20 价格偏离反转，本轮不为 10 日窗口另计家族或发起择优。官方全文访问返回 403；样本、精确归一化、门槛和多头腿未完全核实，不从二手介绍补齐。[CFA 官方摘要](https://rpc.cfainstitute.org/research/financial-analysts-journal/2025/short-term-moving-average-distance)；[出版记录](https://www.tandfonline.com/doi/abs/10.1080/0015198X.2025.2533099)

## 暂不提交：12～7 个月回声动量

Novy-Marx（2012）的原始结论是，过去第 12～7 个月的累计收益比第 6～2 个月更能解释未来收益。出版商引言报告美国 1927-01～2010-12 大型股的市值加权赢家减输家组合，不能据此得出 A 股多头 Sharpe 或 10 万元收益。严格的月度窗口需自然月端点；将其写成 `lag(close,126)/lag(close,252)-1` 只能是交易日近似。[原始出版商摘要与引言](https://www.sciencedirect.com/science/article/pii/S0304405X11001152)

需要保留的反证及版本区别：

- Gong、Liu、Liu 的 [2011 年工作稿](https://iuj.repo.nii.ac.jp/record/460/files/EMS_2011_22.pdf) 摘要支持国际回声效应；但同作者 **2015 年正式发表**的 *Momentum is really short-term momentum* 认为第 12 个月季节性和第 2 个月反转会影响比较，排除这些月份后，美国及其余 26 个市场的中期／近期预测力差异不显著。不能只引用旧稿的正面摘要。[2015 年正式论文](https://www.sciencedirect.com/science/article/pii/S0378426614003252)
- Goyal、Wahal（2015），*Is Momentum an Echo?*，在 37 个非美国市场和地区组合中没有发现一致回声效应。本轮取得出版／作者页和摘要，未读到完整正式正文；不将结论扩大成每个 A 股年份均不存在动量。[期刊原摘要](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/is-momentum-an-echo/5E4B893AFD2F110B7347F8F483D28ED3)；[作者出版列表](https://swahal.github.io/publications/)
- Eom、Park（2026-03-31）提供可读正式全文：韩国 KOSPI／KOSDAQ，2000-07～2022-06，按自然月形成、持有 1 月，CMOM 使用原收益、IMOM 使用因子模型残差，方向结论不同；1990-07～2000-06 的样本不支持回声。尤其 §2.1 的入选规则包含**过去和未来时期的数据完整性**；不能把这种后验完整样本筛选复制为实盘 PIT 资格。它是韩国证据，不是中国复现。[官方全文 §2、§4.3](https://onlinelibrary.wiley.com/doi/10.1111/irfi.70072)
- Li、Liang、Huynh（2022）的中国 2000-01～2020-12 研究报告传统动量不显著，所提 CBMOM 还需要短期一致信念指标。它既不单独验证 12～7 个月，也不能只拿标题替已有动量加背书。本轮未核全 CB 的数学构造，不延伸新候选。[作者所在机构记录](https://eprints.soton.ac.uk/456671/)；[出版商引言](https://www.sciencedirect.com/science/article/abs/pii/S0927538X22000543)

本轮结论是研究优先级判断：暂不追加回声动量的交易日近似，不代表计算出它必然亏损。近期 A 股同定义证据未核得，且原生日频近似会混合月度季节性；继续换形成端点将扩大已有动量的参数尝试。

## 读取与可复现范围

实际核对了 40 页 MRAT 作者稿的定义、回归、组合和附录文本，以及 77 页旧稿的国际指数表格描述；正式 2026 年韩国论文正文可读。2024 国际论文、2012 原始动量、2015 争议论文、2022 中国论文和 2025 SMAD 使用出版方／作者机构可读摘要或索引片段，未冒称读到受阻全文。PDF 截图接口只返回了引用信息，本文的数值核对来自原 PDF 文本抽取，未声称完成可视截图验表。没有使用第三方量化博客的回测数值。

下一步若采用 MRAT，应先冻结候选与比较项、主检验期限和追加策略门槛，再调用原生公式诊断并做独立分数核对。文献报告提供候选依据；不会把相关系数、t 值或外国组合 Sharpe 计入本项目的达标策略数量。
