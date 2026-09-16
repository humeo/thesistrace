# TOP3000 策略与因子持续研究

更新：2026-09-10T02:57:25.771724+00:00

最新已固定数据日：2026-09-09；终值为该日开盘估值。研究同时覆盖2018年起的长区间、2023年起的对照，以及近3年、近1年和2026年至今。

已接受 108 次因子评估任务（92 个公式/区间/中性化案例，包含失败后恢复提交）、341 个策略回测。已采集 335 个策略结果，158 个不同公式/区间/中性化的因子结果（含策略关联因子）。策略 Sharpe > 1.2：14 个参数组合，5 个不同公式文本。其中2项为已证明观察路径重复的有效样本对照；排除后为12个区间/参数案例、4个公式文本，仍不代表独立经济家族。

Sharpe 为平台扣除交易费用后的净收益日序列年化值；阈值严格大于 1.2。各参数变体并非独立策略家族。全历史已用于探索，年度和近期切片只能检验时间稳定性，不能称作未接触的样本外。

QS4为个股评分切换；QS10/11/12/15的门控为排除自身后的市场宽度筛选，候选为空时按原调仓日退出；QS16按该宽度在低成交额与低波动之间切换评分。两者只用当时已知信息，次日开盘执行；均不是多个策略之间的动态组合分配，公式本身经过后验研究筛选。

当前用户约束：本金10万元，最大回撤目标20%。平台初始资金固定1000万元，本表属于线上大本金研究。独立10万元模型已用本地真实行情完成52个情景，数据止于2026-08-27；两类结果不能混为同一本金或日期，也不能线性缩放。参见 [10万元回放](CAPITAL_REPLAY.md)、[市场择时验证](MARKET_TIMING.md)、[两种评分切换](MARKET_SWITCH.md)、[调仓邻近检验](SWITCH_NEIGHBORS.md) 与 [产品问题记录](product-audit/REPORT.md)。

新增研究：[经营效率与交易活动稳定性](ROUND18_RESULTS.md)、[既有因子转实际策略](ROUND19_RESULTS.md)、[自回归与历史风险稳定性](ROUND20_RESULTS.md)。各轮保留预声明、负结果、匹配对照与未完成任务；短期通过不等于10万元账户已通过全部验证。

后续核查：[财务策略执行与资源限制](ROUND21_RESULTS.md)、[过线案例的日收益相关性](CANDIDATE_DEPENDENCE.md)、[新资料去重与排除理由](ROUND21_SOURCES.md)。收益相关性按相同起点和本金比较；没有将候选加权为新组合，也没有把失败任务计为策略负收益。

继续补齐：[九项因子的18个实际策略](ROUND22_RESULTS.md)。它们均未通过全年Sharpe与回撤条件，不再继续调参。另有一个[赢家条件内的连续性检验](ROUND23_RESULTS.md)，保留[原始资料](ROUND22_SOURCES.md)与[候选及匹配对照的预声明](round23-plan.json)。

后续执行：[经营效率的等价恢复](ROUND24_RESULTS.md)仍受资源限制；[日收益总偏度检验](ROUND25_RESULTS.md)在已有反彩票家族内比较三阶矩、MAX与低波动，不能只凭公式不同宣布新独立Alpha。

最新覆盖：[原始信号的一年期补测](ROUND26_RESULTS.md)按完整20项清单补齐16个旧定义；[21/200日均价比](ROUND27_RESULTS.md)与相同历史覆盖的动量、价格/长均价比较。[来源核对](ROUND26_SOURCES.md)保留论文版本、交易对象和可表达性边界。

[既有定义统一账户审计](ROUND28_RESULTS.md)：固定109个定义、218个H10/H20/R20年度案例；已完成208个，其中复用71个，执行问题未解决10个。全年Sharpe>1.2且回撤≤20%的固定案例0个。相关性与分位收益只用于分类；[方法审查](ROUND28_METHOD_REVIEW.md)与[独立清单核对](ROUND28_INVENTORY_REVIEW.md)保留选择和复用证据。只检验这组固定持仓/频率，不能推断所有参数无效，也不表示发现新家族或取得未见样本外证据。

调仓敏感性已出现反证：QS17四个预先固定邻居均未同时通过全年和季度；例如20只/9日季度Sharpe3.300，全年只有0.233。表中短期高值是已筛选历史区间的结果，不表示推荐10万元实盘。

## 按回测区间统计

|区间|已采集策略数|Sharpe > 1.2|最高 Sharpe|
|---|---:|---:|---:|
|2018-01-02 → 2026-09-09|34|0|0.508|
|2023-01-03 → 2026-09-09|9|0|0.574|
|2023-09-11 → 2026-09-09|12|1|1.209|
|2025-09-10 → 2026-09-09|262|7|1.572|
|2026-01-05 → 2026-09-09|3|0|0.073|
|2026-06-11 → 2026-09-09|15|6|3.300|

## 策略结果（各行日期不同，按 Sharpe 排序仅供检索）

|名称|区间起点|中性化|持仓/调仓|Sharpe|净年化|最大回撤|年化超额|Run|
|---|---|---|---|---:|---:|---:|---:|---|
|QS17 quarter market_switch_neighbor H20 R9|2026-06-11|none|20/9|3.300|78.9%|7.3%|113.9%|`run_b97c74f3cf7946eea447`|
|QS17 quarter market_switch_neighbor H10 R4|2026-06-11|none|10/4|2.932|65.1%|8.3%|97.4%|`run_88c7a5cd7d1a4ff3b57e`|
|QS17 quarter market_switch_neighbor H20 R11|2026-06-11|none|20/11|1.814|40.4%|7.5%|67.9%|`run_d898227ac09e41779c31`|
|QS16 quarter market_switch_amount_lowvol H10 R5|2026-06-11|none|10/5|1.640|35.0%|8.4%|61.4%|`run_9a68e61b294844ab9aa7`|
|QS16 quarter market_switch_amount_lowvol H20 R10|2026-06-11|none|20/10|1.574|28.8%|7.5%|54.0%|`run_7e94f022b5da43838f6f`|
|QS16 1y common_valid_amount_cash H20 R10|2025-09-10|none|20/10|1.572|18.3%|4.8%|14.5%|`run_1b505fb2143246efb3e6`|
|QS10 1y lowamount LOO_breadth20 H20 R10|2025-09-10|none|20/10|1.572|18.3%|4.8%|14.5%|`run_ec334d7e6ddd464f806e`|
|QS16 1y market_switch_amount_lowvol H10 R5|2025-09-10|none|10/5|1.525|30.7%|8.4%|26.6%|`run_c9871f3c547147bc80a1`|
|QS15 1y wq006_strong_breadth20 H20 R10|2025-09-10|none|20/10|1.480|21.7%|7.5%|17.8%|`run_8fedee28b1d84c1ebd4b`|
|QS16 1y common_valid_amount_cash H10 R5|2025-09-10|none|10/5|1.471|25.3%|6.7%|21.3%|`run_7297da0535ff4eacbb47`|
|QS10 1y lowamount LOO_breadth20 H10 R5|2025-09-10|none|10/5|1.471|25.3%|6.7%|21.3%|`run_e20c03fe0028468799de`|
|QS5 63s lowvol20 H100 R10|2026-06-11|none|100/10|1.401|24.5%|5.6%|48.9%|`run_96384289b08844dca9dc`|
|QS16 1y market_switch_amount_lowvol H20 R10|2025-09-10|none|20/10|1.387|21.4%|8.9%|17.5%|`run_fe6c5b6b5f2d4a2395da`|
|QS16 3y market_switch_amount_lowvol H20 R10|2023-09-11|none|20/10|1.209|29.3%|16.5%|20.7%|`run_e8afbf2f89d24e2e8af8`|
|QS5 63s lowvol20 H50 R20|2026-06-11|none|50/20|1.186|18.8%|6.8%|42.1%|`run_7b70101310aa41d5a48f`|
|QS5 63s lowvol20 H50 R5|2026-06-11|none|50/5|1.180|18.6%|8.4%|41.8%|`run_cc1e153b10844fcc8cd3`|
|QS5 63s lowvol20 H50 R10|2026-06-11|none|50/10|1.179|19.2%|7.1%|42.6%|`run_615df5226f5d4a8b9c6c`|
|QS5 63s lowvol20 H100 R20|2026-06-11|none|100/20|1.175|19.6%|5.5%|43.0%|`run_a395688cc50c4fd58dad`|
|QS17 quarter market_switch_neighbor H10 R6|2026-06-11|none|10/6|1.139|25.2%|9.1%|49.7%|`run_e9d80d1aa8dd41f4abf7`|
|QS11 1y lowamount LOO_breadth120 H10 R5|2025-09-10|none|10/5|1.139|23.0%|10.6%|19.1%|`run_cb7c1f55f0a448ac9654`|
|QS10 3y lowamount LOO_breadth20 H20 R10|2023-09-11|none|20/10|1.107|23.8%|16.3%|15.6%|`run_31298510aab342a2a630`|
|QS17 1y market_switch_neighbor H10 R4|2025-09-10|none|10/4|1.105|20.1%|12.4%|16.3%|`run_62c3fb71dbad436d98cd`|
|QS5 63s lowvol20 H100 R5|2026-06-11|none|100/5|1.091|17.3%|6.9%|40.3%|`run_c0cf9f6fdfa94852b03b`|
|QS28 1y d087 wq006_percentile90 H10 R20|2025-09-10|none|10/20|1.052|28.6%|19.4%|24.5%|`run_4fa825f36c2c4dd38254`|
|QS28 1y d085 wq006_weak_breadth20 H20 R20|2025-09-10|none|20/20|1.035|16.7%|8.5%|13.0%|`run_8ed2f120b90c4e7a86c0`|
|QS11 1y lowamount LOO_breadth60 H10 R5|2025-09-10|none|10/5|1.017|17.6%|11.2%|13.9%|`run_1c576dcdba8042ed847b`|
|QS10 quarter lowamount LOO_breadth20 H10 R5|2026-06-11|none|10/5|0.987|12.4%|3.8%|34.4%|`run_fb797c3c5d3a4903a2d5`|
|QS22 1y wq002_none H10 R20|2025-09-10|none|10/20|0.987|27.2%|29.5%|23.1%|`run_0b392f7f468c4823b6b0`|
|QS19 1y downside20_none H10 R20|2025-09-10|none|10/20|0.971|13.1%|10.0%|9.5%|`run_285c38e87c074b839ec3`|
|QS8 1y lowamount20 industry H20 R10|2025-09-10|industry|20/10|0.950|25.9%|20.0%|21.9%|`run_1b900ded767b4705b61e`|
|QS28 1y d087 wq006_percentile90 H20 R20|2025-09-10|none|20/20|0.919|22.1%|18.4%|18.2%|`run_ee66760001be4d3994bc`|
|QS13 1y wq006 H20 R10|2025-09-10|none|20/10|0.872|18.5%|20.0%|14.7%|`run_3d8373b9b84642818bac`|
|QS8 1y downside20 industry H10 R10|2025-09-10|industry|10/10|0.870|17.2%|12.2%|13.4%|`run_a5d9a9582f6c44f6b39a`|
|QS8 1y lowamount20 industry H10 R10|2025-09-10|industry|10/10|0.830|22.4%|23.9%|18.5%|`run_66dd3706b1404409a8a2`|
|QS28 1y d039 wq006 H20 R20|2025-09-10|none|20/20|0.808|16.4%|20.0%|12.7%|`run_d98cee7926a6464c8e46`|
|QS8 1y lowamount20 industry H10 R20|2025-09-10|industry|10/20|0.768|20.5%|25.4%|16.6%|`run_bb819378d121406caf5b`|
|QS6 prescreen lowamount20 H10 R10|2025-09-10|none|10/10|0.759|15.9%|12.3%|12.1%|`run_f87508c0fc204af1b381`|
|QS11 1y lowamount LOO_breadth120 H20 R10|2025-09-10|none|20/10|0.700|10.4%|10.2%|6.8%|`run_4ff6f9b10cd04d349a26`|
|QS10 quarter lowamount LOO_breadth20 H20 R10|2026-06-11|none|20/10|0.691|4.7%|3.5%|25.2%|`run_2e80590093ee43afb71f`|
|QS11 1y lowamount LOO_breadth60 H20 R10|2025-09-10|none|20/10|0.687|7.9%|5.1%|4.5%|`run_d892f7bf324b492fae03`|
|QS28 1y d088 market_switch_amount_lowvol H20 R20|2025-09-10|none|20/20|0.685|9.9%|14.8%|6.4%|`run_95532804370941fd8ea7`|
|QS28 1y d028 lowamount20_trend120 H20 R20|2025-09-10|none|20/20|0.650|13.5%|24.8%|9.8%|`run_7c16a70f1ec243cfbc45`|
|QS28 1y d031 lowamount20_lowvol20 H20 R20|2025-09-10|none|20/20|0.643|9.1%|16.6%|5.6%|`run_49b64e88ba684d93a625`|
|QS10 3y lowamount LOO_breadth20 H10 R5|2023-09-11|none|10/5|0.643|12.7%|16.4%|5.3%|`run_779d11c1a18f4eb4bff7`|
|QS16 3y market_switch_amount_lowvol H10 R5|2023-09-11|none|10/5|0.640|13.8%|25.1%|6.3%|`run_f7f73103c33f4aa29754`|
|QS28 1y d036 switch_trend_amount_lowvol H10 R20|2025-09-10|none|10/20|0.598|8.4%|8.9%|4.9%|`run_761410df5edd4984868a`|
|QS22 1y wq003_none H20 R20|2025-09-10|none|20/20|0.595|11.6%|17.6%|8.0%|`run_31aa367b51854a9fbd52`|
|QS17 1y market_switch_neighbor H10 R6|2025-09-10|none|10/6|0.588|8.4%|12.1%|4.9%|`run_ea0515b235c14df7bd26`|
|QS6 prescreen lowamount20 H5 R10|2025-09-10|none|5/10|0.584|12.5%|15.7%|8.9%|`run_578813e076cb494eacac`|
|QS3 2023 lowamount20 H50 R10|2023-01-03|none|50/10|0.574|12.7%|36.9%|7.6%|`run_13b22f39cf314db3b381`|
|QS28 1y d096 ar1_increment60 H10 R20|2025-09-10|none|10/20|0.574|17.0%|28.0%|13.3%|`run_d4735fbfd2ba4edfa075`|
|QS22 1y wq003_none H10 R20|2025-09-10|none|10/20|0.556|11.5%|22.4%|7.9%|`run_1fef61cdcb8b47d58aae`|
|QS28 1y d066 volume_dry_lowvol industry H20 R20|2025-09-10|industry|20/20|0.553|10.1%|23.8%|6.5%|`run_51c5dd5deeca4fdebbf7`|
|QS11 1y lowamount coverage120_control H10 R5|2025-09-10|none|10/5|0.552|11.1%|22.2%|7.6%|`run_0f883258866747929499`|
|QS28 1y d076 intraday_mom20 H10 R20|2025-09-10|none|10/20|0.547|16.2%|42.2%|12.5%|`run_5e28135b464b40d0a617`|
|QS20 1y historical_vol_instability20_60_low H20 R20|2025-09-10|none|20/20|0.538|11.7%|27.8%|8.2%|`run_9746504e8af8470380a1`|
|QS6 prescreen lowamount20 H20 R10|2025-09-10|none|20/10|0.528|9.3%|14.3%|5.8%|`run_3d41733d71b84ab383e8`|
|QS15 3y wq006_strong_breadth20 H20 R10|2023-09-11|none|20/10|0.525|9.3%|23.4%|2.1%|`run_803cf573db1041b8a73a`|
|QS15 1y wq006_strong_breadth20 H10 R10|2025-09-10|none|10/10|0.520|7.5%|15.3%|4.0%|`run_2ccb38495fec4ce894c2`|
|QS1 lowamount20 H100 R20|2018-01-02|none|100/20|0.508|10.0%|35.7%|8.6%|`run_b1c43159f6304d2c92dc`|
|QS18 1y amount_cv60_low H20 R20|2025-09-10|none|20/20|0.507|8.1%|19.6%|4.6%|`run_2cdc9b788a394081894a`|
|QS12 1y lowvol LOO_weak_breadth20 H10 R5|2025-09-10|none|10/5|0.499|4.3%|10.3%|1.0%|`run_5a89769b227b41259db3`|
|QS28 1y d089 common_valid_amount_cash H20 R20|2025-09-10|none|20/20|0.490|5.5%|10.0%|2.1%|`run_1b9a96a9c42b4d19803c`|
|QS28 1y d069 lowamount LOO_breadth20 H20 R20|2025-09-10|none|20/20|0.490|5.5%|10.0%|2.1%|`run_6e0869929d0741cc8f4b`|
|QS28 1y d104 total_daily_skew20_low H10 R20|2025-09-10|none|10/20|0.490|9.0%|24.2%|5.5%|`run_44a49ef4a6af4836b774`|
|QS28 1y d074 lowvol LOO_weak_breadth20 H20 R20|2025-09-10|none|20/20|0.487|4.2%|11.3%|0.9%|`run_1f0edcbe8731453a8041`|
|QS3 2023 lowamount20 H100 R10|2023-01-03|none|100/10|0.485|9.9%|37.9%|5.0%|`run_0b63eca4246c43029cd5`|
|QS6 prescreen lowvol20 H5 R10|2025-09-10|none|5/10|0.482|5.2%|11.6%|1.8%|`run_072d4799de174a6dbb02`|
|QS8 1y lowamount20 industry H20 R20|2025-09-10|industry|20/20|0.473|10.0%|26.0%|6.5%|`run_107cb89d326344178425`|
|QS15 1y overnight20_percentile90 H20 R20|2025-09-10|none|20/20|0.469|10.5%|27.5%|6.9%|`run_3f53d9cb02b6411b9540`|
|QS6 prescreen lowvol20 H10 R10|2025-09-10|none|10/10|0.456|4.5%|9.2%|1.2%|`run_f5fc4222fa4c4b26af34`|
|QS11 3y lowamount LOO_breadth60 H10 R5|2023-09-11|none|10/5|0.455|8.5%|20.3%|1.3%|`run_d84bd0cd45594db4a355`|
|QS3 2023 lowamount20 H100 R20|2023-01-03|none|100/20|0.452|9.0%|36.4%|4.0%|`run_696f8729882e4ae0a988`|
|QS8 1y downside20 industry H20 R10|2025-09-10|industry|20/10|0.451|6.9%|9.0%|3.5%|`run_c758eb8a3033432db44d`|
|QS3 2023 lowamount20 H50 R5|2023-01-03|none|50/5|0.451|8.9%|39.9%|4.0%|`run_baad76a4807e48b1a90c`|
|QS4 1y lowamount20 H100 R20|2025-09-10|none|100/20|0.448|7.3%|20.7%|3.8%|`run_6c31d43b1d674ad8bce8`|
|QS6 prescreen lowamount20 H5 R20|2025-09-10|none|5/20|0.447|8.8%|15.9%|5.3%|`run_525ff1f46178404fa0c3`|
|QS11 3y lowamount LOO_breadth120 H20 R10|2023-09-11|none|20/10|0.446|6.7%|20.4%|-0.4%|`run_ced92f63f8004284be15`|
|QS28 1y d072 lowamount LOO_breadth120 H10 R20|2025-09-10|none|10/20|0.444|7.1%|12.6%|3.7%|`run_c8122e4b7e914572a01f`|
|QS28 1y d076 intraday_mom20 H20 R20|2025-09-10|none|20/20|0.440|10.0%|42.1%|6.5%|`run_6a38c542f88c4cb1a327`|
|QS6 prescreen lowamount20 H20 R20|2025-09-10|none|20/20|0.435|7.3%|22.5%|3.9%|`run_3690e87a47484b0fb3b4`|
|QS28 1y d072 lowamount LOO_breadth120 H20 R20|2025-09-10|none|20/20|0.431|6.4%|14.0%|3.0%|`run_63f6ef00c5b84c5293e1`|
|QS6 prescreen lowvol20 H5 R20|2025-09-10|none|5/20|0.428|5.1%|11.1%|1.7%|`run_9cc87f57e60245479ef1`|
|QS20 1y lowvol20_instability_coverage H10 R20|2025-09-10|none|10/20|0.426|4.4%|11.6%|1.0%|`run_12ba53e001414fe0b5ff`|
|QS2 lowamount20_cfoa H100 R20|2018-01-02|none|100/20|0.422|7.4%|34.2%|6.0%|`run_da470cd72ecc40378da4`|
|QS3 2023 lowamount20 H100 R5|2023-01-03|none|100/5|0.419|8.0%|38.6%|3.1%|`run_51337ab0305342c18686`|
|QS3 2023 lowamount20 H50 R20|2023-01-03|none|50/20|0.415|7.9%|40.0%|3.0%|`run_afa8efc5ef7a4b31a7bf`|
|QS28 1y d025 ma5_volume_dry H10 R20|2025-09-10|none|10/20|0.412|8.7%|34.8%|5.2%|`run_2dc4db6910e74c0cb7e3`|
|QS28 1y d085 wq006_weak_breadth20 H10 R20|2025-09-10|none|10/20|0.403|5.9%|16.0%|2.5%|`run_b7339f39af8046599828`|
|QS3 2023 lowamount20 H20 R10|2023-01-03|none|20/10|0.402|7.6%|37.9%|2.8%|`run_959e544fada547c3ad82`|
|QS2 lowamount20_trend120 H100 R20|2018-01-02|none|100/20|0.392|6.7%|33.7%|5.3%|`run_b6bef4ef096645d6ba23`|
|QS2 lowamount20_lowvol20 H100 R20|2018-01-02|none|100/20|0.391|5.9%|38.2%|4.5%|`run_262c855a7f8641c3b19c`|
|QS11 3y lowamount LOO_breadth120 H10 R5|2023-09-11|none|10/5|0.373|5.6%|19.8%|-1.4%|`run_7b9c5babd44a4fa3b33d`|
|QS2 intraday5_lowamount20 H100 R5|2018-01-02|none|100/5|0.371|6.7%|45.2%|5.2%|`run_3a3ab2ce0ad145d4a2ab`|
|QS28 1y d022 rev5_cfoa H10 R20|2025-09-10|none|10/20|0.370|6.8%|32.5%|3.4%|`run_0c4bb5652639484d8909`|
|QS6 prescreen lowvol20 H10 R20|2025-09-10|none|10/20|0.363|3.6%|10.6%|0.3%|`run_1a6ab615115040618a0a`|
|QS28 1y d106 lowvol20_skew_coverage H10 R20|2025-09-10|none|10/20|0.363|3.6%|10.6%|0.3%|`run_8249230e8a2c41efaada`|
|QS28 1y d074 lowvol LOO_weak_breadth20 H10 R20|2025-09-10|none|10/20|0.363|2.9%|10.5%|-0.3%|`run_bf75e6b2470e4e149808`|
|QS8 1y downside20 industry H20 R20|2025-09-10|industry|20/20|0.359|5.0%|11.5%|1.6%|`run_f7ef0da8484846c78805`|
|QS11 1y lowamount coverage120_control H20 R10|2025-09-10|none|20/10|0.358|5.4%|15.3%|2.0%|`run_448e1eb81a1442829b24`|
|QS2 lowvol20_trend120 H100 R20|2018-01-02|none|100/20|0.356|4.8%|32.1%|3.4%|`run_3ea899aa214746f8bc00`|
|QS22 1y lowmax20_industry H10 R20|2025-09-10|industry|10/20|0.353|5.2%|14.9%|1.8%|`run_63393a4c245040f4bfd2`|
|QS4 3y switch_trend_amount_lowvol H100 R20|2023-09-11|none|100/20|0.347|5.1%|20.0%|-1.8%|`run_5af32e2d6ea94dbc9144`|
|QS2 lowamount20_roa H100 R20|2018-01-02|none|100/20|0.341|5.5%|37.6%|4.1%|`run_1be298753c224f899678`|
|QS14 1y overnight_mom20_industry H20 R20|2025-09-10|industry|20/20|0.331|5.6%|37.8%|2.2%|`run_13708ce23eba4bed9a0c`|
|QS28 1y d029 lowvol20_trend120 H10 R20|2025-09-10|none|10/20|0.325|3.3%|15.8%|-0.0%|`run_15d4919b49364baca993`|
|QS28 1y d015 volume_dry 5比60日缩量 H10 R20|2025-09-10|none|10/20|0.317|5.1%|33.3%|1.8%|`run_34b3b6f8357f456b9fcf`|
|QS3 momentum_lowvol60 H100 R20|2018-01-02|none|100/20|0.309|4.0%|35.5%|2.6%|`run_6d37a8d1620c4f5da411`|
|QS28 1y d088 market_switch_amount_lowvol H10 R20|2025-09-10|none|10/20|0.307|3.9%|12.9%|0.6%|`run_47ea70c439c04218a2be`|
|QS22 1y volume_dry_lowvol_none H10 R20|2025-09-10|none|10/20|0.301|4.4%|29.2%|1.0%|`run_7f7cb4b361c24e72836d`|
|QS12 1y lowvol LOO_weak_breadth20 H20 R10|2025-09-10|none|20/10|0.299|2.5%|11.3%|-0.8%|`run_62bfbde2b2f64f4baf92`|
|QS3 2023 lowamount20 H20 R5|2023-01-03|none|20/5|0.296|4.5%|37.7%|-0.2%|`run_f08905cb0d034ad585ad`|
|QS3 2023 lowamount20 H20 R20|2023-01-03|none|20/20|0.290|4.3%|46.8%|-0.4%|`run_a83493cf3900443bae6a`|
|QS22 1y wq002_none H20 R20|2025-09-10|none|20/20|0.289|4.2%|27.6%|0.9%|`run_521b1c390bc9431fbbef`|
|QS20 1y historical_vol_instability20_60_low H10 R20|2025-09-10|none|10/20|0.288|4.3%|32.4%|0.9%|`run_ca1d2fa5162d4eb8bdd1`|
|QS28 1y d028 lowamount20_trend120 H10 R20|2025-09-10|none|10/20|0.288|4.3%|25.0%|0.9%|`run_91d77c2498474aa9ab6c`|
|QS28 1y d024 lowamount20_cfoa H20 R20|2025-09-10|none|20/20|0.282|3.5%|13.5%|0.2%|`run_bb2d128b344348a9abef`|
|QS28 1y d079 amihud20 H10 R20|2025-09-10|none|10/20|0.282|3.8%|33.1%|0.5%|`run_1c69e0e8caad492598f6`|
|QS28 1y d013 illiquidity20 20日非流动性 H10 R20|2025-09-10|none|10/20|0.282|3.8%|33.1%|0.5%|`run_3edc7b50d57d4330aefd`|
|QS28 1y d073 lowamount coverage120_control H20 R20|2025-09-10|none|20/20|0.274|3.7%|24.2%|0.3%|`run_1b92377ef53a47579fac`|
|QS28 1y d026 lowamount20_roa H10 R20|2025-09-10|none|10/20|0.256|3.2%|19.2%|-0.1%|`run_e8864eb620b14175b480`|
|QS28 1y d036 switch_trend_amount_lowvol H20 R20|2025-09-10|none|20/20|0.252|2.4%|12.2%|-0.8%|`run_d79195a0bd25465fa125`|
|QS11 3y lowamount LOO_breadth60 H20 R10|2023-09-11|none|20/10|0.251|3.3%|24.2%|-3.5%|`run_3c61e672345d4fc2b9ff`|
|QS13 1y wq006 H10 R10|2025-09-10|none|10/10|0.245|3.1%|24.9%|-0.2%|`run_9aab8652d8a14142b06d`|
|QS15 1y neighbor wq006_strong_breadth20 H20 R5|2025-09-10|none|20/5|0.244|2.7%|10.8%|-0.6%|`run_01769e720e4d4c408b79`|
|QS17 1y market_switch_neighbor H20 R9|2025-09-10|none|20/9|0.233|2.4%|18.5%|-0.8%|`run_fa8eb66281dc43afb7f3`|
|QS15 1y neighbor wq006_strong_breadth20 H20 R20|2025-09-10|none|20/20|0.230|2.3%|13.2%|-1.0%|`run_02a73e3bcfb14c34a5c6`|
|QS22 1y volume_dry_lowvol_none H20 R20|2025-09-10|none|20/20|0.228|2.6%|25.5%|-0.7%|`run_1680945deddc4abc85da`|
|QS1 lowvol20 H100 R20|2018-01-02|none|100/20|0.228|2.4%|35.0%|1.0%|`run_1d504800188b46b191f0`|
|QS28 1y d033 momentum_risk120 H10 R20|2025-09-10|none|10/20|0.225|-1.7%|49.0%|-4.9%|`run_376f8d0e4a8d4dcda86d`|
|QS17 1y market_switch_neighbor H20 R11|2025-09-10|none|20/11|0.223|2.2%|12.4%|-1.1%|`run_a7d5fda4634c4584b535`|
|QS19 1y downside20_none H20 R20|2025-09-10|none|20/20|0.208|1.7%|13.9%|-1.5%|`run_6f3a11540849479185aa`|
|QS28 1y d073 lowamount coverage120_control H10 R20|2025-09-10|none|10/20|0.206|2.1%|17.0%|-1.1%|`run_3d1cb390f66a44179d81`|
|QS4 3y switch_vol_lowvol_moderate H100 R20|2023-09-11|none|100/20|0.206|1.9%|34.1%|-4.8%|`run_7a4f01927a964fb583e4`|
|QS28 1y d021 rev5_lowvol20 H20 R20|2025-09-10|none|20/20|0.203|2.0%|22.8%|-1.2%|`run_ce045e6dabde468297d9`|
|QS28 1y d071 lowamount LOO_breadth60 H10 R20|2025-09-10|none|10/20|0.202|1.9%|8.2%|-1.3%|`run_e8fcdc1e921e4e6e9986`|
|QS28 1y d035 switch_trend_mom_lowvol H10 R20|2025-09-10|none|10/20|0.194|1.6%|20.5%|-1.6%|`run_34246eb3c6364b2aa67d`|
|QS28 1y d104 total_daily_skew20_low H20 R20|2025-09-10|none|20/20|0.192|1.9%|19.8%|-1.4%|`run_4653447e1cb9491fad3d`|
|QS28 1y d021 rev5_lowvol20 H10 R20|2025-09-10|none|10/20|0.190|1.8%|22.4%|-1.4%|`run_2e8dd6e931f949b48984`|
|QS26 1y rev20 H20 R20|2025-09-10|none|20/20|0.184|0.3%|33.4%|-2.9%|`run_47cdfd9fa3b147ff8ae7`|
|QS26 1y intraday5 H10 R20|2025-09-10|none|10/20|0.170|-1.1%|40.6%|-4.3%|`run_b22b9be9d274427ca2d7`|
|QS22 1y lowmax20_industry H20 R20|2025-09-10|industry|20/20|0.167|1.4%|17.1%|-1.8%|`run_d6b632ee5ee143269c38`|
|QS1 cfoa H100 R20|2018-01-02|none|100/20|0.162|1.0%|46.7%|-0.3%|`run_6dedba947b27419992d7`|
|QS28 1y d066 volume_dry_lowvol industry H10 R20|2025-09-10|industry|10/20|0.161|1.0%|33.3%|-2.2%|`run_c864f5fc87114abba5fb`|
|QS13 1y overnight_mom20 H10 R20|2025-09-10|none|10/20|0.152|-4.7%|37.7%|-7.8%|`run_64cbaef8c4124373a82c`|
|QS28 1y d029 lowvol20_trend120 H20 R20|2025-09-10|none|20/20|0.150|1.1%|13.3%|-2.1%|`run_679ece79cd3a440fb1a4`|
|QS28 1y d071 lowamount LOO_breadth60 H20 R20|2025-09-10|none|20/20|0.148|1.1%|10.2%|-2.1%|`run_b7c13b5faf204513807a`|
|QS28 1y d024 lowamount20_cfoa H10 R20|2025-09-10|none|10/20|0.144|0.9%|16.6%|-2.3%|`run_e87086d4b4614ba593c2`|
|QS2 moderate_rev5 H100 R5|2018-01-02|none|100/5|0.141|0.2%|48.1%|-1.1%|`run_f8b6e49fe8034ed4a1e8`|
|QS6 prescreen lowamount20 H10 R20|2025-09-10|none|10/20|0.138|0.5%|17.2%|-2.7%|`run_434dcae08cc0483284ed`|
|QS28 1y d069 lowamount LOO_breadth20 H10 R20|2025-09-10|none|10/20|0.137|0.9%|10.4%|-2.3%|`run_4e1fc19bf405468da283`|
|QS28 1y d089 common_valid_amount_cash H10 R20|2025-09-10|none|10/20|0.137|0.9%|10.4%|-2.3%|`run_9fd7fd8f7d2a45c29e5f`|
|QS4 1y switch_trend_amount_lowvol H100 R20|2025-09-10|none|100/20|0.130|0.9%|15.8%|-2.4%|`run_f11d10a6b3ca413883f5`|
|QS28 1y d032 momentum_lowvol60 H10 R20|2025-09-10|none|10/20|0.126|0.7%|14.0%|-2.6%|`run_a43b2f7f9aad4e4d8aca`|
|QS28 1y d100 FIP winner continuity H20 R20|2025-09-10|none|20/20|0.121|-3.2%|42.7%|-6.3%|`run_e58d282438cd45278471`|
|QS26 1y momentum120_skip20 H10 R20|2025-09-10|none|10/20|0.114|-6.1%|43.1%|-9.2%|`run_adcd6e7d9237470b90de`|
|QS4 3y switch_trend_mom_lowvol H100 R20|2023-09-11|none|100/20|0.107|-1.0%|28.1%|-7.5%|`run_e96ea05294274d598dae`|
|QS28 1y d033 momentum_risk120 H20 R20|2025-09-10|none|20/20|0.105|-6.7%|46.9%|-9.7%|`run_d6c22dc0a3094bde908d`|
|QS26 1y close_location5 H20 R20|2025-09-10|none|20/20|0.104|-0.9%|32.4%|-4.1%|`run_d98414ebc0ac401298c1`|
|QS28 1y d070 lowvol LOO_breadth20 H10 R20|2025-09-10|none|10/20|0.103|0.5%|5.5%|-2.7%|`run_62687a0c87f4433788ba`|
|QS28 1y d077 low_overnight_risk20 H20 R20|2025-09-10|none|20/20|0.100|0.5%|13.3%|-2.7%|`run_af2b9e8dcb4e420f8118`|
|QS28 1y d022 rev5_cfoa H20 R20|2025-09-10|none|20/20|0.098|-1.1%|28.8%|-4.3%|`run_243e0ac32964439a81e7`|
|QS18 1y amount_cv60_low H10 R20|2025-09-10|none|10/20|0.084|-0.4%|25.6%|-3.6%|`run_3cbd7537dd7a4a2b999d`|
|QS28 1y d034 roa_lowdebt H10 R20|2025-09-10|none|10/20|0.077|-1.2%|19.7%|-4.4%|`run_96cb42e5755544198730`|
|QS4 ytd switch_trend_amount_lowvol H100 R20|2026-01-05|none|100/20|0.073|0.1%|12.3%|4.8%|`run_95d75a49a8af4621aa66`|
|QS28 1y d015 volume_dry 5比60日缩量 H20 R20|2025-09-10|none|20/20|0.072|-1.6%|32.7%|-4.7%|`run_3096426eab8a4a67af7a`|
|QS28 1y d109 price_to_ma200 H10 R20|2025-09-10|none|10/20|0.070|-12.7%|50.6%|-15.5%|`run_2fb6708c379049e2ba4d`|
|QS2 cfoa_trend120 H100 R20|2018-01-02|none|100/20|0.057|-1.5%|51.0%|-2.8%|`run_4e180e4dd9374df08fe9`|
|QS3 roa_lowdebt H100 R20|2018-01-02|none|100/20|0.055|-2.0%|56.4%|-3.3%|`run_04ce69d6e02744ffad93`|
|QS28 1y d105 lowmax20_skew_coverage H20 R20|2025-09-10|none|20/20|0.053|-0.1%|15.0%|-3.3%|`run_3bba94b76c944560b325`|
|QS19 1y lowmax20_none H20 R20|2025-09-10|none|20/20|0.053|-0.1%|15.0%|-3.3%|`run_d164a8db96914d78b5e8`|
|QS28 1y d025 ma5_volume_dry H20 R20|2025-09-10|none|20/20|0.046|-3.2%|37.3%|-6.3%|`run_0019f48d4a6446c99a13`|
|QS4 1y switch_vol_lowvol_moderate H100 R20|2025-09-10|none|100/20|0.043|-1.1%|24.8%|-4.3%|`run_c299d60f2e5f454bbfe3`|
|QS28 1y d023 intraday5_lowamount20 H20 R20|2025-09-10|none|20/20|0.038|-2.3%|33.2%|-5.4%|`run_421c73b86a604c7abf53`|
|QS28 1y d078 clv_volume20 H10 R20|2025-09-10|none|10/20|0.025|-7.3%|40.8%|-10.2%|`run_32e3a504893246b1b7ed`|
|QS20 1y lowvol20_instability_coverage H20 R20|2025-09-10|none|20/20|0.015|-0.5%|14.2%|-3.6%|`run_966cdd3adfbf4876a99a`|
|QS28 1y d013 illiquidity20 20日非流动性 H20 R20|2025-09-10|none|20/20|0.012|-3.9%|30.4%|-6.9%|`run_506f5dc808804c9582eb`|
|QS28 1y d079 amihud20 H20 R20|2025-09-10|none|20/20|0.012|-3.9%|30.4%|-6.9%|`run_692e5affac7c42e782c7`|
|QS8 1y downside20 industry H10 R20|2025-09-10|industry|10/20|-0.001|-2.2%|14.6%|-5.4%|`run_0eaf60be30514ab89724`|
|QS6 prescreen lowvol20 H20 R20|2025-09-10|none|20/20|-0.004|-0.7%|14.4%|-3.8%|`run_ab196ccc0e1d41a8815b`|
|QS28 1y d106 lowvol20_skew_coverage H20 R20|2025-09-10|none|20/20|-0.004|-0.7%|14.4%|-3.8%|`run_f439efe5c1594464b8fa`|
|QS22 1y lowvol20_industry H10 R20|2025-09-10|industry|10/20|-0.007|-1.3%|14.0%|-4.5%|`run_52968cf79c994b49a8e8`|
|QS2 rev5_cfoa H100 R5|2018-01-02|none|100/5|-0.017|-4.2%|57.2%|-5.5%|`run_163e6495475b4fa3b76b`|
|QS2 ma5_volume_dry H100 R5|2018-01-02|none|100/5|-0.025|-5.4%|60.7%|-6.7%|`run_2d4a38751aef4a6cb4f7`|
|QS2 momentum120_skip20 H100 R20|2018-01-02|none|100/20|-0.031|-7.1%|70.1%|-8.3%|`run_742f2af4b01a48c59b6e`|
|QS28 1y d101 winner momentum matched control H10 R20|2025-09-10|none|10/20|-0.036|-15.3%|46.0%|-18.0%|`run_1390dec03069469995b7`|
|QS3 roa H100 R20|2018-01-02|none|100/20|-0.046|-4.0%|60.8%|-5.3%|`run_5021021ba3ed41019fd9`|
|QS15 1y wq006_percentile90 H20 R10|2025-09-10|none|20/10|-0.067|-4.3%|24.4%|-7.4%|`run_12a224fe408e4f448d10`|
|QS28 1y d095 chl_spread20_high H20 R20|2025-09-10|none|20/20|-0.074|-13.3%|45.1%|-16.0%|`run_a13d6f846d1d4abf9e54`|
|QS28 1y d037 switch_vol_lowvol_moderate H10 R20|2025-09-10|none|10/20|-0.079|-5.1%|24.9%|-8.1%|`run_c910363960754ce1b047`|
|QS28 1y d020 lowdebt 低资产负债率 H20 R20|2025-09-10|none|20/20|-0.090|-7.2%|26.3%|-10.1%|`run_a5d6ea5293af43a6a325`|
|QS28 1y d108 momentum120_skip20_history200 H10 R20|2025-09-10|none|10/20|-0.091|-18.1%|49.2%|-20.7%|`run_1084118cf5914384bec9`|
|QS28 1y d023 intraday5_lowamount20 H10 R20|2025-09-10|none|10/20|-0.092|-6.6%|42.1%|-9.6%|`run_a2ade142890b4381a542`|
|QS28 1y d037 switch_vol_lowvol_moderate H20 R20|2025-09-10|none|20/20|-0.094|-4.3%|25.7%|-7.3%|`run_dd614038e5cd485c885c`|
|QS3 momentum_risk120 H100 R20|2018-01-02|none|100/20|-0.099|-8.3%|75.1%|-9.6%|`run_d048fa2df5f245aea97a`|
|QS15 1y wq006_weak_breadth20 H20 R10|2025-09-10|none|20/10|-0.103|-3.2%|19.3%|-6.3%|`run_fda37c0660e346399d7a`|
|QS28 1y d019 cash_accrual 现金盈利相对利润 H20 R20|2025-09-10|none|20/20|-0.108|-7.3%|31.6%|-10.3%|`run_eb46fa6d59d44a118ff9`|
|QS4 ytd switch_trend_mom_lowvol H100 R20|2026-01-05|none|100/20|-0.119|-6.1%|19.0%|-1.6%|`run_dfdabe2dd5964f47b841`|
|QS9 1y revenue_growth252 industry H50 R20 single|2025-09-10|industry|50/20|-0.121|-5.8%|23.9%|-8.8%|`run_1ade8d44021a488b80b1`|
|QS22 1y lowvol20_industry H20 R20|2025-09-10|industry|20/20|-0.121|-3.1%|15.7%|-6.2%|`run_7bb62048148e4ae0a282`|
|QS28 1y d086 overnight20_percentile90 H10 R20|2025-09-10|none|10/20|-0.137|-10.7%|43.6%|-13.5%|`run_3a0053684378436a80b5`|
|QS2 rev5_lowvol20 H100 R5|2018-01-02|none|100/5|-0.139|-5.4%|49.3%|-6.6%|`run_23c48d524d6347c48a5a`|
|QS8 1y profit_margin none H10 R20|2025-09-10|none|10/20|-0.144|-6.3%|29.3%|-9.3%|`run_4b89a4d019b1444fa422`|
|QS28 1y d011 lowvol60 60日低收益波动 H20 R20|2025-09-10|none|20/20|-0.144|-2.2%|13.3%|-5.3%|`run_4789161ab0ce4bdf854e`|
|QS6 prescreen lowvol20 H20 R10|2025-09-10|none|20/10|-0.150|-2.3%|14.4%|-5.4%|`run_e07bba11d6c54f4c9965`|
|QS26 1y momentum120_skip20 H20 R20|2025-09-10|none|20/20|-0.162|-17.9%|46.7%|-20.5%|`run_a64d9045d7314c39bab4`|
|QS22 1y positive_roe_industry H20 R20|2025-09-10|industry|20/20|-0.176|-6.4%|27.8%|-9.4%|`run_172ba011cc4e4f47941d`|
|QS28 1y d077 low_overnight_risk20 H10 R20|2025-09-10|none|10/20|-0.177|-2.7%|14.5%|-5.8%|`run_aa30dc2f204a47af8d6a`|
|QS26 1y close_location5 H10 R20|2025-09-10|none|10/20|-0.198|-10.3%|32.8%|-13.2%|`run_2f8ab0fceb9b4055a893`|
|QS28 1y d019 cash_accrual 现金盈利相对利润 H10 R20|2025-09-10|none|10/20|-0.200|-11.4%|30.4%|-14.3%|`run_b699af2487ae4eecacb9`|
|QS28 1y d108 momentum120_skip20_history200 H20 R20|2025-09-10|none|20/20|-0.204|-20.7%|50.0%|-23.2%|`run_77c4448588c34400b3c6`|
|QS28 1y d012 lowrange20 20日低振幅 H10 R20|2025-09-10|none|10/20|-0.217|-3.1%|13.5%|-6.2%|`run_8b670171fc39432c99c9`|
|QS28 1y d080 near_high252 H20 R20|2025-09-10|none|20/20|-0.218|-14.0%|32.2%|-16.8%|`run_ff80a9845bb3416e836c`|
|QS28 1y d034 roa_lowdebt H20 R20|2025-09-10|none|20/20|-0.233|-7.6%|19.1%|-10.5%|`run_f30792a3fe8a4c948322`|
|QS28 1y d005 ma20 20日均线偏离反转 H10 R20|2025-09-10|none|10/20|-0.239|-14.6%|43.9%|-17.3%|`run_5cba9a725a0946729d59`|
|QS14 1y clv_volume_reversal20 H10 R20|2025-09-10|none|10/20|-0.241|-9.9%|29.3%|-12.8%|`run_62ccbec1662247099e0c`|
|QS28 1y d020 lowdebt 低资产负债率 H10 R20|2025-09-10|none|10/20|-0.243|-12.5%|29.0%|-15.3%|`run_70b942af08124fe4a273`|
|QS28 1y d101 winner momentum matched control H20 R20|2025-09-10|none|20/20|-0.245|-22.7%|49.6%|-25.2%|`run_f6591f2c646e40b18606`|
|QS28 1y d064 trend_consistency60 industry H10 R20|2025-09-10|industry|10/20|-0.247|-12.7%|34.8%|-15.5%|`run_228e7717956648d7ab92`|
|QS28 1y d043 wq101 H10 R20|2025-09-10|none|10/20|-0.249|-17.3%|29.6%|-20.0%|`run_8f5fd62da8294b86be66`|
|QS15 1y wq006_weak_breadth20 H10 R10|2025-09-10|none|10/10|-0.250|-6.3%|23.9%|-9.3%|`run_ef92215f1b0f4d3bb19d`|
|QS19 1y revenue_growth252_none H20 R20|2025-09-10|none|20/20|-0.251|-9.5%|23.3%|-12.4%|`run_0292b71688a64b9891e2`|
|QS1 intraday5 H100 R5|2018-01-02|none|100/5|-0.258|-12.1%|76.4%|-13.3%|`run_efcb81b43f8c4770974a`|
|QS28 1y d027 moderate_rev5 H20 R20|2025-09-10|none|20/20|-0.259|-9.0%|30.6%|-11.9%|`run_38e03c93f3e84b398f4b`|
|QS28 1y d096 ar1_increment60 H20 R20|2025-09-10|none|20/20|-0.260|-15.9%|32.5%|-18.6%|`run_9ae9e9c0213c4c4fab27`|
|QS28 1y d105 lowmax20_skew_coverage H10 R20|2025-09-10|none|10/20|-0.261|-4.7%|15.9%|-7.7%|`run_6ecf418d55de40e580be`|
|QS19 1y lowmax20_none H10 R20|2025-09-10|none|10/20|-0.261|-4.7%|15.9%|-7.7%|`run_8f7cab7e3b72467ca770`|
|QS26 1y rev20 H10 R20|2025-09-10|none|10/20|-0.269|-16.0%|43.4%|-18.7%|`run_44b9548bba4449559899`|
|QS4 1y lowvol20 H100 R20|2025-09-10|none|100/20|-0.269|-3.5%|15.8%|-6.6%|`run_38add7ac94b24695ac79`|
|QS28 1y d032 momentum_lowvol60 H20 R20|2025-09-10|none|20/20|-0.272|-5.8%|17.6%|-8.8%|`run_d04254f233dd49908398`|
|QS8 1y profit_margin none H20 R20|2025-09-10|none|20/20|-0.275|-7.2%|24.0%|-10.1%|`run_cd3bf5681ecb4d499c0d`|
|QS8 1y profit_margin none H20 R10|2025-09-10|none|20/10|-0.275|-7.1%|23.3%|-10.1%|`run_e37133fbf2124c93a02c`|
|QS6 prescreen wq016 H20 R20|2025-09-10|none|20/20|-0.276|-11.5%|34.3%|-14.3%|`run_47a20c9e4c92499baef8`|
|QS28 1y d109 price_to_ma200 H20 R20|2025-09-10|none|20/20|-0.288|-27.4%|51.3%|-29.7%|`run_25dec76b6ff4452e8e3c`|
|QS28 1y d031 lowamount20_lowvol20 H10 R20|2025-09-10|none|10/20|-0.294|-6.1%|23.9%|-9.1%|`run_cf95b27045d04d2cb4a1`|
|QS28 1y d043 wq101 H20 R20|2025-09-10|none|20/20|-0.298|-15.5%|30.2%|-18.2%|`run_f388fb1eb2e649eea664`|
|QS28 1y d063 revenue_growth252 industry H10 R20|2025-09-10|industry|10/20|-0.303|-12.7%|28.2%|-15.5%|`run_92d30c020d64478a8ca9`|
|QS28 1y d078 clv_volume20 H20 R20|2025-09-10|none|20/20|-0.309|-15.2%|36.4%|-17.9%|`run_09f74d346e4c475ba72c`|
|QS28 1y d018 cfoa 经营现金资产比 H10 R20|2025-09-10|none|10/20|-0.324|-9.7%|26.5%|-12.6%|`run_cc9eee9be80143e7a6c5`|
|QS28 1y d100 FIP winner continuity H10 R20|2025-09-10|none|10/20|-0.325|-20.4%|46.5%|-22.9%|`run_5217e68dd8b042c895be`|
|QS4 1y cfoa H100 R20|2025-09-10|none|100/20|-0.334|-7.2%|18.7%|-10.2%|`run_3bf8a542b6cb4b9eb512`|
|QS19 1y positive_roe_none H10 R20|2025-09-10|none|10/20|-0.337|-10.0%|29.6%|-12.9%|`run_d44a5acfe66a42639bef`|
|QS1 rev5 H100 R20|2018-01-02|none|100/20|-0.338|-14.2%|82.3%|-15.4%|`run_5813412a97de467991cf`|
|QS26 1y intraday5 H20 R20|2025-09-10|none|20/20|-0.340|-16.8%|39.6%|-19.4%|`run_fe6db5c8d9264a54a1fe`|
|QS14 1y clv_volume_reversal20 H20 R20|2025-09-10|none|20/20|-0.341|-11.8%|32.8%|-14.6%|`run_59a79ac183fe4a23bd16`|
|QS28 1y d046 wq009_ret_switch H10 R20|2025-09-10|none|10/20|-0.361|-21.7%|46.3%|-24.2%|`run_3b612ff18e624abf9968`|
|QS28 1y d035 switch_trend_mom_lowvol H20 R20|2025-09-10|none|20/20|-0.367|-11.0%|24.1%|-13.8%|`run_222a56cedf21406f8642`|
|QS28 1y d102 continuity formation control H10 R20|2025-09-10|none|10/20|-0.369|-20.9%|48.1%|-23.4%|`run_00ecac8335e84072aec0`|
|QS28 1y d107 mrat21_200 H10 R20|2025-09-10|none|10/20|-0.381|-32.7%|54.8%|-34.9%|`run_74da4341ee61432884f4`|
|QS8 1y profit_margin none H10 R10|2025-09-10|none|10/10|-0.388|-11.6%|30.9%|-14.4%|`run_f438ed5760cf42089ba6`|
|QS13 1y overnight_mom20 H20 R20|2025-09-10|none|20/20|-0.395|-24.4%|42.1%|-26.8%|`run_7b73782d1631488e8d17`|
|QS28 1y d102 continuity formation control H20 R20|2025-09-10|none|20/20|-0.400|-19.1%|41.9%|-21.7%|`run_eb05c3b38a3f4e92a575`|
|QS28 1y d050 cash_margin none H20 R20|2025-09-10|none|20/20|-0.401|-9.1%|21.9%|-12.0%|`run_aa05840caffb41388114`|
|QS4 1y switch_trend_mom_lowvol H100 R20|2025-09-10|none|100/20|-0.405|-11.2%|21.9%|-14.0%|`run_7df1db67efbf46ccbd60`|
|QS19 1y quality_defensive_industry H20 R20|2025-09-10|industry|20/20|-0.407|-8.7%|28.0%|-11.6%|`run_264c7ea0243d454492aa`|
|QS28 1y d027 moderate_rev5 H10 R20|2025-09-10|none|10/20|-0.416|-14.5%|33.9%|-17.2%|`run_e7389b25c96646cb94e9`|
|QS28 1y d012 lowrange20 20日低振幅 H20 R20|2025-09-10|none|20/20|-0.417|-5.1%|15.9%|-8.1%|`run_c584f0cea48c451db2de`|
|QS28 1y d107 mrat21_200 H20 R20|2025-09-10|none|20/20|-0.420|-33.1%|53.8%|-35.2%|`run_d9f6fdf019c747a38766`|
|QS28 1y d044 wq101_mean5 H20 R20|2025-09-10|none|20/20|-0.420|-18.6%|30.1%|-21.2%|`run_2157292fe3814b0bae47`|
|QS22 1y quality_defensive_none H10 R20|2025-09-10|none|10/20|-0.430|-8.9%|23.6%|-11.8%|`run_fd375d4b19d042a7826a`|
|QS14 1y intraday_reversal20 H20 R20|2025-09-10|none|20/20|-0.434|-17.6%|37.6%|-20.2%|`run_c514e854a88a4306893d`|
|QS28 1y d046 wq009_ret_switch H20 R20|2025-09-10|none|20/20|-0.450|-21.8%|36.9%|-24.3%|`run_ee1f8dcfe9dd4439be9f`|
|QS28 1y d039 wq006 H10 R20|2025-09-10|none|10/20|-0.454|-12.7%|31.6%|-15.5%|`run_90291e3716f94f559148`|
|QS28 1y d030 cfoa_trend120 H20 R20|2025-09-10|none|20/20|-0.484|-13.9%|30.0%|-16.7%|`run_3721a13529ac4bc0ad1a`|
|QS28 1y d050 cash_margin none H10 R20|2025-09-10|none|10/20|-0.485|-10.5%|24.4%|-13.4%|`run_1a1a6163af2945d3920f`|
|QS6 prescreen wq016 H20 R10|2025-09-10|none|20/10|-0.490|-18.2%|36.3%|-20.8%|`run_9caf6b1c4a6c4b41b0d6`|
|QS19 1y revenue_growth252_none H10 R20|2025-09-10|none|10/20|-0.490|-16.0%|26.4%|-18.6%|`run_b4709084b1c148d5bda1`|
|QS22 1y cash_margin_industry H20 R20|2025-09-10|industry|20/20|-0.500|-17.7%|39.6%|-20.4%|`run_1d82f358d6504066b9b8`|
|QS28 1y d054 trend_consistency60 none H20 R20|2025-09-10|none|20/20|-0.518|-26.1%|43.7%|-28.5%|`run_2571def985834dbea043`|
|QS28 1y d095 chl_spread20_high H10 R20|2025-09-10|none|10/20|-0.519|-31.6%|51.5%|-33.8%|`run_7dab1f107d344b338c97`|
|QS19 1y wq012_ret_none H10 R20|2025-09-10|none|10/20|-0.528|-28.9%|37.1%|-31.2%|`run_f135fd937953416f9ccd`|
|QS28 1y d030 cfoa_trend120 H10 R20|2025-09-10|none|10/20|-0.532|-18.0%|34.6%|-20.6%|`run_0001837f61c04a83b580`|
|QS22 1y cash_margin_industry H10 R20|2025-09-10|industry|10/20|-0.546|-22.3%|42.0%|-24.8%|`run_8327dd40cdf54721b6a2`|
|QS1 rev5 H50 R20|2018-01-02|none|50/20|-0.562|-20.9%|90.3%|-22.0%|`run_00c56b77816f4cea9ab5`|
|QS28 1y d097 reversal1_ar_coverage H20 R20|2025-09-10|none|20/20|-0.569|-21.9%|37.5%|-24.4%|`run_7db18cdae236482292b0`|
|QS28 1y d093 amount_cv60_high H20 R20|2025-09-10|none|20/20|-0.583|-23.2%|48.0%|-25.7%|`run_ada08979e69c48d98fb1`|
|QS28 1y d001 rev1 1日反转 H20 R20|2025-09-10|none|20/20|-0.585|-22.3%|37.7%|-24.8%|`run_8f1df02cdb174858b76e`|
|QS4 ytd switch_vol_lowvol_moderate H100 R20|2026-01-05|none|100/20|-0.614|-12.9%|23.4%|-8.8%|`run_25e41e948fd544c0b99d`|
|QS28 1y d026 lowamount20_roa H20 R20|2025-09-10|none|20/20|-0.622|-11.2%|20.4%|-14.0%|`run_3ec5059d8de94743b55b`|
|QS28 1y d011 lowvol60 60日低收益波动 H10 R20|2025-09-10|none|10/20|-0.627|-7.5%|17.1%|-10.4%|`run_9532142d3b424426a347`|
|QS14 1y intraday_reversal20 H10 R20|2025-09-10|none|10/20|-0.635|-25.2%|45.0%|-27.6%|`run_aa814c655423400bb497`|
|QS19 1y wq013_none H20 R20|2025-09-10|none|20/20|-0.636|-19.9%|39.5%|-22.4%|`run_b04fee5ce5314961aef0`|
|QS1 rev5 H100 R10|2018-01-02|none|100/10|-0.638|-21.3%|88.7%|-22.3%|`run_680fc2d3814447e8b67d`|
|QS28 1y d093 amount_cv60_high H10 R20|2025-09-10|none|10/20|-0.640|-28.3%|54.4%|-30.6%|`run_c04cdea597634ddf845e`|
|QS1 rev5 H100 R5|2018-01-02|none|100/5|-0.679|-21.9%|89.5%|-22.9%|`run_4bd488c22fcc4e72aaf1`|
|QS22 1y positive_roe_industry H10 R20|2025-09-10|industry|10/20|-0.680|-18.7%|33.1%|-21.3%|`run_a3b6fad0acd04f869b6b`|
|QS28 1y d018 cfoa 经营现金资产比 H20 R20|2025-09-10|none|20/20|-0.682|-14.4%|23.3%|-17.2%|`run_a133fc81455f40f29b48`|
|QS26 1y roa H10 R20|2025-09-10|none|10/20|-0.687|-18.0%|23.7%|-20.6%|`run_041d1b65491040b7b871`|
|QS14 1y overnight_mom20_industry H10 R20|2025-09-10|industry|10/20|-0.696|-28.9%|36.1%|-31.2%|`run_ce498bb41bae4b4182dd`|
|QS28 1y d094 chl_spread20_low H20 R20|2025-09-10|none|20/20|-0.702|-17.0%|26.7%|-19.6%|`run_d97c8080b1554041b048`|
|QS28 1y d064 trend_consistency60 industry H20 R20|2025-09-10|industry|20/20|-0.713|-22.4%|37.3%|-24.8%|`run_89e4a23323114eeabc0d`|
|QS28 1y d005 ma20 20日均线偏离反转 H20 R20|2025-09-10|none|20/20|-0.713|-25.2%|45.4%|-27.6%|`run_d166dace016949f3ac4a`|
|QS28 1y d054 trend_consistency60 none H10 R20|2025-09-10|none|10/20|-0.727|-34.5%|49.1%|-36.6%|`run_515b9c90752044b0b010`|
|QS28 1y d080 near_high252 H10 R20|2025-09-10|none|10/20|-0.732|-31.7%|45.0%|-33.9%|`run_eac1cfcf87f94f2ab955`|
|QS22 1y quality_defensive_none H20 R20|2025-09-10|none|20/20|-0.763|-13.3%|22.3%|-16.1%|`run_ef1ee9e6f70941f58f19`|
|QS6 prescreen wq016 H10 R10|2025-09-10|none|10/10|-0.767|-31.3%|44.2%|-33.5%|`run_a195295e7c2849508bb5`|
|QS28 1y d070 lowvol LOO_breadth20 H20 R20|2025-09-10|none|20/20|-0.776|-4.9%|8.0%|-7.9%|`run_147017bb69cf4e49a09b`|
|QS1 ma5 H100 R5|2018-01-02|none|100/5|-0.781|-24.2%|91.8%|-25.2%|`run_43ee484d372a4ba79049`|
|QS19 1y wq012_ret_none H20 R20|2025-09-10|none|20/20|-0.789|-33.1%|40.2%|-35.2%|`run_08ae57b1b5ca445ab584`|
|QS6 prescreen wq016 H10 R20|2025-09-10|none|10/20|-0.789|-27.4%|46.7%|-29.7%|`run_66bf715974274a0eb53c`|
|QS19 1y quality_defensive_industry H10 R20|2025-09-10|industry|10/20|-0.800|-15.6%|27.3%|-18.3%|`run_555dda7f88d744d998dd`|
|QS19 1y positive_roe_none H20 R20|2025-09-10|none|20/20|-0.880|-17.0%|27.6%|-19.6%|`run_c465a7be404b436e85fa`|
|QS28 1y d004 ma5 5日均线偏离反转 H20 R20|2025-09-10|none|20/20|-0.904|-29.1%|44.0%|-31.4%|`run_70ac63ab5a1447fcb3f9`|
|QS10 1y lowvol LOO_breadth20 H20 R10|2025-09-10|none|20/10|-0.946|-5.0%|7.1%|-8.0%|`run_cbc4ec9ad95f414cb7e5`|
|QS9 1y revenue_growth252 industry H20 R20 single|2025-09-10|industry|20/20|-0.974|-23.7%|33.9%|-26.2%|`run_5f316b8f337941748319`|
|QS28 1y d004 ma5 5日均线偏离反转 H10 R20|2025-09-10|none|10/20|-0.982|-33.5%|48.4%|-35.6%|`run_a3f3e1f3957c416fa052`|
|QS22 1y profit_margin_industry H10 R20|2025-09-10|industry|10/20|-1.010|-24.1%|38.0%|-26.5%|`run_6fb4b3a3dc80443a94a7`|
|QS28 1y d001 rev1 1日反转 H10 R20|2025-09-10|none|10/20|-1.025|-35.1%|47.3%|-37.2%|`run_82953f8488be402ab952`|
|QS1 rev5 H100 R1|2018-01-02|none|100/1|-1.038|-29.3%|95.1%|-30.2%|`run_e02a651b80644c5a931e`|
|QS6 prescreen wq016 H5 R10|2025-09-10|none|5/10|-1.045|-46.2%|55.2%|-47.9%|`run_de9888b4deaa4f44b956`|
|QS1 rev5 H20 R20|2018-01-02|none|20/20|-1.047|-35.0%|97.8%|-35.8%|`run_aaecbd38ba784354b8f6`|
|QS28 1y d002 rev5 5日反转 H20 R20|2025-09-10|none|20/20|-1.056|-35.2%|50.1%|-37.2%|`run_c88938e88f6a45ee98de`|
|QS1 rev5 H50 R10|2018-01-02|none|50/10|-1.064|-31.1%|96.2%|-32.0%|`run_7b743a714a2046318e61`|
|QS28 1y d094 chl_spread20_low H10 R20|2025-09-10|none|10/20|-1.081|-26.6%|38.9%|-29.0%|`run_259b855e449c405a92da`|
|QS6 prescreen wq016 H5 R20|2025-09-10|none|5/20|-1.093|-39.9%|59.7%|-41.8%|`run_c3cc60adb32d4be1923a`|
|QS28 1y d044 wq101_mean5 H10 R20|2025-09-10|none|10/20|-1.096|-40.6%|44.6%|-42.5%|`run_ce2a88ffef3a4e939df0`|
|QS19 1y wq013_none H10 R20|2025-09-10|none|10/20|-1.128|-35.3%|47.3%|-37.4%|`run_eddb56451afe415c8d7c`|
|QS10 1y lowvol LOO_breadth20 H100 R10|2025-09-10|none|100/10|-1.130|-5.9%|7.7%|-8.9%|`run_b4141f517ae84d16ba40`|
|QS28 1y d007 overnight20 20日隔夜反转 H20 R20|2025-09-10|none|20/20|-1.140|-34.3%|41.6%|-36.4%|`run_c99a03ccc17b42a59837`|
|QS28 1y d007 overnight20 20日隔夜反转 H10 R20|2025-09-10|none|10/20|-1.141|-37.8%|47.0%|-39.8%|`run_ec976b14deed4bd0a2f5`|
|QS28 1y d002 rev5 5日反转 H10 R20|2025-09-10|none|10/20|-1.161|-40.8%|56.7%|-42.7%|`run_204bb650819e46d2a166`|
|QS1 rev5 H50 R5|2018-01-02|none|50/5|-1.175|-32.5%|96.7%|-33.4%|`run_fc7f33c9b7d74cc29579`|
|QS28 1y d097 reversal1_ar_coverage H10 R20|2025-09-10|none|10/20|-1.198|-38.4%|49.8%|-40.4%|`run_41faef649cda4938ac80`|
|QS10 1y lowvol LOO_breadth20 H10 R5|2025-09-10|none|10/5|-1.236|-6.2%|8.1%|-9.2%|`run_d1fdc66c4cb64c83a84d`|
|QS15 quarter wq006_strong_breadth20 H20 R10|2026-06-11|none|20/10|-1.252|-13.2%|6.2%|3.8%|`run_bfd15d265dc74f59aa22`|
|QS28 1y d084 wq006_strong_breadth20 H10 R20|2025-09-10|none|10/20|-1.266|-18.4%|23.9%|-21.0%|`run_bcd85d81ef374770b079`|
|QS26 1y roa H20 R20|2025-09-10|none|20/20|-1.269|-22.0%|25.9%|-24.5%|`run_546191d4caf44a40a8e9`|
|QS22 1y profit_margin_industry H20 R20|2025-09-10|industry|20/20|-1.350|-29.8%|43.7%|-32.1%|`run_1e4fb5bcda304fcfaaf5`|
|QS28 1y d016 roe 净资产盈利率 H20 R20|2025-09-10|none|20/20|-1.358|-29.8%|38.3%|-32.1%|`run_1ba88cbcb78649c5bea4`|
|QS1 rev5 H20 R10|2018-01-02|none|20/10|-1.693|-45.3%|99.4%|-46.1%|`run_200a292e1ab44e5f9e90`|
|QS28 1y d016 roe 净资产盈利率 H10 R20|2025-09-10|none|10/20|-1.799|-42.9%|51.9%|-44.7%|`run_e409850d95a343dfaacd`|
|QS1 rev5 H50 R1|2018-01-02|none|50/1|-2.012|-44.7%|99.3%|-45.4%|`run_2bd72c12b5e540ddbf2d`|
|QS1 rev5 H20 R5|2018-01-02|none|20/5|-2.358|-51.6%|99.8%|-52.2%|`run_f2fc3d66e6844b2ea27e`|
|QS1 rev1 H100 R1|2018-01-02|none|100/1|-3.128|-50.5%|99.7%|-51.2%|`run_59408465548b44599285`|
|QS1 rev5 H20 R1|2018-01-02|none|20/1|-3.320|-60.1%|100.0%|-60.7%|`run_695cd664ad654723969c`|

## 因子筛选

因子 Rank IC 不是 Sharpe；多空分组收益也未计入交易成本。

各行日期不同，排序仅供检索，不将短窗口与多年样本视为同一对照。

|名称|区间起点|中性化|1日 Rank IC|5日 Rank IC|20日 Rank IC|5日多空收益|
|---|---|---|---:|---:|---:|---:|
|QS16 quarter market_switch_amount_lowvol H20 R10|2026-06-11|none|0.067|0.134|0.238|2.3%|
|QS5 63s lowvol20 H50 R10|2026-06-11|none|0.041|0.098|0.206|1.6%|
|QS2 lowvol20_trend120 H100 R20|2018-01-02|none|0.050|0.088|0.117|0.7%|
|QS28 1y d074 lowvol LOO_weak_breadth20 H20 R20|2025-09-10|none|0.057|0.079|0.093|0.8%|
|QS1 lowrange20 20日低振幅|2018-01-02|none|0.043|0.070|0.092|0.2%|
|QS2 rev5_lowvol20 H100 R5|2018-01-02|none|0.051|0.068|0.086|0.4%|
|QS1 lowvol20 H100 R20|2018-01-02|none|0.041|0.068|0.088|0.3%|
|QS2 lowamount20_lowvol20 H100 R20|2018-01-02|none|0.038|0.067|0.094|0.4%|
|QS16 3y market_switch_amount_lowvol H20 R10|2023-09-11|none|0.038|0.062|0.071|0.4%|
|QS1 lowvol60 60日低收益波动|2018-01-02|none|0.036|0.061|0.086|0.2%|
|QS2 intraday5_lowamount20 H100 R5|2018-01-02|none|0.043|0.059|0.084|0.5%|
|QS22 1y volume_dry_lowvol_none H20 R20|2025-09-10|none|0.043|0.059|0.082|0.1%|
|QS14 1y intraday_reversal20 H10 R20|2025-09-10|none|0.041|0.058|0.092|0.2%|
|QS1 rev20 20日反转|2018-01-02|none|0.038|0.058|0.075|0.5%|
|QS7 recovery 1y lowmax20 none|2025-09-10|none|0.035|0.054|0.078|0.2%|
|QS28 1y d105 lowmax20_skew_coverage H20 R20|2025-09-10|none|0.035|0.054|0.078|0.2%|
|QS28 1y d066 volume_dry_lowvol industry H20 R20|2025-09-10|industry|0.042|0.053|0.073|0.1%|
|QS1 ma20 20日均线偏离反转|2018-01-02|none|0.041|0.053|0.067|0.4%|
|QS28 1y d088 market_switch_amount_lowvol H10 R20|2025-09-10|none|0.032|0.053|0.069|0.2%|
|QS6 prescreen lowvol20 H5 R10|2025-09-10|none|0.034|0.052|0.075|0.0%|
|QS25 1y lowvol20_skew_coverage|2025-09-10|none|0.034|0.052|0.075|0.0%|
|QS11 3y lowamount LOO_breadth60 H20 R10|2023-09-11|none|0.025|0.052|0.072|0.3%|
|QS7 1y lowvol20_control industry|2025-09-10|industry|0.035|0.052|0.073|0.1%|
|QS20 1y lowvol20_instability_coverage H10 R20|2025-09-10|none|0.034|0.052|0.075|-0.0%|
|QS28 1y d012 lowrange20 20日低振幅 H10 R20|2025-09-10|none|0.033|0.050|0.067|-0.1%|
|QS22 1y lowmax20_industry H10 R20|2025-09-10|industry|0.034|0.050|0.074|0.1%|
|QS2 moderate_rev5 H100 R5|2018-01-02|none|0.041|0.050|0.059|0.4%|
|QS4 3y switch_vol_lowvol_moderate H100 R20|2023-09-11|none|0.039|0.049|0.065|0.2%|
|QS28 1y d029 lowvol20_trend120 H10 R20|2025-09-10|none|0.030|0.048|0.068|0.1%|
|QS1 volume_dry 5比60日缩量|2018-01-02|none|0.036|0.048|0.055|0.3%|
|QS3 momentum_lowvol60 H100 R20|2018-01-02|none|0.030|0.047|0.064|0.2%|
|QS10 3y lowamount LOO_breadth20 H20 R10|2023-09-11|none|0.020|0.047|0.075|0.2%|
|QS4 3y switch_trend_amount_lowvol H100 R20|2023-09-11|none|0.029|0.046|0.060|0.1%|
|QS2 ma5_volume_dry H100 R5|2018-01-02|none|0.042|0.046|0.050|0.3%|
|QS26 1y rev20 H10 R20|2025-09-10|none|0.033|0.046|0.070|0.0%|
|QS28 1y d021 rev5_lowvol20 H10 R20|2025-09-10|none|0.037|0.046|0.075|-0.1%|
|QS28 1y d031 lowamount20_lowvol20 H20 R20|2025-09-10|none|0.027|0.045|0.064|-0.1%|
|QS3 2023 lowamount20 H100 R10|2023-01-03|none|0.023|0.045|0.068|0.3%|
|QS28 1y d015 volume_dry 5比60日缩量 H20 R20|2025-09-10|none|0.037|0.044|0.061|0.1%|
|QS1 lowamount20 20日低成交额|2018-01-02|none|0.022|0.044|0.068|0.4%|
|QS4 1y switch_vol_lowvol_moderate H100 R20|2025-09-10|none|0.036|0.044|0.069|0.1%|
|QS5 1y wq016|2025-09-10|none|0.030|0.043|0.054|0.3%|
|QS5 1y wq013|2025-09-10|none|0.031|0.043|0.056|0.3%|
|QS1 intraday5 5日日内反转|2018-01-02|none|0.040|0.043|0.055|0.4%|
|QS26 1y original lowvol60|2025-09-10|none|0.026|0.042|0.051|-0.0%|
|QS2 lowamount20_trend120 H100 R20|2018-01-02|none|0.017|0.041|0.069|0.4%|
|QS2 lowamount20_cfoa H100 R20|2018-01-02|none|0.021|0.041|0.063|0.3%|
|QS11 3y lowamount LOO_breadth120 H10 R5|2023-09-11|none|0.019|0.037|0.053|0.1%|
|QS14 1y clv_volume_reversal20 H20 R20|2025-09-10|none|0.025|0.037|0.053|0.4%|
|QS26 1y original ma20|2025-09-10|none|0.031|0.037|0.061|-0.2%|
|QS15 3y wq006_strong_breadth20 H20 R10|2023-09-11|none|0.026|0.037|0.057|0.3%|
|QS2 lowamount20_roa H100 R20|2018-01-02|none|0.019|0.036|0.055|0.3%|
|QS28 1y d032 momentum_lowvol60 H10 R20|2025-09-10|none|0.025|0.036|0.057|0.2%|
|QS8 1y downside20 industry H10 R20|2025-09-10|industry|0.020|0.035|0.047|0.2%|
|QS11 1y lowamount LOO_breadth60 H10 R5|2025-09-10|none|0.009|0.034|0.058|-0.1%|
|QS1 rev5 5日反转|2018-01-02|none|0.034|0.034|0.040|0.3%|
|QS20 1y historical_vol_instability20_60_low|2025-09-10|none|0.018|0.034|0.065|0.5%|
|QS13 1y low_overnight_risk20|2025-09-10|none|0.021|0.033|0.041|-0.2%|
|QS18 1y amount_cv60_low H20 R20|2025-09-10|none|0.020|0.033|0.070|0.3%|
|QS2 rev5_cfoa H100 R5|2018-01-02|none|0.029|0.033|0.042|0.3%|
|QS28 1y d026 lowamount20_roa H20 R20|2025-09-10|none|0.016|0.033|0.050|0.1%|
|QS19 1y downside20_none H10 R20|2025-09-10|none|0.019|0.033|0.049|0.0%|
|QS4 ytd switch_trend_amount_lowvol H100 R20|2026-01-05|none|0.018|0.033|0.047|-0.1%|
|QS8 1y lowamount20 industry H20 R20|2025-09-10|industry|0.015|0.031|0.047|0.1%|
|QS28 1y d086 overnight20_percentile90 H10 R20|2025-09-10|none|0.019|0.031|0.053|0.6%|
|QS28 1y d023 intraday5_lowamount20 H20 R20|2025-09-10|none|0.027|0.030|0.062|-0.1%|
|QS19 1y wq012_ret_none H20 R20|2025-09-10|none|0.021|0.030|0.034|0.2%|
|QS28 1y d036 switch_trend_amount_lowvol H10 R20|2025-09-10|none|0.017|0.030|0.045|-0.2%|
|QS19 1y quality_defensive_industry H20 R20|2025-09-10|industry|0.019|0.029|0.042|0.1%|
|QS1 ma5 H100 R5|2018-01-02|none|0.030|0.029|0.029|0.3%|
|QS13 1y overnight_mom20|2025-09-10|none|0.018|0.029|0.049|0.6%|
|QS7 recovery 1y quality_defensive none|2025-09-10|none|0.019|0.028|0.043|0.0%|
|QS28 1y d027 moderate_rev5 H20 R20|2025-09-10|none|0.030|0.027|0.055|-0.1%|
|QS4 ytd switch_vol_lowvol_moderate H100 R20|2026-01-05|none|0.027|0.027|0.056|-0.1%|
|QS28 1y d025 ma5_volume_dry H20 R20|2025-09-10|none|0.030|0.027|0.049|-0.2%|
|QS14 1y overnight_mom20_industry H20 R20|2025-09-10|industry|0.014|0.026|0.044|0.6%|
|QS7 recovery 1y positive_roe none|2025-09-10|none|0.014|0.026|0.042|0.1%|
|QS11 1y lowamount coverage120_control H10 R5|2025-09-10|none|0.011|0.025|0.035|-0.1%|
|QS6 prescreen lowamount20 H20 R20|2025-09-10|none|0.011|0.025|0.035|-0.1%|
|QS2 cfoa_trend120 H100 R20|2018-01-02|none|0.014|0.025|0.037|0.2%|
|QS8 1y profit_margin none H10 R20|2025-09-10|none|0.014|0.025|0.042|0.2%|
|QS28 1y d016 roe 净资产盈利率 H20 R20|2025-09-10|none|0.014|0.025|0.040|0.1%|
|QS1 close_location5 5日收盘位置反转|2018-01-02|none|0.025|0.023|0.028|0.4%|
|QS22 1y wq002_none H10 R20|2025-09-10|none|0.018|0.022|0.033|0.1%|
|QS19 1y revenue_growth252_none H20 R20|2025-09-10|none|0.010|0.022|0.040|0.5%|
|QS28 1y d104 total_daily_skew20_low H10 R20|2025-09-10|none|0.015|0.022|0.015|0.2%|
|QS22 1y positive_roe_industry H20 R20|2025-09-10|industry|0.013|0.022|0.033|0.2%|
|QS28 1y d024 lowamount20_cfoa H20 R20|2025-09-10|none|0.012|0.021|0.029|-0.1%|
|QS26 1y roa H10 R20|2025-09-10|none|0.012|0.021|0.035|0.1%|
|QS22 1y profit_margin_industry H20 R20|2025-09-10|industry|0.011|0.019|0.032|0.2%|
|QS10 quarter lowamount LOO_breadth20 H20 R10|2026-06-11|none|-0.041|0.019|0.089|-0.5%|
|QS26 1y original intraday5|2025-09-10|none|0.029|0.019|0.053|-0.1%|
|QS22 1y wq003_none H10 R20|2025-09-10|none|0.012|0.018|0.031|0.2%|
|QS26 1y close_location5 H10 R20|2025-09-10|none|0.019|0.018|0.036|0.1%|
|QS15 1y neighbor wq006_strong_breadth20 H20 R5|2025-09-10|none|0.022|0.017|0.038|0.1%|
|QS28 1y d085 wq006_weak_breadth20 H20 R20|2025-09-10|none|0.010|0.017|0.049|0.2%|
|QS15 1y wq006_percentile90 H20 R10|2025-09-10|none|0.014|0.017|0.043|0.2%|
|QS13 1y wq006 H20 R10|2025-09-10|none|0.014|0.017|0.044|0.2%|
|QS1 rev1 1日反转|2018-01-02|none|0.022|0.016|0.013|0.2%|
|QS28 1y d028 lowamount20_trend120 H20 R20|2025-09-10|none|0.006|0.014|0.021|-0.2%|
|QS1 cfoa 经营现金资产比|2018-01-02|none|0.008|0.014|0.020|0.1%|
|QS28 1y d069 lowamount LOO_breadth20 H10 R20|2025-09-10|none|-0.006|0.013|0.032|-0.5%|
|QS16 1y common_valid_amount_cash H20 R10|2025-09-10|none|-0.006|0.013|0.032|-0.5%|
|QS9 1y revenue_growth252 industry H50 R20 single|2025-09-10|industry|0.006|0.013|0.022|0.3%|
|QS1 roe 净资产盈利率|2018-01-02|none|0.008|0.012|0.015|-0.0%|
|QS15 quarter wq006_strong_breadth20 H20 R10|2026-06-11|none|0.043|0.012|0.147|0.1%|
|QS28 1y d070 lowvol LOO_breadth20 H20 R20|2025-09-10|none|-0.000|0.011|0.047|-1.1%|
|QS11 1y lowamount LOO_breadth120 H20 R10|2025-09-10|none|0.006|0.011|0.019|-0.4%|
|QS28 1y d022 rev5_cfoa H10 R20|2025-09-10|none|0.017|0.010|0.029|-0.3%|
|QS28 1y d094 chl_spread20_low H10 R20|2025-09-10|none|0.003|0.009|0.033|0.2%|
|QS28 1y d034 roa_lowdebt H10 R20|2025-09-10|none|0.005|0.009|0.018|0.1%|
|QS26 1y original rev5|2025-09-10|none|0.019|0.009|0.037|-0.3%|
|QS28 1y d050 cash_margin none H10 R20|2025-09-10|none|0.006|0.008|0.014|-0.1%|
|QS3 roa H100 R20|2018-01-02|none|0.005|0.008|0.010|-0.0%|
|QS22 1y cash_margin_industry H20 R20|2025-09-10|industry|0.006|0.008|0.013|0.0%|
|QS4 3y switch_trend_mom_lowvol H100 R20|2023-09-11|none|0.012|0.007|0.005|-0.1%|
|QS28 1y d030 cfoa_trend120 H10 R20|2025-09-10|none|0.007|0.007|0.003|-0.1%|
|QS1 cash_accrual 现金盈利相对利润|2018-01-02|none|0.003|0.006|0.012|0.1%|
|QS4 ytd switch_trend_mom_lowvol H100 R20|2026-01-05|none|0.009|0.006|0.026|0.0%|
|QS4 1y cfoa H100 R20|2025-09-10|none|0.006|0.005|0.005|-0.1%|
|QS18 1y efficiency_change252|2025-09-10|none|0.002|0.005|0.008|0.2%|
|QS28 1y d035 switch_trend_mom_lowvol H20 R20|2025-09-10|none|0.006|0.003|0.020|-0.1%|
|QS1 illiquidity20 20日非流动性|2018-01-02|none|-0.004|0.003|0.016|0.2%|
|QS28 1y d004 ma5 5日均线偏离反转 H20 R20|2025-09-10|none|0.010|0.002|0.020|-0.3%|
|QS3 roa_lowdebt H100 R20|2018-01-02|none|0.001|0.002|0.003|0.0%|
|QS18 1y efficiency_level_matched|2025-09-10|none|-0.000|-0.001|-0.006|-0.0%|
|QS28 1y d001 rev1 1日反转 H10 R20|2025-09-10|none|0.018|-0.001|0.006|-0.2%|
|QS20 1y reversal1_ar_coverage|2025-09-10|none|0.019|-0.001|0.006|-0.2%|
|QS28 1y d046 wq009_ret_switch H10 R20|2025-09-10|none|0.014|-0.002|0.001|-0.2%|
|QS28 1y d096 ar1_increment60 H20 R20|2025-09-10|none|-0.005|-0.004|-0.001|-0.1%|
|QS28 1y d079 amihud20 H10 R20|2025-09-10|none|-0.009|-0.004|-0.010|-0.1%|
|QS28 1y d013 illiquidity20 20日非流动性 H10 R20|2025-09-10|none|-0.009|-0.004|-0.010|-0.1%|
|QS1 lowdebt 低资产负债率|2018-01-02|none|-0.003|-0.005|-0.005|0.0%|
|QS28 1y d020 lowdebt 低资产负债率 H10 R20|2025-09-10|none|-0.002|-0.005|-0.004|0.1%|
|QS28 1y d100 FIP winner continuity H10 R20|2025-09-10|none|-0.001|-0.007|-0.015|-0.2%|
|QS28 1y d102 continuity formation control H10 R20|2025-09-10|none|-0.001|-0.008|-0.002|-0.0%|
|QS2 momentum120_skip20 H100 R20|2018-01-02|none|-0.002|-0.008|-0.014|-0.0%|
|QS18 1y chl_spread20_high|2025-09-10|none|-0.003|-0.009|-0.033|-0.2%|
|QS26 1y momentum120_skip20 H20 R20|2025-09-10|none|-0.003|-0.009|0.001|0.3%|
|QS28 1y d108 momentum120_skip20_history200 H10 R20|2025-09-10|none|-0.003|-0.010|0.001|0.3%|
|QS5 1y wq101|2025-09-10|none|-0.020|-0.010|-0.021|-0.1%|
|QS26 1y original cash_accrual|2025-09-10|none|-0.005|-0.012|-0.023|-0.3%|
|QS28 1y d101 winner momentum matched control H10 R20|2025-09-10|none|-0.008|-0.013|-0.021|-0.0%|
|QS1 overnight20 20日隔夜反转|2018-01-02|none|-0.009|-0.015|-0.028|-0.2%|
|QS13 1y near_high252|2025-09-10|none|-0.013|-0.017|-0.018|0.2%|
|QS28 1y d044 wq101_mean5 H20 R20|2025-09-10|none|-0.022|-0.018|-0.046|0.0%|
|QS7 recovery 1y lowasset_growth252 industry|2025-09-10|industry|-0.011|-0.020|-0.034|-0.3%|
|QS27 1y mrat21_200|2025-09-10|none|-0.013|-0.023|-0.019|0.4%|
|QS7 1y trend_consistency60 industry|2025-09-10|industry|-0.015|-0.026|-0.040|-0.2%|
|QS28 1y d007 overnight20 20日隔夜反转 H20 R20|2025-09-10|none|-0.018|-0.029|-0.049|-0.6%|
|QS28 1y d033 momentum_risk120 H10 R20|2025-09-10|none|-0.019|-0.031|-0.027|0.2%|
|QS7 recovery 1y lowasset_growth252 none|2025-09-10|none|-0.017|-0.033|-0.058|-0.6%|
|QS18 1y amount_cv60_high|2025-09-10|none|-0.020|-0.033|-0.070|-0.3%|
|QS7 recovery 1y trend_consistency60 none|2025-09-10|none|-0.017|-0.033|-0.054|-0.2%|
|QS28 1y d078 clv_volume20 H20 R20|2025-09-10|none|-0.025|-0.037|-0.053|-0.4%|
|QS3 momentum_risk120 H100 R20|2018-01-02|none|-0.023|-0.040|-0.050|-0.3%|
|QS28 1y d109 price_to_ma200 H20 R20|2025-09-10|none|-0.026|-0.042|-0.050|0.1%|
|QS28 1y d076 intraday_mom20 H10 R20|2025-09-10|none|-0.041|-0.058|-0.092|-0.2%|

## 近期切片诊断

以下沿用原回测持仓、资金和调仓相位，只用于发现时间适应性。与近期重新建仓的独立回测不同，不计入上面的达标数量。63/126交易日值样本较短。

|原始策略|窗口|Sharpe|区间收益|最大回撤|
|---|---|---:|---:|---:|
|QS6 prescreen lowvol20 H5 R10|recent_1y|0.482|4.9%|11.6%|
|QS6 prescreen lowvol20 H5 R10|2026_YTD|0.943|8.0%|11.6%|
|QS22 1y wq002_none H10 R20|recent_1y|0.987|25.7%|29.5%|
|QS22 1y wq002_none H10 R20|2026_YTD|0.190|0.8%|29.5%|
|QS20 1y lowvol20_instability_coverage H10 R20|recent_1y|0.426|4.1%|11.6%|
|QS20 1y lowvol20_instability_coverage H10 R20|2026_YTD|0.884|7.3%|11.6%|
|QS16 1y common_valid_amount_cash H20 R10|recent_1y|1.572|17.3%|4.8%|
|QS16 1y common_valid_amount_cash H20 R10|2026_YTD|2.462|21.3%|3.9%|
|QS8 1y lowamount20 industry H20 R10|recent_1y|0.950|24.5%|20.0%|
|QS8 1y lowamount20 industry H20 R10|2026_YTD|0.949|17.8%|20.0%|
|QS28 1y d079 amihud20 H10 R20|recent_1y|0.282|3.6%|33.1%|
|QS28 1y d079 amihud20 H10 R20|2026_YTD|0.693|13.5%|33.1%|
|QS1 lowvol20 H100 R20|recent_3y|0.537|24.2%|15.0%|
|QS1 lowvol20 H100 R20|recent_1y|0.122|0.7%|12.1%|
|QS1 lowvol20 H100 R20|2026_YTD|0.250|1.6%|12.0%|
|QS28 1y d002 rev5 5日反转 H10 R20|recent_1y|-1.161|-39.3%|56.7%|
|QS28 1y d002 rev5 5日反转 H10 R20|2026_YTD|-2.199|-46.9%|56.5%|
|QS2 rev5_lowvol20 H100 R5|recent_3y|-0.142|-16.9%|33.8%|
|QS2 rev5_lowvol20 H100 R5|recent_1y|-0.560|-10.2%|23.3%|
|QS2 rev5_lowvol20 H100 R5|2026_YTD|-0.760|-10.2%|23.3%|
|QS18 1y amount_cv60_low H20 R20|recent_1y|0.507|7.7%|19.6%|
|QS18 1y amount_cv60_low H20 R20|2026_YTD|0.755|9.3%|19.6%|
|QS10 3y lowamount LOO_breadth20 H20 R10|recent_3y|1.107|84.5%|16.3%|
|QS10 3y lowamount LOO_breadth20 H20 R10|recent_1y|-0.054|-1.3%|10.5%|
|QS10 3y lowamount LOO_breadth20 H20 R10|2026_YTD|-0.068|-1.1%|10.5%|
|QS28 1y d033 momentum_risk120 H10 R20|recent_1y|0.225|-1.6%|49.0%|
|QS28 1y d033 momentum_risk120 H10 R20|2026_YTD|-0.067|-12.6%|49.0%|
|QS18 1y amount_cv60_low H10 R20|recent_1y|0.084|-0.4%|25.6%|
|QS18 1y amount_cv60_low H10 R20|2026_YTD|0.119|0.1%|25.6%|
|QS13 1y wq006 H20 R10|recent_1y|0.872|17.5%|20.0%|
|QS13 1y wq006 H20 R10|2026_YTD|1.318|20.2%|20.0%|
|QS28 1y d013 illiquidity20 20日非流动性 H10 R20|recent_1y|0.282|3.6%|33.1%|
|QS28 1y d013 illiquidity20 20日非流动性 H10 R20|2026_YTD|0.693|13.5%|33.1%|
|QS28 1y d087 wq006_percentile90 H10 R20|recent_1y|1.052|27.1%|19.4%|
|QS28 1y d087 wq006_percentile90 H10 R20|2026_YTD|0.846|14.1%|19.4%|
|QS28 1y d013 illiquidity20 20日非流动性 H20 R20|recent_1y|0.012|-3.7%|30.4%|
|QS28 1y d013 illiquidity20 20日非流动性 H20 R20|2026_YTD|-0.041|-3.8%|30.4%|
|QS17 1y market_switch_neighbor H10 R4|recent_1y|1.105|19.1%|12.4%|
|QS17 1y market_switch_neighbor H10 R4|2026_YTD|1.169|14.9%|12.4%|
|QS13 1y overnight_mom20 H10 R20|recent_1y|0.152|-4.5%|37.7%|
|QS13 1y overnight_mom20 H10 R20|2026_YTD|-0.465|-20.2%|37.7%|
|QS28 1y d079 amihud20 H20 R20|recent_1y|0.012|-3.7%|30.4%|
|QS28 1y d079 amihud20 H20 R20|2026_YTD|-0.041|-3.8%|30.4%|
|QS1 rev5 H20 R1|recent_3y|-3.772|-89.2%|89.2%|
|QS1 rev5 H20 R1|recent_1y|-4.945|-13.5%|14.2%|
|QS1 rev5 H20 R1|2026_YTD|-6.375|-8.2%|8.5%|
|QS1 cfoa H100 R20|recent_3y|0.371|20.1%|23.7%|
|QS1 cfoa H100 R20|recent_1y|-0.264|-6.0%|17.5%|
|QS1 cfoa H100 R20|2026_YTD|0.028|-0.9%|17.5%|
|QS16 1y common_valid_amount_cash H10 R5|recent_1y|1.471|24.0%|6.7%|
|QS16 1y common_valid_amount_cash H10 R5|2026_YTD|1.861|21.7%|5.3%|
|QS10 3y lowamount LOO_breadth20 H10 R5|recent_3y|0.643|40.9%|16.4%|
|QS10 3y lowamount LOO_breadth20 H10 R5|recent_1y|-0.684|-9.3%|16.4%|
|QS10 3y lowamount LOO_breadth20 H10 R5|2026_YTD|-0.721|-6.4%|16.4%|
|QS13 1y overnight_mom20 H20 R20|recent_1y|-0.395|-23.4%|42.1%|
|QS13 1y overnight_mom20 H20 R20|2026_YTD|-0.747|-25.7%|42.1%|
|QS15 1y wq006_strong_breadth20 H20 R10|recent_1y|1.480|20.6%|7.5%|
|QS15 1y wq006_strong_breadth20 H20 R10|2026_YTD|2.121|24.5%|7.5%|
|QS20 1y lowvol20_instability_coverage H20 R20|recent_1y|0.015|-0.4%|14.2%|
|QS20 1y lowvol20_instability_coverage H20 R20|2026_YTD|0.447|3.2%|13.4%|
|QS20 1y historical_vol_instability20_60_low H20 R20|recent_1y|0.538|11.2%|27.8%|
|QS20 1y historical_vol_instability20_60_low H20 R20|2026_YTD|0.744|12.8%|27.8%|
|QS8 1y downside20 industry H10 R10|recent_1y|0.870|16.3%|12.2%|
|QS8 1y downside20 industry H10 R10|2026_YTD|1.705|25.5%|7.5%|
|QS26 1y momentum120_skip20 H20 R20|recent_1y|-0.162|-17.1%|46.7%|
|QS26 1y momentum120_skip20 H20 R20|2026_YTD|-0.722|-29.2%|46.7%|
|QS17 1y market_switch_neighbor H20 R11|recent_1y|0.223|2.1%|12.4%|
|QS17 1y market_switch_neighbor H20 R11|2026_YTD|0.468|4.3%|12.4%|
|QS1 lowamount20 H100 R20|recent_3y|0.524|37.8%|34.0%|
|QS1 lowamount20 H100 R20|recent_1y|-0.042|-2.6%|23.4%|
|QS1 lowamount20 H100 R20|2026_YTD|-0.152|-3.6%|23.4%|
|QS16 1y market_switch_amount_lowvol H10 R5|recent_1y|1.525|29.1%|8.4%|
|QS16 1y market_switch_amount_lowvol H10 R5|2026_YTD|2.026|28.6%|8.4%|
|QS20 1y historical_vol_instability20_60_low H10 R20|recent_1y|0.288|4.0%|32.4%|
|QS20 1y historical_vol_instability20_60_low H10 R20|2026_YTD|0.380|4.7%|32.4%|
|QS10 1y lowamount LOO_breadth20 H10 R5|recent_1y|1.471|24.0%|6.7%|
|QS10 1y lowamount LOO_breadth20 H10 R5|2026_YTD|1.861|21.7%|5.3%|
|QS16 3y market_switch_amount_lowvol H20 R10|recent_3y|1.209|109.1%|16.5%|
|QS16 3y market_switch_amount_lowvol H20 R10|recent_1y|0.333|3.9%|16.5%|
|QS16 3y market_switch_amount_lowvol H20 R10|2026_YTD|0.604|6.0%|16.5%|
|QS17 1y market_switch_neighbor H10 R6|recent_1y|0.588|8.0%|12.1%|
|QS17 1y market_switch_neighbor H10 R6|2026_YTD|0.847|9.2%|12.1%|
|QS10 1y lowamount LOO_breadth20 H20 R10|recent_1y|1.572|17.3%|4.8%|
|QS10 1y lowamount LOO_breadth20 H20 R10|2026_YTD|2.462|21.3%|3.9%|
|QS1 intraday5 H100 R5|recent_3y|0.057|-12.7%|41.9%|
|QS1 intraday5 H100 R5|recent_1y|-0.292|-14.2%|41.1%|
|QS1 intraday5 H100 R5|2026_YTD|-0.784|-21.0%|41.1%|
|QS16 3y market_switch_amount_lowvol H10 R5|recent_3y|0.640|44.9%|25.1%|
|QS16 3y market_switch_amount_lowvol H10 R5|recent_1y|-0.141|-3.5%|20.7%|
|QS16 3y market_switch_amount_lowvol H10 R5|2026_YTD|0.068|-0.2%|20.7%|
|QS6 prescreen lowamount20 H10 R10|recent_1y|0.759|15.0%|12.3%|
|QS6 prescreen lowamount20 H10 R10|2026_YTD|0.686|9.5%|12.3%|
|QS17 1y market_switch_neighbor H20 R9|recent_1y|0.233|2.3%|18.5%|
|QS17 1y market_switch_neighbor H20 R9|2026_YTD|0.633|6.5%|18.5%|
|QS16 1y market_switch_amount_lowvol H20 R10|recent_1y|1.387|20.3%|8.9%|
|QS16 1y market_switch_amount_lowvol H20 R10|2026_YTD|1.911|21.9%|8.9%|

## 可复核证据

- `submissions/`：每次提交的完整公式、日期、参数、request_id 与 batch_id。
- `batches/`：最近一次读取的服务端状态；失败与未完成项保留。
- `results/`：MCP 原始 Run / Factor / Strategy Summary。
- `observations/`：完整分页净值数据；`nav-audit.csv` 为独立 Sharpe / 回撤复算。
- `periods.csv`：同一策略路径的年度与时间段表现，2026 年为截至最新日。
- `recent-path-diagnostics.csv`：近3年/1年/YTD与63/126/252交易日路径切片。
- `regime-plan.json`：状态切换公式、预先选定窗口和适用边界。
- `research-contract.md`：当前模型假设、代码和原始文献。

独立净值复算：50 个策略。

## 仍在运行
