# QS28 冻结清单独立复核

**结论：在第二段检查点范围内，未发现定义遗漏、来源顺序错误、错误复用或状态计数错误。** 从原始提交独立恢复出的结果是 109 个定义、96 条字面公式和 218 个固定账户案例；71 个复用案例逐项匹配。检查点的 160 个完整案例、50 个未提交案例、8 个执行未解决案例能够由原始提交与 Run/Result 重建。这里的 8 个未解决案例是 **5 次实际资源失败 + 3 个按停止规则未提交**，没有可据此判断收益的完整账户结果。

检查范围固定到 **2026-09-10 02:10:47.104151 UTC**（首尔时间 11:10:47.104151），即 [第二段检查点](round28-segment2-checkpoint-verification.json)。主代理随后提交的 QS28 任务按 `submitted_at` 排除；本报告不是当前服务端任务总数。独立读取完成时间为 `2026-09-10T02:21:42.136795+00:00`。

冻结 [round28-plan.json](round28-plan.json) 的 SHA-256 为 `8f1ac92d21efb746cbbe58aa890127bae91d42b208c9c1d9c2c90a49d4370b4c`；129 份历史提交逐文件重新计算 SHA-256，全部与冻结清单一致。审查用独立内联 Python，经 `uv run --project apps/core --no-sync --offline python` 执行；没有运行、导入或读取现有 render/analyze/状态审计脚本来产生结论。[逐项证据 JSON](round28-inventory-review.json) 保存了全部来源、复用检查项、结果文件哈希、逐案例状态及排除的后续提交。

## 原始清单恢复

只从 `source_manifest` 指向的原始 `input` 提取定义：因子批次逐个取 `factors`，策略批次取 `alpha`，单任务取顶层 `formula`；连同原始 `neutralization` 和 `universe` 构成身份。公式不去空格、不改写、不按摘要或收益合并。随后按提交时间、文件名、输入项的零起始序号排序，以首次出现依次赋予 d001—d109。每个定义的所有来源、item key、序号、接受/拒绝结果及原始日期均与冻结计划逐项比较。

| 独立恢复项目 | 结果 |
|---|---:|
| 历史提交文件 | 129 |
| 策略批次 / 策略单任务 / 因子批次 | 63 / 41 / 25 |
| 提交接受 / 提交拒绝 | 125 / 4 |
| 原始定义出现次数 | 224 |
| 字面公式 + neutralization + universe 定义 | 109 |
| 不同字面公式 | 96 |
| none 定义 / industry 定义 | 96 / 13 |
| H10 R20 与 H20 R20 固定案例 | 218 |
| 定义顺序、全部来源顺序、案例网格差异 | 0 |

拒绝的提交也保留在这个历史清单中。例如 [r7-new-factors-industry.json](submissions/r7-new-factors-industry.json) 中 d062/d063 的首次来源早于后续拆分接受的提交；不能把“首次成功”替代“首次提交”。全部 224 次出现和 109 个定义映射见证据 JSON 的 `source_files`、`reconstructed_definitions`。

## 71 个复用案例

从 129 份原始提交中，沿接受响应的单任务 Run ID 或批次 item key → Run ID 链，恢复出 **201 个原始策略 Run ID**。对全部原始策略结果检索精确可复用条件，得到 **71 个案例、71 个 Run ID**，与计划的复用集合完全相同；没有额外可复用案例被漏记，也没有把摘要一致当作公式等价。批次链示例：[rev20 原始提交](submissions/r26-strategy-rev20.json) → [对应批次](batches/batch_8386c807f1a34e9badb4.json) → [H10 Result](results/run_44b9548bba4449559899.json)。

每个复用案例均核对：完整字面公式、none/industry、TOP3000、2025-09-10 至 2026-09-09、H10/H20、R20；原始请求的 hypothesis 与其余作者输入；Result 内 Run.input 与 provenance.authoring_input；成功状态、完整 242 个研究 session、截止日、Result 各区段 Run ID；数据身份、完整执行契约、基准快照、本金声明、Result schema，以及完成时间早于计划冻结时间。未将名字或展示摘要当作输入身份。

| 复用的共同声明 | 核实值 |
|---|---|
| 数据代次 | `17f5694f6a9d47b915ffde326928b919a55181e75a4908cb661934850ac8c983` |
| data_through_session / financial readiness | `2026-09-09` / `ready` |
| 基准快照 | `d81a7d1c1f12023c161f68a52f84d0a6d070ca17ae69cc027ba4fa7b9cf5d3f5` |
| 语义版本 | `kernel-v5` / `factor-v1` / `strategy-v2` |
| 数值契约 | `thesistrace-numeric-v1` |
| 策略和执行 | `long_only_top_n_equal_weight` / `next_open_full_fill` |
| 本金 / 无风险利率 | 10,000,000 CNY / 0 |
| 佣金 / 最低佣金 | 0.0003 / 5 CNY |
| 过户费 / 卖出印花税 | 0.00001 / 0.0005 |

71 个 Result 都保存了完整 Run 输入和 provenance；其中 65 个另有单独的 `runs/<id>.json` 缓存，另行交叉比较也全部一致。以下六个案例没有单独的 Run 缓存：`d010-h10r20`, `d010-h20r20`, `d014-h10r20`, `d014-h20r20`, `d042-h10r20`, `d042-h20r20`。这些案例依据 Result 内完整 Run 与原始请求核实，不声称另做了一次独立服务端读取。

逐个复用证据如下；“输入及契约通过”包括上述检查，不代表独立复算收益。

| 固定案例 | 原始提交 | 完整 Result | 输入及契约 |
|---|---|---|---|
| `d003-h10r20` | [r26-strategy-rev20.json](submissions/r26-strategy-rev20.json) | [run_44b9548bba4449559899](results/run_44b9548bba4449559899.json) | 通过 |
| `d003-h20r20` | [r26-strategy-rev20.json](submissions/r26-strategy-rev20.json) | [run_47cdfd9fa3b147ff8ae7](results/run_47cdfd9fa3b147ff8ae7.json) | 通过 |
| `d006-h10r20` | [r26-strategy-intraday5.json](submissions/r26-strategy-intraday5.json) | [run_b22b9be9d274427ca2d7](results/run_b22b9be9d274427ca2d7.json) | 通过 |
| `d006-h20r20` | [r26-strategy-intraday5.json](submissions/r26-strategy-intraday5.json) | [run_fe6db5c8d9264a54a1fe](results/run_fe6db5c8d9264a54a1fe.json) | 通过 |
| `d008-h10r20` | [r26-strategy-close_location5.json](submissions/r26-strategy-close_location5.json) | [run_2f8ab0fceb9b4055a893](results/run_2f8ab0fceb9b4055a893.json) | 通过 |
| `d008-h20r20` | [r26-strategy-close_location5.json](submissions/r26-strategy-close_location5.json) | [run_d98414ebc0ac401298c1](results/run_d98414ebc0ac401298c1.json) | 通过 |
| `d009-h10r20` | [r26-strategy-momentum120_skip20.json](submissions/r26-strategy-momentum120_skip20.json) | [run_adcd6e7d9237470b90de](results/run_adcd6e7d9237470b90de.json) | 通过 |
| `d009-h20r20` | [r26-strategy-momentum120_skip20.json](submissions/r26-strategy-momentum120_skip20.json) | [run_a64d9045d7314c39bab4](results/run_a64d9045d7314c39bab4.json) | 通过 |
| `d010-h10r20` | [r6-small-account-prescreen-lowvol20.json](submissions/r6-small-account-prescreen-lowvol20.json) | [run_1a6ab615115040618a0a](results/run_1a6ab615115040618a0a.json) | 通过 |
| `d010-h20r20` | [r6-small-account-prescreen-lowvol20.json](submissions/r6-small-account-prescreen-lowvol20.json) | [run_ab196ccc0e1d41a8815b](results/run_ab196ccc0e1d41a8815b.json) | 通过 |
| `d014-h10r20` | [r6-small-account-prescreen-lowamount20.json](submissions/r6-small-account-prescreen-lowamount20.json) | [run_434dcae08cc0483284ed](results/run_434dcae08cc0483284ed.json) | 通过 |
| `d014-h20r20` | [r6-small-account-prescreen-lowamount20.json](submissions/r6-small-account-prescreen-lowamount20.json) | [run_3690e87a47484b0fb3b4](results/run_3690e87a47484b0fb3b4.json) | 通过 |
| `d017-h10r20` | [r26-strategy-roa.json](submissions/r26-strategy-roa.json) | [run_041d1b65491040b7b871](results/run_041d1b65491040b7b871.json) | 通过 |
| `d017-h20r20` | [r26-strategy-roa.json](submissions/r26-strategy-roa.json) | [run_546191d4caf44a40a8e9](results/run_546191d4caf44a40a8e9.json) | 通过 |
| `d038-h10r20` | [r22-strategy-wq003_none.json](submissions/r22-strategy-wq003_none.json) | [run_1fef61cdcb8b47d58aae](results/run_1fef61cdcb8b47d58aae.json) | 通过 |
| `d038-h20r20` | [r22-strategy-wq003_none.json](submissions/r22-strategy-wq003_none.json) | [run_31aa367b51854a9fbd52](results/run_31aa367b51854a9fbd52.json) | 通过 |
| `d040-h10r20` | [r22-strategy-wq002_none.json](submissions/r22-strategy-wq002_none.json) | [run_0b392f7f468c4823b6b0](results/run_0b392f7f468c4823b6b0.json) | 通过 |
| `d040-h20r20` | [r22-strategy-wq002_none.json](submissions/r22-strategy-wq002_none.json) | [run_521b1c390bc9431fbbef](results/run_521b1c390bc9431fbbef.json) | 通过 |
| `d041-h10r20` | [r19-strategy-wq013_none.json](submissions/r19-strategy-wq013_none.json) | [run_eddb56451afe415c8d7c](results/run_eddb56451afe415c8d7c.json) | 通过 |
| `d041-h20r20` | [r19-strategy-wq013_none.json](submissions/r19-strategy-wq013_none.json) | [run_b04fee5ce5314961aef0](results/run_b04fee5ce5314961aef0.json) | 通过 |
| `d042-h10r20` | [r6-small-account-prescreen-wq016.json](submissions/r6-small-account-prescreen-wq016.json) | [run_66bf715974274a0eb53c](results/run_66bf715974274a0eb53c.json) | 通过 |
| `d042-h20r20` | [r6-small-account-prescreen-wq016.json](submissions/r6-small-account-prescreen-wq016.json) | [run_47a20c9e4c92499baef8](results/run_47a20c9e4c92499baef8.json) | 通过 |
| `d045-h10r20` | [r19-strategy-wq012_ret_none.json](submissions/r19-strategy-wq012_ret_none.json) | [run_f135fd937953416f9ccd](results/run_f135fd937953416f9ccd.json) | 通过 |
| `d045-h20r20` | [r19-strategy-wq012_ret_none.json](submissions/r19-strategy-wq012_ret_none.json) | [run_08ae57b1b5ca445ab584](results/run_08ae57b1b5ca445ab584.json) | 通过 |
| `d047-h10r20` | [r19-strategy-lowmax20_none.json](submissions/r19-strategy-lowmax20_none.json) | [run_8f7cab7e3b72467ca770](results/run_8f7cab7e3b72467ca770.json) | 通过 |
| `d047-h20r20` | [r19-strategy-lowmax20_none.json](submissions/r19-strategy-lowmax20_none.json) | [run_d164a8db96914d78b5e8](results/run_d164a8db96914d78b5e8.json) | 通过 |
| `d048-h10r20` | [r19-strategy-downside20_none.json](submissions/r19-strategy-downside20_none.json) | [run_285c38e87c074b839ec3](results/run_285c38e87c074b839ec3.json) | 通过 |
| `d048-h20r20` | [r19-strategy-downside20_none.json](submissions/r19-strategy-downside20_none.json) | [run_6f3a11540849479185aa](results/run_6f3a11540849479185aa.json) | 通过 |
| `d049-h10r20` | [r22-strategy-quality_defensive_none.json](submissions/r22-strategy-quality_defensive_none.json) | [run_fd375d4b19d042a7826a](results/run_fd375d4b19d042a7826a.json) | 通过 |
| `d049-h20r20` | [r22-strategy-quality_defensive_none.json](submissions/r22-strategy-quality_defensive_none.json) | [run_ef1ee9e6f70941f58f19](results/run_ef1ee9e6f70941f58f19.json) | 通过 |
| `d051-h10r20` | [r8-profit-margin-none-small.json](submissions/r8-profit-margin-none-small.json) | [run_4b89a4d019b1444fa422](results/run_4b89a4d019b1444fa422.json) | 通过 |
| `d051-h20r20` | [r8-profit-margin-none-small.json](submissions/r8-profit-margin-none-small.json) | [run_cd3bf5681ecb4d499c0d](results/run_cd3bf5681ecb4d499c0d.json) | 通过 |
| `d053-h10r20` | [r19-strategy-revenue_growth252_none-single-h10.json](submissions/r19-strategy-revenue_growth252_none-single-h10.json) | [run_b4709084b1c148d5bda1](results/run_b4709084b1c148d5bda1.json) | 通过 |
| `d053-h20r20` | [r19-strategy-revenue_growth252_none-single-h20.json](submissions/r19-strategy-revenue_growth252_none-single-h20.json) | [run_0292b71688a64b9891e2](results/run_0292b71688a64b9891e2.json) | 通过 |
| `d055-h10r20` | [r19-strategy-positive_roe_none.json](submissions/r19-strategy-positive_roe_none.json) | [run_d44a5acfe66a42639bef](results/run_d44a5acfe66a42639bef.json) | 通过 |
| `d055-h20r20` | [r19-strategy-positive_roe_none.json](submissions/r19-strategy-positive_roe_none.json) | [run_c465a7be404b436e85fa](results/run_c465a7be404b436e85fa.json) | 通过 |
| `d056-h10r20` | [r22-strategy-volume_dry_lowvol_none.json](submissions/r22-strategy-volume_dry_lowvol_none.json) | [run_7f7cb4b361c24e72836d](results/run_7f7cb4b361c24e72836d.json) | 通过 |
| `d056-h20r20` | [r22-strategy-volume_dry_lowvol_none.json](submissions/r22-strategy-volume_dry_lowvol_none.json) | [run_1680945deddc4abc85da](results/run_1680945deddc4abc85da.json) | 通过 |
| `d057-h10r20` | [r22-strategy-lowmax20_industry.json](submissions/r22-strategy-lowmax20_industry.json) | [run_63393a4c245040f4bfd2](results/run_63393a4c245040f4bfd2.json) | 通过 |
| `d057-h20r20` | [r22-strategy-lowmax20_industry.json](submissions/r22-strategy-lowmax20_industry.json) | [run_d6b632ee5ee143269c38](results/run_d6b632ee5ee143269c38.json) | 通过 |
| `d058-h10r20` | [r8-downside20-industry-small.json](submissions/r8-downside20-industry-small.json) | [run_0eaf60be30514ab89724](results/run_0eaf60be30514ab89724.json) | 通过 |
| `d058-h20r20` | [r8-downside20-industry-small.json](submissions/r8-downside20-industry-small.json) | [run_f7ef0da8484846c78805](results/run_f7ef0da8484846c78805.json) | 通过 |
| `d059-h10r20` | [r19-strategy-quality_defensive_industry.json](submissions/r19-strategy-quality_defensive_industry.json) | [run_555dda7f88d744d998dd](results/run_555dda7f88d744d998dd.json) | 通过 |
| `d059-h20r20` | [r19-strategy-quality_defensive_industry.json](submissions/r19-strategy-quality_defensive_industry.json) | [run_264c7ea0243d454492aa](results/run_264c7ea0243d454492aa.json) | 通过 |
| `d060-h10r20` | [r22-strategy-cash_margin_industry.json](submissions/r22-strategy-cash_margin_industry.json) | [run_8327dd40cdf54721b6a2](results/run_8327dd40cdf54721b6a2.json) | 通过 |
| `d060-h20r20` | [r22-strategy-cash_margin_industry.json](submissions/r22-strategy-cash_margin_industry.json) | [run_1d82f358d6504066b9b8](results/run_1d82f358d6504066b9b8.json) | 通过 |
| `d061-h10r20` | [r22-strategy-profit_margin_industry.json](submissions/r22-strategy-profit_margin_industry.json) | [run_6fb4b3a3dc80443a94a7](results/run_6fb4b3a3dc80443a94a7.json) | 通过 |
| `d061-h20r20` | [r22-strategy-profit_margin_industry.json](submissions/r22-strategy-profit_margin_industry.json) | [run_1e4fb5bcda304fcfaaf5](results/run_1e4fb5bcda304fcfaaf5.json) | 通过 |
| `d063-h20r20` | [r9-revenue-growth-single-h20.json](submissions/r9-revenue-growth-single-h20.json) | [run_5f316b8f337941748319](results/run_5f316b8f337941748319.json) | 通过 |
| `d065-h10r20` | [r22-strategy-positive_roe_industry.json](submissions/r22-strategy-positive_roe_industry.json) | [run_a3b6fad0acd04f869b6b](results/run_a3b6fad0acd04f869b6b.json) | 通过 |
| `d065-h20r20` | [r22-strategy-positive_roe_industry.json](submissions/r22-strategy-positive_roe_industry.json) | [run_172ba011cc4e4f47941d](results/run_172ba011cc4e4f47941d.json) | 通过 |
| `d067-h10r20` | [r8-lowamount20-industry-small.json](submissions/r8-lowamount20-industry-small.json) | [run_bb819378d121406caf5b](results/run_bb819378d121406caf5b.json) | 通过 |
| `d067-h20r20` | [r8-lowamount20-industry-small.json](submissions/r8-lowamount20-industry-small.json) | [run_107cb89d326344178425](results/run_107cb89d326344178425.json) | 通过 |
| `d068-h10r20` | [r22-strategy-lowvol20_industry.json](submissions/r22-strategy-lowvol20_industry.json) | [run_52968cf79c994b49a8e8](results/run_52968cf79c994b49a8e8.json) | 通过 |
| `d068-h20r20` | [r22-strategy-lowvol20_industry.json](submissions/r22-strategy-lowvol20_industry.json) | [run_7bb62048148e4ae0a282](results/run_7bb62048148e4ae0a282.json) | 通过 |
| `d075-h10r20` | [r13-overnight20-strategies.json](submissions/r13-overnight20-strategies.json) | [run_64cbaef8c4124373a82c](results/run_64cbaef8c4124373a82c.json) | 通过 |
| `d075-h20r20` | [r13-overnight20-strategies.json](submissions/r13-overnight20-strategies.json) | [run_7b73782d1631488e8d17](results/run_7b73782d1631488e8d17.json) | 通过 |
| `d081-h10r20` | [r14-intraday_reversal20.json](submissions/r14-intraday_reversal20.json) | [run_aa814c655423400bb497](results/run_aa814c655423400bb497.json) | 通过 |
| `d081-h20r20` | [r14-intraday_reversal20.json](submissions/r14-intraday_reversal20.json) | [run_c514e854a88a4306893d](results/run_c514e854a88a4306893d.json) | 通过 |
| `d082-h10r20` | [r14-clv_volume_reversal20.json](submissions/r14-clv_volume_reversal20.json) | [run_62ccbec1662247099e0c](results/run_62ccbec1662247099e0c.json) | 通过 |
| `d082-h20r20` | [r14-clv_volume_reversal20.json](submissions/r14-clv_volume_reversal20.json) | [run_59a79ac183fe4a23bd16](results/run_59a79ac183fe4a23bd16.json) | 通过 |
| `d083-h10r20` | [r14-overnight_mom20_industry.json](submissions/r14-overnight_mom20_industry.json) | [run_ce498bb41bae4b4182dd](results/run_ce498bb41bae4b4182dd.json) | 通过 |
| `d083-h20r20` | [r14-overnight_mom20_industry.json](submissions/r14-overnight_mom20_industry.json) | [run_13708ce23eba4bed9a0c](results/run_13708ce23eba4bed9a0c.json) | 通过 |
| `d084-h20r20` | [r15-wq006-strong-frequency-neighbors.json](submissions/r15-wq006-strong-frequency-neighbors.json) | [run_02a73e3bcfb14c34a5c6](results/run_02a73e3bcfb14c34a5c6.json) | 通过 |
| `d086-h20r20` | [r15-overnight20_percentile90.json](submissions/r15-overnight20_percentile90.json) | [run_3f53d9cb02b6411b9540](results/run_3f53d9cb02b6411b9540.json) | 通过 |
| `d092-h10r20` | [r18-strategy-amount-cv60-low.json](submissions/r18-strategy-amount-cv60-low.json) | [run_3cbd7537dd7a4a2b999d](results/run_3cbd7537dd7a4a2b999d.json) | 通过 |
| `d092-h20r20` | [r18-strategy-amount-cv60-low.json](submissions/r18-strategy-amount-cv60-low.json) | [run_2cdc9b788a394081894a](results/run_2cdc9b788a394081894a.json) | 通过 |
| `d098-h10r20` | [r20-strategy-vol-instability.json](submissions/r20-strategy-vol-instability.json) | [run_ca1d2fa5162d4eb8bdd1](results/run_ca1d2fa5162d4eb8bdd1.json) | 通过 |
| `d098-h20r20` | [r20-strategy-vol-instability.json](submissions/r20-strategy-vol-instability.json) | [run_9746504e8af8470380a1](results/run_9746504e8af8470380a1.json) | 通过 |
| `d099-h10r20` | [r20-strategy-lowvol-matched.json](submissions/r20-strategy-lowvol-matched.json) | [run_12ba53e001414fe0b5ff](results/run_12ba53e001414fe0b5ff.json) | 通过 |
| `d099-h20r20` | [r20-strategy-lowvol-matched.json](submissions/r20-strategy-lowvol-matched.json) | [run_966cdd3adfbf4876a99a](results/run_966cdd3adfbf4876a99a.json) | 通过 |

## 第二段检查点状态重建

对截止检查点前的 47 份 QS28 提交（44 个双账户批次、3 个单账户任务），从接受响应恢复 91 次账户尝试；按 Run 的实际 `finished_at` 判断截至检查点的状态。89 个有完整 Result，2 个资源失败。再与 71 个原始精确复用案例和早先资源失败案例合并，得到下表；不是从检查点汇总反推个案。新增 89 个完整 Result 也额外检查了冻结输入、数据和执行契约。

| 状态 | 独立计数 | 检查点计数 |
|---|---:|---:|
| 原始精确复用 | 71 | 71 |
| QS28 新完整结果 | 89 | 89 |
| 完整案例合计 | 160 | 160 |
| 实际运行因资源失败 | 5 | 8 个未解决的一部分 |
| 按资源失败停止规则未提交 | 3 | 8 个未解决的一部分 |
| 尚未提交且未被停止规则阻断 | 50 | 50 |
| 已提交但截至检查点尚未完成 | 0 | 0 |
| 合计 | 218 | 218 |

前 75 个定义的 150 个案例为 146 个完整结果（89 新结果 + 57 复用）、2 次资源失败、2 个停止后未提交；其余定义已有 14 个复用结果、4 个原效率未解决案例、50 个未提交案例。与检查点字段逐项比较，差异为 0。

| 未解决案例 | 原始证据 | 截至检查点的含义 |
|---|---|---|
| `d052-h10r20` | [提交](submissions/r28-d052-year-h10.json)；[run_cc031d9dc41b4717aca1](runs/run_cc031d9dc41b4717aca1.json) | 实际资源失败；预热 252/252，研究 68/242，最后研究日 2025-12-22；无 Result |
| `d052-h20r20` | [阻断 Run run_cc031d9dc41b4717aca1](runs/run_cc031d9dc41b4717aca1.json) | 同一定义已有资源失败，按冻结停止规则未提交；没有自己的失败 Run 或收益结果 |
| `d062-h10r20` | [提交](submissions/r28-d062-year-h10.json)；[run_a86c4107345843bb8573](runs/run_a86c4107345843bb8573.json) | 实际资源失败；预热 252/252，研究 68/242，最后研究日 2025-12-22；无 Result |
| `d062-h20r20` | [阻断 Run run_a86c4107345843bb8573](runs/run_a86c4107345843bb8573.json) | 同一定义已有资源失败，按冻结停止规则未提交；没有自己的失败 Run 或收益结果 |
| `d090-h10r20` | [提交](submissions/r18-strategy-efficiency-change252-single-h10.json)；[run_c17b5a72dc0d483da801](runs/run_c17b5a72dc0d483da801.json) | 实际资源失败；预热 252/252，研究 4/242，最后研究日 2025-09-15；无 Result |
| `d090-h20r20` | [提交](submissions/r18-strategy-efficiency-change252-single-h20.json)；[run_4cfbc3af66b84752ac4c](runs/run_4cfbc3af66b84752ac4c.json) | 实际资源失败；预热 252/252，研究 4/242，最后研究日 2025-09-15；无 Result |
| `d103-h10r20` | [提交](submissions/r24-efficiency-delta252-h10.json)；[run_164b822dc3dd48c98c1c](runs/run_164b822dc3dd48c98c1c.json) | 实际资源失败；预热 252/252，研究 68/242，最后研究日 2025-12-22；无 Result |
| `d103-h20r20` | [阻断 Run run_164b822dc3dd48c98c1c](runs/run_164b822dc3dd48c98c1c.json) | 同一定义已有资源失败，按冻结停止规则未提交；没有自己的失败 Run 或收益结果 |

五个实际失败 Run 的原始请求与保存的 Run.input 逐项一致，均声明 `result_available: false`，本地也没有对应完整 Result 文件。原效率定义编号为 **d090（显式减法）与 d103（delta 写法）**；前者 H10/H20 均实际失败，后者 H10 实际失败、H20 未提交。**d108 是 `momentum120_skip20_history200`**，来自 [r27-factors-none.json](submissions/r27-factors-none.json) 的第二项，公式为 `rank(lag(close, 20) / lag(close, 120) - 1 + 0 * ts_mean(close, 200))`；它不属于上述资源失败定义。

50 个未提交案例的完整集合如下。这里的未提交按固定检查点判断，之后的执行不会改变这个历史结论。

| 定义 | 截至检查点未提交的固定账户 |
|---|---|
| `d076` | `d076-h10r20`, `d076-h20r20` |
| `d077` | `d077-h10r20`, `d077-h20r20` |
| `d078` | `d078-h10r20`, `d078-h20r20` |
| `d079` | `d079-h10r20`, `d079-h20r20` |
| `d080` | `d080-h10r20`, `d080-h20r20` |
| `d084` | `d084-h10r20` |
| `d085` | `d085-h10r20`, `d085-h20r20` |
| `d086` | `d086-h10r20` |
| `d087` | `d087-h10r20`, `d087-h20r20` |
| `d088` | `d088-h10r20`, `d088-h20r20` |
| `d089` | `d089-h10r20`, `d089-h20r20` |
| `d091` | `d091-h10r20`, `d091-h20r20` |
| `d093` | `d093-h10r20`, `d093-h20r20` |
| `d094` | `d094-h10r20`, `d094-h20r20` |
| `d095` | `d095-h10r20`, `d095-h20r20` |
| `d096` | `d096-h10r20`, `d096-h20r20` |
| `d097` | `d097-h10r20`, `d097-h20r20` |
| `d100` | `d100-h10r20`, `d100-h20r20` |
| `d101` | `d101-h10r20`, `d101-h20r20` |
| `d102` | `d102-h10r20`, `d102-h20r20` |
| `d104` | `d104-h10r20`, `d104-h20r20` |
| `d105` | `d105-h10r20`, `d105-h20r20` |
| `d106` | `d106-h10r20`, `d106-h20r20` |
| `d107` | `d107-h10r20`, `d107-h20r20` |
| `d108` | `d108-h10r20`, `d108-h20r20` |
| `d109` | `d109-h10r20`, `d109-h20r20` |

## 结论的边界

- **固定 R20 只审计这一组参数。** H10/H20 × R20 的结果不能证明同一公式的所有持仓规模、调仓频率或状态切换规则都无效，也不能据此替换过去已冻结的其他频率试验。因子摘要与账户结果衡量不同对象；本审查没有把因子 IC、分组收益直接当作策略 Sharpe。
- **这些日期已经被研究过。** 2025-09-10 至 2026-09-09 的这轮统一账户补测可用来观察旧因子门槛遗漏，但不是完全未见历史的样本外验证。预定 3 年/季度补测也不能仅因换了窗口就称为未见样本外。本审查没有估计多重检验显著性、PBO 或未来收益。
- **原生 1000 万账户不等于用户的 10 万账户。** 复用 Result 的本金和费用声明一致仅证明可比较；最低佣金、手数、可交易板块、成交和资金闲置等对较小账户的影响，需要相应账户证据。这里没有核实用户券商权限，没有将 1000 万收益按比例当成 10 万实盘利润。
- **109 个定义、96 条字面公式不是独立经济家族数量。** 13 对完全相同公式分别带 none/industry；其他不同字面表达还可能是窗口/阈值变体、控制项或等价改写。本审查只做精确字面身份核对，没有用相同摘要/收益认定等价，也没有独立证明 d090 与 d103 的代数或缺失值语义等价。证据 JSON 保留各自全部来源，不能把控制项或变体统计成新的独立赚钱策略。
- **资源失败与未提交没有经济结论。** 8 个未解决和 50 个未提交案例均不能算作 Sharpe 不达标；实际运行失败也不能自动等同于公式计算错误。三个未提交账户没有真实失败 Run。
- **证据是已保存的 MCP 请求和 Run/Result。** 129 份源文件与冻结哈希一致，且输入和 Result 声明一致；这没有独立验证服务端数据字节、运行时内核实现、真实成交、净值路径或 Sharpe 计算。本审查未重新请求服务端状态、未导出行情、未复算 NAV，Result 文件哈希是本地审查快照标识。

上述边界由 [冻结 selection / execution_reference](round28-plan.json)、各原始提交和逐个 Result 中可检查的字段支持。本次只新增本报告与 [round28-inventory-review.json](round28-inventory-review.json)；未改计划、父代理脚本、原始研究结果或产品代码。
