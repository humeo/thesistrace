# Round 13：原始文献与探索性因子的边界

核对日期：2026-09-10。本轮限定截至 **2026-09-09** 的 TOP3000 A 股日频数据、当日收盘后形成信号、次日开盘做多执行。下列文献提供待检验的机制，不构成论文复现、日内交易策略或收益承诺。

George–Hwang（2004）按月末价格除以前 12 个月最高价格排序，基准取上下 30% 等权多空组合，持有 6 个月；使用 1963–2001 年 CRSP 股票。描述性表不跳月，回归测试跳过形成后的一个月。因此，价格除以 **252 交易日最高价**只是近似改写；A 股股票池、日频更新、做多与开盘成交均需重新验证，不能继承原文收益结论。[作者原文，§I、表 I、脚注 3](https://www.bauer.uh.edu/tgeorge/papers/gh4-paper.pdf)

Gao 等（2019）研究 1996–2018 年 A 股高频数据，隔夜定义为前收盘至当日开盘，预测目标是**同日最后半小时**收益。它没有验证过去 20 日隔夜均值预测次日开盘后的完整持有收益。[作者存档正文，§2–4](https://mpra.ub.uni-muenchen.de/96784/1/MPRA_paper_96784.pdf) Cheema 等（2022）研究负日内反转的频率，发现中国样本未来一个月的隔夜与日内分量大致抵消，完整收益无显著预测关系；这也不能替代对收益均值信号的检验。[出版商摘要及引言](https://www.sciencedirect.com/science/article/pii/S0927538X22001044)

本轮 `Mean20(O_t/C_{t-1}-1)` 与 `Mean20(C_t/O_t-1)` 均是自行定义的探索性信号，不是上述文献的原始策略。应固定复权、缺失值与有效观察日口径；次日开盘执行也不会获得已在开盘前发生的那段隔夜收益。2023 年后续研究同样显示中国不同异常的日夜收益表现并不统一。[出版商摘要及引言](https://www.sciencedirect.com/science/article/pii/S0927538X23000732)

Amihud（2002）的个股 ILLIQ 是每日绝对收益率除以**美元成交额**后取年度平均；样本为 NYSE，解释后续月收益。本轮 `Mean(abs(r_daily)/amount_CNY)` 保留指标结构，但人民币单位、滚动窗口与交易策略均属改写。已读的定义及筛选段落未明确规定零成交额处理，不能声称“加 epsilon”或“填零”来自原文；除零无定义，无效日处理及有效日数须单独披露。[2002 年排版文，作者上传版 §2.1–2.2](https://www.researchgate.net/publication/222694235_Illiquidity_and_Stock_Returns_Cross-Section_and_Time-Series_Effects)

资金与最大回撤仅按本轮任务给定约束记录：用户本金 **100,000 CNY**、目标最大回撤 **20%**，平台原生回测本金 **10,000,000 CNY**。文献和该规模回测都未证明十万元账户的可执行性、Sharpe 或回撤达标，不能据此给出买入建议。

| 一手来源 | 本次实际读取范围 | 支持范围与限制 |
|---|---|---|
| [George–Hwang 2004：作者最终 PDF](https://www.bauer.uh.edu/tgeorge/papers/gh4-paper.pdf)；[出版记录](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2004.00695.x) | 正文 §I、表 I、脚注 3；出版商摘要 | 核实原始比例、样本、持有期及跳月区别；未证明 252 日 A 股版本。 |
| [Gao 等 2019：出版页](https://www.sciencedirect.com/science/article/pii/S1057521919302741)；[作者存档稿](https://mpra.ub.uni-muenchen.de/96784/) | 出版商摘要和章节预览；存档 PDF §2–4、附录变量表 | 核实隔夜预测同日末半小时；未验证 20 日平均收益因子。 |
| [Cheema 等 2022：出版页](https://www.sciencedirect.com/science/article/abs/pii/S0927538X22001044) | 摘要、引言及方法预览，未读完整正文 | 反转频率与未来收益分解；不能推广为所有日夜信号均无效。 |
| [Lin–Chang–Chou 2023：出版页](https://www.sciencedirect.com/science/article/pii/S0927538X23000732) | 摘要及引言，未读完整正文 | 不同异常的日夜表现混合；没有为本轮公式背书。 |
| [Amihud 2002：出版页](https://www.sciencedirect.com/science/article/pii/S1386418101000246)；[作者上传的最终排版文](https://www.researchgate.net/publication/222694235_Illiquidity_and_Stock_Returns_Cross-Section_and_Time-Series_Effects) | 出版商摘要；最终排版文 §2.1–2.2 | 年度均值、可用日数和 NYSE 边界；未核实原文明确的零成交额专门规则。 |

本笔记只核对公开文献并写入该文件，未读取或上传私有数据、提交 ResearchRun、修改产品代码。
