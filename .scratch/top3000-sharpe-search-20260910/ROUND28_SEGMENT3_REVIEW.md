# QS28 第三段独立证据复核

**指定的准入恢复、执行状态、路径相等和净值复算均通过；发现并推动修正了一处“汇总相同”的范围歧义，修正后已再次核实。** 本次不依赖父代理比较表来证明相等，而是直接读取原始提交、Run、Result 与逐日观察，另写内联 Python 复算。未调用 MCP、导出行情、运行或导入父代理审计脚本，未改产品、冻结计划、父报告或前一份历史清单复核。

初次证据读取完成于 `2026-09-10T02:41:32.582444+00:00`；报告修正复查于 `2026-09-10T02:46:53.754746+00:00`。本次检查的 236 份源文件初始 SHA-256、全部结构比较结果、5 条路径的独立 Decimal 结果和发现状态保存在 [round28-segment3-review.json](round28-segment3-review.json)。其中 202 份提交用于核对 d080/d091 的全部已保存提交出现。

## 发现与修正

**F1：d089/d069 的“汇总相同”需要指明比较层级，现已修正。** [原诊断报告](ROUND28_SEGMENT3_DIAGNOSTICS.md) 第26行原文写“H10/H20汇总分别与此前d069相同”。独立比较发现，两对同 N 账户的完整 `summary.metrics` 确实分别相同，但 `factor.factor` 每对有 **36 个叶子数值不同**。这不是策略指标计算错误；笼统的“汇总”容易被读成因子与账户结果都相同。

| 20日因子指标 | d069 | d089 |
|---|---:|---:|
| Rank IC mean | 0.03232884168309928 | 0.03231406706069523 |
| q5 | −0.0016365332609079857 | −0.0016486780647237099 |

直接证据：H10 [d069](results/run_4e1fc19bf405468da283.json) / [d089](results/run_9fd7fd8f7d2a45c29e5f.json)；H20 [d069](results/run_6e0869929d0741cc8f4b.json) / [d089](results/run_1b9a96a9c42b4d19803c.json)。初版报告 SHA-256 为 `1dc9c791754f76aef65184fdaa36038c0e27f33c9939bf9fc2e3357a67f239b5`。

主代理已将文字收窄为“策略metrics……相同，但因子摘要不同”，列出 d089、d069 顺序对应的正确数值，并明确不能扩展为因子或所有账户状态等价。本代理重新读取第26行，确认文字、方向和数值正确；修正版 SHA-256 为 `327993b8bcb2f66108b4871f10ed495814a7eb4270ae90fc105f14ea2118a902`。全部其他已检查证据文件在修正复查时保持原哈希。没有未解决的数值或输入错误。

## d080：批次准入拒绝后的原样单任务恢复

[被拒绝的原始批次](submissions/r28-d080-year.json) 返回 `outcome: rejected`，错误码 `RESEARCH_BATCH_EXCEEDS_WORKER_CAPACITY`，响应中没有 Run ID 或 Batch ID。[准入审查记录](round28-admission-resolutions.json) 中的拒绝文件哈希与实际文件吻合，且审查时间位于原拒绝和 H10 提交之间。现有保存证据支持“没有接受成回测任务”；本次未读服务端数据库或日志，不能把无句柄响应扩展为独立证明服务端不存在任何孤立记录。

批次的 `alpha`、共同条件和各策略 H/R 分别展开后，与两份单任务的完整作者输入一致；每份单任务又与 Result 的 Run.input/provenance.authoring_input 一致。固定公式为 `rank(close / ts_max(close, 252))`，保持 TOP3000、none、2025-09-10 至 2026-09-09、R20、H10/H20。冻结编译信息的 lookback 为251，两份 Run 的总预热和完成预热都为251，均完成242个研究日，没有缩短历史或股票池。数据代次、基准快照及除 H 外的完整执行契约符合冻结计划，原生本金均为1000万元。

| 事件 | UTC 时间 |
|---|---|
| 批次被拒绝的提交时间 | 2026-09-10 02:16:23.316 |
| H10 单任务提交 | 2026-09-10T02:23:23.037Z |
| H10 成功完成 | 2026-09-10T02:25:56.632023Z |
| H20 单任务提交 | 2026-09-10T02:27:15.929Z |
| H20 成功完成 | 2026-09-10T02:29:46.758242Z |

H20 在 H10 成功完成 **79.296977 秒后**才提交；其服务端创建时间也晚于 H10 完成。两次接受响应都不是 replay。原式全年账户仅有被拒绝批次和随后 H10/H20 两个已接受单任务，没有改成其他 N/R。证据：[H10 提交](submissions/r28-d080-year-h10.json) / [Result](results/run_eac1cfcf87f94f2ab955.json)；[H20 提交](submissions/r28-d080-year-h20.json) / [Result](results/run_ff80a9845bb3416e836c.json)。

| N | 原生 Sharpe | 原生累计净收益 | 原生最大回撤 |
|---|---:|---:|---:|
| 10 | -0.731668605538699 | -30.44529881% | 45.02525435% |
| 20 | -0.218257595599874 | -13.38388799% | 32.16178540% |

这些值与诊断报告的显示精度一致；准入恢复成功，不代表两个经济结果达标。

## d091：首次账户运行失败，H20 按规则未提交

对本次枚举的202份已保存原始提交按完整字面公式查找，d091 只有此前 [r18 因子评估](submissions/r18-factors-1.json) 与本轮 [H10 策略单任务](submissions/r28-d091-year-h10.json)。因此“首次”指首次实际账户尝试，不是首次因子研究；没有对应 H20 策略提交，也没有任何已保存 H20 接受句柄。

[原始失败 Run](runs/run_7c21234da53b49f5b4a5.json) 的输入与单任务和冻结 d091 字面定义一致；其为效率**水平**及252日有效历史对照，与 d090 的效率变化原式、d103 的 delta 写法不同。Run 为 `failed`，252/252 预热，研究4/242，最后研究日2025-09-15，无 Result 区段，本地也无完整 Result 文件。

失败原因只有 `Research execution exceeded its resource limit.`，不能据此断言 OOM、内存峰值或另一具体资源原因。本次没有检查进程退出码、主机监控或系统日志。H20 未提交属于执行未解决，不能记为一次实际失败或经济负例，也不能把 d091 H10 称为原效率任务的未改输入重试。

## d013/d079：两对公开路径确实相同

分别读取原式与正比例变体的4份 Result 和4份观察档案。每份有242个唯一、按日期排序的点，首尾为2025-09-10和2026-09-09，`pages: 5`、`next_cursor: null`；点数与 Result 的完整研究日数一致。每对按日期逐行比较全部10个字段，保留 JSON 数字/字符串类型，合计 **4840 次字段配对比较**，没有差异。并核实因子内容及其除 Run ID 外的 metadata、完整策略 metrics 分别相同；数据、基准与执行契约相同。原作者输入仅公式/hypothesis 不同。

10个字段是 `session`、`gross_nav`、`net_nav`、`net_cash`、`transaction_cost_cny`、`holdings_count`、`maximum_single_name_weight`、`upper_limit_buy_rejections`、`lower_limit_sell_rejections`、`suspension_rejections`。它们没有证券代码或逐笔交易身份，因此不能推出已独立验证每日证券名单完全相同。

| N | 原式 / 变体 Result | 公开观察 | 独立 Sharpe | 净收益 | 最大回撤 |
|---|---|---|---:|---:|---:|
| 10 | [原式](results/run_3edc7b50d57d4330aefd.json) / [变体](results/run_1c69e0e8caad492598f6.json) | [原式242点](observations/run_3edc7b50d57d4330aefd.json) / [变体242点](observations/run_1c69e0e8caad492598f6.json) | 0.2822179147561375 | 3.62383006% | 33.10084011% |
| 20 | [原式](results/run_506f5dc808804c9582eb.json) / [变体](results/run_692e5affac7c42e782c7.json) | [原式242点](observations/run_506f5dc808804c9582eb.json) / [变体242点](observations/run_692e5affac7c42e782c7.json) | 0.0123457195220545 | -3.67212672% | 30.40384777% |

独立复算使用50位 Decimal。对242点净值只生成241个相邻收益 `NAV[t]/NAV[t-1]-1`，无额外起始零收益；以样本标准差（分母 n−1）、零无风险利率和 √252 年化计算 Sharpe，逐日运行峰值计算回撤，末/初净值减一计算收益，并逐行精确求和已记录费用。所有四条路径的独立 Decimal 数字、峰谷日期和父代理保存的复算结果逐项一致。

转换到原生汇总所用 float 后，Sharpe 最大差为 `5.551115123125783e-17`，回撤、收益、费用的 float 差均为0；这与 [Scale Proof](ROUND28_SCALE_PROOF.md) 的“数值转换后精确相同”措辞一致。它不是高精度实数与已舍入 JSON 小数精确相等：例如 H10 回撤的 Decimal 值与汇总最短小数字符串仍差 `3.30877348845998588639202757177341e-18`。JSON同时保存两种比较口径，避免把 float 的0差读成不经舍入的代数证明。

本证据验证指定数据和执行契约的公开路径；未独立重建源行情，未重新获取原始分页响应或外部交易日历，也未证明所有浮点输入下通用等价。费用是对已记录费用求和，没有从成交重新计算佣金。四个账户都是1000万元原生账户，不是10万元回放。外部 V-Lab 方法引文不在本次仅限已保存语义结果的核对范围。

## d088：同 N、不同 R 的比较成立

两对完整 Run.input、provenance.authoring_input 仅 `rebalance_every_sessions` 不同；从 execution.calculation_contracts.strategy 移除该项后完整执行契约一致，数据、基准、因子内容与其其他 metadata 均相同。原生条件仍为TOP3000、none、同一年和1000万元。以下值直接从四个原始 Result 提取，逐值匹配父代理比较 JSON；诊断报告中的四舍五入也正确。

| N | R | Result | 净收益 | Sharpe | 最大回撤 | 费用/初始本金 | 年化换手 |
|---|---:|---|---:|---:|---:|---:|---:|
| 10 | 5 | [run_c9871f3c547147bc80a1](results/run_c9871f3c547147bc80a1.json) | 29.0849% | 1.525261623408 | 8.3884% | 4.3241% | 36.03889722 |
| 10 | 20 | [run_47ea70c439c04218a2be](results/run_47ea70c439c04218a2be.json) | 3.7165% | 0.306652789355 | 12.9274% | 1.1851% | 11.61163369 |
| 20 | 10 | [run_fe6c5b6b5f2d4a2395da](results/run_fe6c5b6b5f2d4a2395da.json) | 20.2751% | 1.386783830793 | 8.8707% | 2.1393% | 19.14514004 |
| 20 | 20 | [run_95532804370941fd8ea7](results/run_95532804370941fd8ea7.json) | 9.4446% | 0.685244611525 | 14.7872% | 1.1830% | 11.34714061 |

这说明已测历史里 R20 的费用与换手更低，而本例收益风险表现也变差；没有证明最优 R、未来稳定性或特定切换日的因果贡献。输入合同是按 R 个研究 session 调仓，不支持把 R20 账户称为“每日即时切换”。本次没有额外验证 d088 的逐笔成交或完整逐日持仓身份。

## d087 H10：独立复算与措辞边界

对 [原始 Result](results/run_4fa825f36c2c4dd38254.json) 与 [242点原始观察](observations/run_4fa825f36c2c4dd38254.json) 按上述独立方法复算：

| 项目 | 独立结果 |
|---|---:|
| Sharpe | `1.0522503829402381358527405922316985957894206141432` |
| 最大回撤 | 19.4039578878% |
| 累计净收益 | 27.1053882976% |
| 费用合计 | 152031.2154740 CNY |
| 最大回撤峰 / 谷 | 2026-05-25 / 2026-07-21 |

报告中的 Sharpe1.0522503829402381、回撤19.40395789%、净收益27.10538830%、费用152031.215474及峰谷日期都符合对应显示精度。转换到汇总 float 后四项差为0；仍然只是对公开净值/费用与摘要的一致性验证，不是独立复核行情或真实券商成交。

还直接核对了报告中的 d085 H20 与 d087 H20 原生指标：d085 H20 净收益15.85384512%、Sharpe1.035426695637、回撤8.46882856%、平均现金42.22239700%、平均持仓11.57024793只；d087 H20 净收益20.91278200%、Sharpe0.919023077202、回撤18.43755441%。均与报告显示精度一致。原始证据：[d085 H20](results/run_8ed2f120b90c4e7a86c0.json)、[d087 H20](results/run_ee66760001be4d3994bc.json)。

两份被审文字均明确限制为原生1000万元、已研究历史，并否认每日证券身份或真实券商交易已经独立验证；未发现将其误称为10万元账户结果、未见样本外证明或“证券名单全相同”。d089/d069 的摘要范围歧义已按 F1 修正并复查。

## 文件哈希与审查边界

全部 236 份源文件的初始哈希见证据 JSON 的 `file_sha256`。修正复查只发现诊断报告发生上述一项变更，其余已检查文件哈希保持一致。主要文档及原始准入/失败证据如下：

| 文件 | 审查时 SHA-256 |
|---|---|
| [round28-plan.json](round28-plan.json) | `8f1ac92d21efb746cbbe58aa890127bae91d42b208c9c1d9c2c90a49d4370b4c` |
| [round28-admission-resolutions.json](round28-admission-resolutions.json) | `2e485ef6c8e906a0e514356e8ab1ce1e1994c77d9fe7d95f122cd805ace7b5c4` |
| [submissions/r28-d080-year.json](submissions/r28-d080-year.json) | `db7464dd3b17c3e080cac1c307a6619d8b90ac89e11cc031ce0dc6915afddb47` |
| [submissions/r28-d080-year-h10.json](submissions/r28-d080-year-h10.json) | `c79111d3273b06144eaf4e316e66bba56b867f1c3c50798d42906383777d7018` |
| [submissions/r28-d080-year-h20.json](submissions/r28-d080-year-h20.json) | `0ef6c3f4fef9caffbb5ea538a3a6f2b965cd24d924372b1bb35539528d31eb68` |
| [submissions/r28-d091-year-h10.json](submissions/r28-d091-year-h10.json) | `559419f6e23b3e8d36562a78ef731cd5f70001f63283168f617acd59e27cedfc` |
| [runs/run_7c21234da53b49f5b4a5.json](runs/run_7c21234da53b49f5b4a5.json) | `a302cba3e4d251ec092ae341b20470d8de6f282bc59a132ecfec22a437c80527` |
| [ROUND28_SCALE_PROOF.md](ROUND28_SCALE_PROOF.md) | `fca2cc7613a6dcb4e93f782303f2578956e46f3c2b827522d84bdd5fd614bdac` |
| [ROUND28_SEGMENT3_DIAGNOSTICS.md](ROUND28_SEGMENT3_DIAGNOSTICS.md) | `327993b8bcb2f66108b4871f10ed495814a7eb4270ae90fc105f14ea2118a902` |
| [round28-amihud-scale-comparison.json](round28-amihud-scale-comparison.json) | `3d5a446f4a08bee3926d17a7a1a885ba4b69259d6416e941f4891fea9e4cde17` |
| [round28-market-switch-interval-comparison.json](round28-market-switch-interval-comparison.json) | `789232957ae4187688e694877421523dfac2530dbb763b6fa7771ec7ad9bcf85` |
| [round28-nav-audits.json](round28-nav-audits.json) | `59b2ca77657bfbcc18adcac611fd940ad3857903492c16f711a97cbb29302f70` |

输入/数据/契约检查依据已保存 Result 的声明；未独立确认服务端数据字节或内核实现。负面的“没有 H20 提交”限定在本次列出的202份已保存提交范围；后续执行新增文件不属于这个快照。没有重开旧实验、生成新参数或把运行失败记为经济结果。本次仅写本报告与 [round28-segment3-review.json](round28-segment3-review.json)；前一份历史清单复核未改写。
