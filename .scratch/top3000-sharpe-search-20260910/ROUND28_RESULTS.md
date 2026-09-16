# 既有定义的统一账户覆盖审计

更新：2026-09-10T02:57:25.212680+00:00

正Rank IC不是TopN多头盈利的必要条件。此次按全部既有提交冻结有限清单，统一检查固定账户参数；IC、最高组与配对差的正负只用于对照分类。[方法审查](ROUND28_METHOD_REVIEW.md)、[冻结清单与协议](round28-plan.json)、[独立反例核对](round28-gate-proof.json)。

清单包含109个公式/行业处理定义、96个公式文本、218个一年期案例。冻结时71个可复用、143个需要补测，效率变化原式和等价式的4个案例保留为资源问题未解决。清单包含原候选、对照、组合及行业变体，并不代表109个独立经济家族。

固定TOP3000、2025-09-10至2026-09-09，每个定义10/20只、每20个交易日调仓。全部沿用原公式和行业处理。原生本金1000万元；10万元、20%回撤仍需独立账户验证，不能按本金比例缩放。

目前完成208/218个固定案例，其中复用71、新完成137；全年Sharpe>1.2且回撤≤20%的案例0个。

剩余案例分别为：尚未提交0，已提交但尚未收齐结果0，执行问题未解决10。这些都不计作经济失败。

|原筛选类别|已完成账户案例|原生全年达标|
|---|---:|---:|
|原因子门槛通过|92|0|
|仅IC条件未过|18|0|
|最高组/配对差也未过|82|0|
|指标空值/覆盖不足|16|0|

固定清单的可执行部分已收齐，当前没有运行中或待采集任务。资源未解决案例继续保留；既包括实际失败，也包括按停止规则未派发的同定义账户。不在执行条件未变时重试，也不把这部分当作经济负结果。

上表按本年度实际因子统计分类；“冻结时缺少年度因子”的定义在补测后归入相应类别。尚未完成的部分不能当作负结果，分批早期通过率不代表完整清单。

来源列保留最早实验的原始名称。本次全部为一年期，实际持仓与调仓间隔在独立列中显示。

|定义|历史来源名称|行业处理|本次持仓/调仓|累计净收益|最大回撤|Sharpe|旧门槛分类|原生全年通过|
|---|---|---|---|---:|---:|---:|---|---|
|[d001](https://thesistrace.com/research-runs/run_82953f8488be402ab952)|QS1 rev1 1日反转|none|10/20|-33.74%|47.25%|-1.025|最高组/配对差也未过|否|
|[d001](https://thesistrace.com/research-runs/run_8f1df02cdb174858b76e)|QS1 rev1 1日反转|none|20/20|-21.35%|37.72%|-0.585|最高组/配对差也未过|否|
|[d002](https://thesistrace.com/research-runs/run_204bb650819e46d2a166)|QS1 rev5 5日反转|none|10/20|-39.34%|56.75%|-1.161|最高组/配对差也未过|否|
|[d002](https://thesistrace.com/research-runs/run_c88938e88f6a45ee98de)|QS1 rev5 5日反转|none|20/20|-33.80%|50.06%|-1.056|最高组/配对差也未过|否|
|[d003](https://thesistrace.com/research-runs/run_44b9548bba4449559899)|QS1 rev20 20日反转|none|10/20|-15.28%|43.43%|-0.269|原因子门槛通过|否|
|[d003](https://thesistrace.com/research-runs/run_47cdfd9fa3b147ff8ae7)|QS1 rev20 20日反转|none|20/20|0.26%|33.43%|0.184|原因子门槛通过|否|
|[d004](https://thesistrace.com/research-runs/run_a3f3e1f3957c416fa052)|QS1 ma5 5日均线偏离反转|none|10/20|-32.22%|48.37%|-0.982|最高组/配对差也未过|否|
|[d004](https://thesistrace.com/research-runs/run_70ac63ab5a1447fcb3f9)|QS1 ma5 5日均线偏离反转|none|20/20|-27.97%|44.03%|-0.904|最高组/配对差也未过|否|
|[d005](https://thesistrace.com/research-runs/run_5cba9a725a0946729d59)|QS1 ma20 20日均线偏离反转|none|10/20|-13.91%|43.92%|-0.239|最高组/配对差也未过|否|
|[d005](https://thesistrace.com/research-runs/run_d166dace016949f3ac4a)|QS1 ma20 20日均线偏离反转|none|20/20|-24.13%|45.39%|-0.713|最高组/配对差也未过|否|
|[d006](https://thesistrace.com/research-runs/run_b22b9be9d274427ca2d7)|QS1 intraday5 5日日内反转|none|10/20|-1.04%|40.62%|0.170|原因子门槛通过|否|
|[d006](https://thesistrace.com/research-runs/run_fe6db5c8d9264a54a1fe)|QS1 intraday5 5日日内反转|none|20/20|-16.03%|39.55%|-0.340|原因子门槛通过|否|
|[d007](https://thesistrace.com/research-runs/run_ec976b14deed4bd0a2f5)|QS1 overnight20 20日隔夜反转|none|10/20|-36.36%|46.97%|-1.141|最高组/配对差也未过|否|
|[d007](https://thesistrace.com/research-runs/run_c99a03ccc17b42a59837)|QS1 overnight20 20日隔夜反转|none|20/20|-33.01%|41.65%|-1.140|最高组/配对差也未过|否|
|[d008](https://thesistrace.com/research-runs/run_2f8ab0fceb9b4055a893)|QS1 close_location5 5日收盘位置反转|none|10/20|-9.81%|32.78%|-0.198|原因子门槛通过|否|
|[d008](https://thesistrace.com/research-runs/run_d98414ebc0ac401298c1)|QS1 close_location5 5日收盘位置反转|none|20/20|-0.88%|32.45%|0.104|原因子门槛通过|否|
|[d009](https://thesistrace.com/research-runs/run_adcd6e7d9237470b90de)|QS1 momentum120_skip20 中期动量跳过近期20日|none|10/20|-5.86%|43.14%|0.114|原因子门槛通过|否|
|[d009](https://thesistrace.com/research-runs/run_a64d9045d7314c39bab4)|QS1 momentum120_skip20 中期动量跳过近期20日|none|20/20|-17.09%|46.72%|-0.162|原因子门槛通过|否|
|[d010](https://thesistrace.com/research-runs/run_1a6ab615115040618a0a)|QS1 lowvol20 20日低收益波动|none|10/20|3.41%|10.62%|0.363|最高组/配对差也未过|否|
|[d010](https://thesistrace.com/research-runs/run_ab196ccc0e1d41a8815b)|QS1 lowvol20 20日低收益波动|none|20/20|-0.63%|14.39%|-0.004|最高组/配对差也未过|否|
|[d011](https://thesistrace.com/research-runs/run_9532142d3b424426a347)|QS1 lowvol60 60日低收益波动|none|10/20|-7.13%|17.10%|-0.627|最高组/配对差也未过|否|
|[d011](https://thesistrace.com/research-runs/run_4789161ab0ce4bdf854e)|QS1 lowvol60 60日低收益波动|none|20/20|-2.08%|13.32%|-0.144|最高组/配对差也未过|否|
|[d012](https://thesistrace.com/research-runs/run_8b670171fc39432c99c9)|QS1 lowrange20 20日低振幅|none|10/20|-2.97%|13.49%|-0.217|最高组/配对差也未过|否|
|[d012](https://thesistrace.com/research-runs/run_c584f0cea48c451db2de)|QS1 lowrange20 20日低振幅|none|20/20|-4.83%|15.92%|-0.417|最高组/配对差也未过|否|
|[d013](https://thesistrace.com/research-runs/run_3edc7b50d57d4330aefd)|QS1 illiquidity20 20日非流动性|none|10/20|3.62%|33.10%|0.282|最高组/配对差也未过|否|
|[d013](https://thesistrace.com/research-runs/run_506f5dc808804c9582eb)|QS1 illiquidity20 20日非流动性|none|20/20|-3.67%|30.40%|0.012|最高组/配对差也未过|否|
|[d014](https://thesistrace.com/research-runs/run_434dcae08cc0483284ed)|QS1 lowamount20 20日低成交额|none|10/20|0.49%|17.22%|0.138|最高组/配对差也未过|否|
|[d014](https://thesistrace.com/research-runs/run_3690e87a47484b0fb3b4)|QS1 lowamount20 20日低成交额|none|20/20|6.97%|22.53%|0.435|最高组/配对差也未过|否|
|[d015](https://thesistrace.com/research-runs/run_34b3b6f8357f456b9fcf)|QS1 volume_dry 5比60日缩量|none|10/20|4.89%|33.31%|0.317|最高组/配对差也未过|否|
|[d015](https://thesistrace.com/research-runs/run_3096426eab8a4a67af7a)|QS1 volume_dry 5比60日缩量|none|20/20|-1.52%|32.66%|0.072|最高组/配对差也未过|否|
|[d016](https://thesistrace.com/research-runs/run_e409850d95a343dfaacd)|QS1 roe 净资产盈利率|none|10/20|-41.31%|51.89%|-1.799|原因子门槛通过|否|
|[d016](https://thesistrace.com/research-runs/run_1ba88cbcb78649c5bea4)|QS1 roe 净资产盈利率|none|20/20|-28.62%|38.27%|-1.358|原因子门槛通过|否|
|[d017](https://thesistrace.com/research-runs/run_041d1b65491040b7b871)|QS1 roa 资产盈利率|none|10/20|-17.18%|23.69%|-0.687|原因子门槛通过|否|
|[d017](https://thesistrace.com/research-runs/run_546191d4caf44a40a8e9)|QS1 roa 资产盈利率|none|20/20|-21.05%|25.90%|-1.269|原因子门槛通过|否|
|[d018](https://thesistrace.com/research-runs/run_cc9eee9be80143e7a6c5)|QS1 cfoa 经营现金资产比|none|10/20|-9.28%|26.45%|-0.324|最高组/配对差也未过|否|
|[d018](https://thesistrace.com/research-runs/run_a133fc81455f40f29b48)|QS1 cfoa 经营现金资产比|none|20/20|-13.81%|23.26%|-0.682|最高组/配对差也未过|否|
|[d019](https://thesistrace.com/research-runs/run_b699af2487ae4eecacb9)|QS1 cash_accrual 现金盈利相对利润|none|10/20|-10.92%|30.44%|-0.200|最高组/配对差也未过|否|
|[d019](https://thesistrace.com/research-runs/run_eb46fa6d59d44a118ff9)|QS1 cash_accrual 现金盈利相对利润|none|20/20|-6.95%|31.59%|-0.108|最高组/配对差也未过|否|
|[d020](https://thesistrace.com/research-runs/run_70b942af08124fe4a273)|QS1 lowdebt 低资产负债率|none|10/20|-11.93%|29.01%|-0.243|仅IC条件未过|否|
|[d020](https://thesistrace.com/research-runs/run_a5d6ea5293af43a6a325)|QS1 lowdebt 低资产负债率|none|20/20|-6.84%|26.33%|-0.090|仅IC条件未过|否|
|[d021](https://thesistrace.com/research-runs/run_2e8dd6e931f949b48984)|QS2 rev5_lowvol20 H100 R5|none|10/20|1.75%|22.37%|0.190|最高组/配对差也未过|否|
|[d021](https://thesistrace.com/research-runs/run_ce045e6dabde468297d9)|QS2 rev5_lowvol20 H100 R5|none|20/20|1.94%|22.80%|0.203|最高组/配对差也未过|否|
|[d022](https://thesistrace.com/research-runs/run_0c4bb5652639484d8909)|QS2 rev5_cfoa H100 R5|none|10/20|6.51%|32.47%|0.370|最高组/配对差也未过|否|
|[d022](https://thesistrace.com/research-runs/run_243e0ac32964439a81e7)|QS2 rev5_cfoa H100 R5|none|20/20|-1.07%|28.83%|0.098|最高组/配对差也未过|否|
|[d023](https://thesistrace.com/research-runs/run_a2ade142890b4381a542)|QS2 intraday5_lowamount20 H100 R5|none|10/20|-6.34%|42.07%|-0.092|原因子门槛通过|否|
|[d023](https://thesistrace.com/research-runs/run_421c73b86a604c7abf53)|QS2 intraday5_lowamount20 H100 R5|none|20/20|-2.15%|33.15%|0.038|原因子门槛通过|否|
|[d024](https://thesistrace.com/research-runs/run_e87086d4b4614ba593c2)|QS2 lowamount20_cfoa H100 R20|none|10/20|0.87%|16.64%|0.144|最高组/配对差也未过|否|
|[d024](https://thesistrace.com/research-runs/run_bb2d128b344348a9abef)|QS2 lowamount20_cfoa H100 R20|none|20/20|3.30%|13.53%|0.282|最高组/配对差也未过|否|
|[d025](https://thesistrace.com/research-runs/run_2dc4db6910e74c0cb7e3)|QS2 ma5_volume_dry H100 R5|none|10/20|8.23%|34.78%|0.412|最高组/配对差也未过|否|
|[d025](https://thesistrace.com/research-runs/run_0019f48d4a6446c99a13)|QS2 ma5_volume_dry H100 R5|none|20/20|-3.09%|37.27%|0.046|最高组/配对差也未过|否|
|[d026](https://thesistrace.com/research-runs/run_e8864eb620b14175b480)|QS2 lowamount20_roa H100 R20|none|10/20|3.01%|19.18%|0.256|原因子门槛通过|否|
|[d026](https://thesistrace.com/research-runs/run_3ec5059d8de94743b55b)|QS2 lowamount20_roa H100 R20|none|20/20|-10.69%|20.39%|-0.622|原因子门槛通过|否|
|[d027](https://thesistrace.com/research-runs/run_e7389b25c96646cb94e9)|QS2 moderate_rev5 H100 R5|none|10/20|-13.85%|33.92%|-0.416|原因子门槛通过|否|
|[d027](https://thesistrace.com/research-runs/run_38e03c93f3e84b398f4b)|QS2 moderate_rev5 H100 R5|none|20/20|-8.62%|30.59%|-0.259|原因子门槛通过|否|
|[d028](https://thesistrace.com/research-runs/run_91d77c2498474aa9ab6c)|QS2 lowamount20_trend120 H100 R20|none|10/20|4.06%|25.01%|0.288|最高组/配对差也未过|否|
|[d028](https://thesistrace.com/research-runs/run_7c16a70f1ec243cfbc45)|QS2 lowamount20_trend120 H100 R20|none|20/20|12.78%|24.83%|0.650|最高组/配对差也未过|否|
|[d029](https://thesistrace.com/research-runs/run_15d4919b49364baca993)|QS2 lowvol20_trend120 H100 R20|none|10/20|3.13%|15.79%|0.325|最高组/配对差也未过|否|
|[d029](https://thesistrace.com/research-runs/run_679ece79cd3a440fb1a4)|QS2 lowvol20_trend120 H100 R20|none|20/20|1.04%|13.33%|0.150|最高组/配对差也未过|否|
|[d030](https://thesistrace.com/research-runs/run_0001837f61c04a83b580)|QS2 cfoa_trend120 H100 R20|none|10/20|-17.22%|34.64%|-0.532|最高组/配对差也未过|否|
|[d030](https://thesistrace.com/research-runs/run_3721a13529ac4bc0ad1a)|QS2 cfoa_trend120 H100 R20|none|20/20|-13.31%|30.04%|-0.484|最高组/配对差也未过|否|
|[d031](https://thesistrace.com/research-runs/run_cf95b27045d04d2cb4a1)|QS2 lowamount20_lowvol20 H100 R20|none|10/20|-5.80%|23.94%|-0.294|最高组/配对差也未过|否|
|[d031](https://thesistrace.com/research-runs/run_49b64e88ba684d93a625)|QS2 lowamount20_lowvol20 H100 R20|none|20/20|8.69%|16.62%|0.643|最高组/配对差也未过|否|
|[d032](https://thesistrace.com/research-runs/run_a43b2f7f9aad4e4d8aca)|QS3 momentum_lowvol60 H100 R20|none|10/20|0.62%|14.02%|0.126|原因子门槛通过|否|
|[d032](https://thesistrace.com/research-runs/run_d04254f233dd49908398)|QS3 momentum_lowvol60 H100 R20|none|20/20|-5.51%|17.59%|-0.272|原因子门槛通过|否|
|[d033](https://thesistrace.com/research-runs/run_376f8d0e4a8d4dcda86d)|QS3 momentum_risk120 H100 R20|none|10/20|-1.64%|49.02%|0.225|仅IC条件未过|否|
|[d033](https://thesistrace.com/research-runs/run_d6c22dc0a3094bde908d)|QS3 momentum_risk120 H100 R20|none|20/20|-6.43%|46.92%|0.105|仅IC条件未过|否|
|[d034](https://thesistrace.com/research-runs/run_96cb42e5755544198730)|QS3 roa_lowdebt H100 R20|none|10/20|-1.13%|19.65%|0.077|原因子门槛通过|否|
|[d034](https://thesistrace.com/research-runs/run_f30792a3fe8a4c948322)|QS3 roa_lowdebt H100 R20|none|20/20|-7.21%|19.08%|-0.233|原因子门槛通过|否|
|[d035](https://thesistrace.com/research-runs/run_34246eb3c6364b2aa67d)|QS4 3y switch_trend_mom_lowvol H100 R20|none|10/20|1.55%|20.47%|0.194|原因子门槛通过|否|
|[d035](https://thesistrace.com/research-runs/run_222a56cedf21406f8642)|QS4 3y switch_trend_mom_lowvol H100 R20|none|20/20|-10.51%|24.14%|-0.367|原因子门槛通过|否|
|[d036](https://thesistrace.com/research-runs/run_761410df5edd4984868a)|QS4 3y switch_trend_amount_lowvol H100 R20|none|10/20|8.00%|8.92%|0.598|最高组/配对差也未过|否|
|[d036](https://thesistrace.com/research-runs/run_d79195a0bd25465fa125)|QS4 3y switch_trend_amount_lowvol H100 R20|none|20/20|2.33%|12.22%|0.252|最高组/配对差也未过|否|
|[d037](https://thesistrace.com/research-runs/run_c910363960754ce1b047)|QS4 3y switch_vol_lowvol_moderate H100 R20|none|10/20|-4.84%|24.89%|-0.079|原因子门槛通过|否|
|[d037](https://thesistrace.com/research-runs/run_dd614038e5cd485c885c)|QS4 3y switch_vol_lowvol_moderate H100 R20|none|20/20|-4.07%|25.71%|-0.094|原因子门槛通过|否|
|[d038](https://thesistrace.com/research-runs/run_1fef61cdcb8b47d58aae)|QS5 1y wq003|none|10/20|10.91%|22.35%|0.556|原因子门槛通过|否|
|[d038](https://thesistrace.com/research-runs/run_31aa367b51854a9fbd52)|QS5 1y wq003|none|20/20|10.99%|17.62%|0.595|原因子门槛通过|否|
|[d039](https://thesistrace.com/research-runs/run_90291e3716f94f559148)|QS5 1y wq006|none|10/20|-12.17%|31.59%|-0.454|原因子门槛通过|否|
|[d039](https://thesistrace.com/research-runs/run_d98cee7926a6464c8e46)|QS5 1y wq006|none|20/20|15.59%|19.96%|0.808|原因子门槛通过|否|
|[d040](https://thesistrace.com/research-runs/run_0b392f7f468c4823b6b0)|QS5 1y wq002|none|10/20|25.71%|29.50%|0.987|原因子门槛通过|否|
|[d040](https://thesistrace.com/research-runs/run_521b1c390bc9431fbbef)|QS5 1y wq002|none|20/20|3.98%|27.57%|0.289|原因子门槛通过|否|
|[d041](https://thesistrace.com/research-runs/run_eddb56451afe415c8d7c)|QS5 1y wq013|none|10/20|-33.98%|47.31%|-1.128|原因子门槛通过|否|
|[d041](https://thesistrace.com/research-runs/run_b04fee5ce5314961aef0)|QS5 1y wq013|none|20/20|-19.01%|39.50%|-0.636|原因子门槛通过|否|
|[d042](https://thesistrace.com/research-runs/run_66bf715974274a0eb53c)|QS5 1y wq016|none|10/20|-26.25%|46.65%|-0.789|原因子门槛通过|否|
|[d042](https://thesistrace.com/research-runs/run_47a20c9e4c92499baef8)|QS5 1y wq016|none|20/20|-10.97%|34.28%|-0.276|原因子门槛通过|否|
|[d043](https://thesistrace.com/research-runs/run_8f5fd62da8294b86be66)|QS5 1y wq101|none|10/20|-16.58%|29.58%|-0.249|最高组/配对差也未过|否|
|[d043](https://thesistrace.com/research-runs/run_f388fb1eb2e649eea664)|QS5 1y wq101|none|20/20|-14.78%|30.17%|-0.298|最高组/配对差也未过|否|
|[d044](https://thesistrace.com/research-runs/run_ce2a88ffef3a4e939df0)|QS5 1y wq101_mean5|none|10/20|-39.08%|44.57%|-1.096|最高组/配对差也未过|否|
|[d044](https://thesistrace.com/research-runs/run_2157292fe3814b0bae47)|QS5 1y wq101_mean5|none|20/20|-17.81%|30.13%|-0.420|最高组/配对差也未过|否|
|[d045](https://thesistrace.com/research-runs/run_f135fd937953416f9ccd)|QS5 1y wq012_ret|none|10/20|-27.75%|37.10%|-0.528|原因子门槛通过|否|
|[d045](https://thesistrace.com/research-runs/run_08ae57b1b5ca445ab584)|QS5 1y wq012_ret|none|20/20|-31.81%|40.17%|-0.789|原因子门槛通过|否|
|[d046](https://thesistrace.com/research-runs/run_3b612ff18e624abf9968)|QS5 1y wq009_ret_switch|none|10/20|-20.79%|46.28%|-0.361|最高组/配对差也未过|否|
|[d046](https://thesistrace.com/research-runs/run_ee1f8dcfe9dd4439be9f)|QS5 1y wq009_ret_switch|none|20/20|-20.84%|36.86%|-0.450|最高组/配对差也未过|否|
|[d047](https://thesistrace.com/research-runs/run_8f7cab7e3b72467ca770)|QS7 1y lowmax20 none|none|10/20|-4.44%|15.86%|-0.261|原因子门槛通过|否|
|[d047](https://thesistrace.com/research-runs/run_d164a8db96914d78b5e8)|QS7 1y lowmax20 none|none|20/20|-0.12%|14.97%|0.053|原因子门槛通过|否|
|[d048](https://thesistrace.com/research-runs/run_285c38e87c074b839ec3)|QS7 1y downside20 none|none|10/20|12.45%|10.01%|0.971|原因子门槛通过|否|
|[d048](https://thesistrace.com/research-runs/run_6f3a11540849479185aa)|QS7 1y downside20 none|none|20/20|1.66%|13.91%|0.208|原因子门槛通过|否|
|[d049](https://thesistrace.com/research-runs/run_fd375d4b19d042a7826a)|QS7 1y quality_defensive none|none|10/20|-8.47%|23.61%|-0.430|原因子门槛通过|否|
|[d049](https://thesistrace.com/research-runs/run_ef1ee9e6f70941f58f19)|QS7 1y quality_defensive none|none|20/20|-12.69%|22.34%|-0.763|原因子门槛通过|否|
|[d050](https://thesistrace.com/research-runs/run_1a1a6163af2945d3920f)|QS7 1y cash_margin none|none|10/20|-10.03%|24.40%|-0.485|最高组/配对差也未过|否|
|[d050](https://thesistrace.com/research-runs/run_aa05840caffb41388114)|QS7 1y cash_margin none|none|20/20|-8.71%|21.90%|-0.401|最高组/配对差也未过|否|
|[d051](https://thesistrace.com/research-runs/run_4b89a4d019b1444fa422)|QS7 1y profit_margin none|none|10/20|-6.00%|29.26%|-0.144|原因子门槛通过|否|
|[d051](https://thesistrace.com/research-runs/run_cd3bf5681ecb4d499c0d)|QS7 1y profit_margin none|none|20/20|-6.83%|23.99%|-0.275|原因子门槛通过|否|
|[d053](https://thesistrace.com/research-runs/run_b4709084b1c148d5bda1)|QS7 1y revenue_growth252 none|none|10/20|-15.26%|26.41%|-0.490|原因子门槛通过|否|
|[d053](https://thesistrace.com/research-runs/run_0292b71688a64b9891e2)|QS7 1y revenue_growth252 none|none|20/20|-9.03%|23.35%|-0.251|原因子门槛通过|否|
|[d054](https://thesistrace.com/research-runs/run_515b9c90752044b0b010)|QS7 1y trend_consistency60 none|none|10/20|-33.16%|49.12%|-0.727|最高组/配对差也未过|否|
|[d054](https://thesistrace.com/research-runs/run_2571def985834dbea043)|QS7 1y trend_consistency60 none|none|20/20|-25.07%|43.70%|-0.518|最高组/配对差也未过|否|
|[d055](https://thesistrace.com/research-runs/run_d44a5acfe66a42639bef)|QS7 1y positive_roe none|none|10/20|-9.59%|29.58%|-0.337|原因子门槛通过|否|
|[d055](https://thesistrace.com/research-runs/run_c465a7be404b436e85fa)|QS7 1y positive_roe none|none|20/20|-16.24%|27.60%|-0.880|原因子门槛通过|否|
|[d056](https://thesistrace.com/research-runs/run_7f7cb4b361c24e72836d)|QS7 1y volume_dry_lowvol none|none|10/20|4.15%|29.16%|0.301|原因子门槛通过|否|
|[d056](https://thesistrace.com/research-runs/run_1680945deddc4abc85da)|QS7 1y volume_dry_lowvol none|none|20/20|2.47%|25.54%|0.228|原因子门槛通过|否|
|[d057](https://thesistrace.com/research-runs/run_63393a4c245040f4bfd2)|QS7 1y lowmax20 industry|industry|10/20|4.92%|14.87%|0.353|原因子门槛通过|否|
|[d057](https://thesistrace.com/research-runs/run_d6b632ee5ee143269c38)|QS7 1y lowmax20 industry|industry|20/20|1.34%|17.14%|0.167|原因子门槛通过|否|
|[d058](https://thesistrace.com/research-runs/run_0eaf60be30514ab89724)|QS7 1y downside20 industry|industry|10/20|-2.13%|14.61%|-0.001|原因子门槛通过|否|
|[d058](https://thesistrace.com/research-runs/run_f7ef0da8484846c78805)|QS7 1y downside20 industry|industry|20/20|4.73%|11.52%|0.359|原因子门槛通过|否|
|[d059](https://thesistrace.com/research-runs/run_555dda7f88d744d998dd)|QS7 1y quality_defensive industry|industry|10/20|-14.88%|27.30%|-0.800|原因子门槛通过|否|
|[d059](https://thesistrace.com/research-runs/run_264c7ea0243d454492aa)|QS7 1y quality_defensive industry|industry|20/20|-8.26%|28.04%|-0.407|原因子门槛通过|否|
|[d060](https://thesistrace.com/research-runs/run_8327dd40cdf54721b6a2)|QS7 1y cash_margin industry|industry|10/20|-21.40%|41.97%|-0.546|原因子门槛通过|否|
|[d060](https://thesistrace.com/research-runs/run_1d82f358d6504066b9b8)|QS7 1y cash_margin industry|industry|20/20|-16.97%|39.62%|-0.500|原因子门槛通过|否|
|[d061](https://thesistrace.com/research-runs/run_6fb4b3a3dc80443a94a7)|QS7 1y profit_margin industry|industry|10/20|-23.08%|37.95%|-1.010|原因子门槛通过|否|
|[d061](https://thesistrace.com/research-runs/run_1e4fb5bcda304fcfaaf5)|QS7 1y profit_margin industry|industry|20/20|-28.64%|43.70%|-1.350|原因子门槛通过|否|
|[d063](https://thesistrace.com/research-runs/run_92d30c020d64478a8ca9)|QS7 1y revenue_growth252 industry|industry|10/20|-12.15%|28.24%|-0.303|原因子门槛通过|否|
|[d063](https://thesistrace.com/research-runs/run_5f316b8f337941748319)|QS7 1y revenue_growth252 industry|industry|20/20|-22.72%|33.89%|-0.974|原因子门槛通过|否|
|[d064](https://thesistrace.com/research-runs/run_228e7717956648d7ab92)|QS7 1y trend_consistency60 industry|industry|10/20|-12.13%|34.81%|-0.247|最高组/配对差也未过|否|
|[d064](https://thesistrace.com/research-runs/run_89e4a23323114eeabc0d)|QS7 1y trend_consistency60 industry|industry|20/20|-21.42%|37.32%|-0.713|最高组/配对差也未过|否|
|[d065](https://thesistrace.com/research-runs/run_a3b6fad0acd04f869b6b)|QS7 1y positive_roe industry|industry|10/20|-17.85%|33.13%|-0.680|原因子门槛通过|否|
|[d065](https://thesistrace.com/research-runs/run_172ba011cc4e4f47941d)|QS7 1y positive_roe industry|industry|20/20|-6.07%|27.82%|-0.176|原因子门槛通过|否|
|[d066](https://thesistrace.com/research-runs/run_c864f5fc87114abba5fb)|QS7 1y volume_dry_lowvol industry|industry|10/20|0.97%|33.25%|0.161|最高组/配对差也未过|否|
|[d066](https://thesistrace.com/research-runs/run_51c5dd5deeca4fdebbf7)|QS7 1y volume_dry_lowvol industry|industry|20/20|9.56%|23.83%|0.553|最高组/配对差也未过|否|
|[d067](https://thesistrace.com/research-runs/run_bb819378d121406caf5b)|QS7 1y lowamount20_control industry|industry|10/20|19.41%|25.42%|0.768|原因子门槛通过|否|
|[d067](https://thesistrace.com/research-runs/run_107cb89d326344178425)|QS7 1y lowamount20_control industry|industry|20/20|9.52%|26.03%|0.473|原因子门槛通过|否|
|[d068](https://thesistrace.com/research-runs/run_52968cf79c994b49a8e8)|QS7 1y lowvol20_control industry|industry|10/20|-1.25%|14.04%|-0.007|原因子门槛通过|否|
|[d068](https://thesistrace.com/research-runs/run_7bb62048148e4ae0a282)|QS7 1y lowvol20_control industry|industry|20/20|-2.92%|15.73%|-0.121|原因子门槛通过|否|
|[d069](https://thesistrace.com/research-runs/run_4e1fc19bf405468da283)|QS10 1y lowamount LOO_breadth20 H10 R5|none|10/20|0.89%|10.40%|0.137|指标空值/覆盖不足|否|
|[d069](https://thesistrace.com/research-runs/run_6e0869929d0741cc8f4b)|QS10 1y lowamount LOO_breadth20 H10 R5|none|20/20|5.23%|10.04%|0.490|指标空值/覆盖不足|否|
|[d070](https://thesistrace.com/research-runs/run_62687a0c87f4433788ba)|QS10 1y lowvol LOO_breadth20 H10 R5|none|10/20|0.46%|5.51%|0.103|指标空值/覆盖不足|否|
|[d070](https://thesistrace.com/research-runs/run_147017bb69cf4e49a09b)|QS10 1y lowvol LOO_breadth20 H10 R5|none|20/20|-4.67%|7.98%|-0.776|指标空值/覆盖不足|否|
|[d071](https://thesistrace.com/research-runs/run_e8fcdc1e921e4e6e9986)|QS11 1y lowamount LOO_breadth60 H10 R5|none|10/20|1.84%|8.16%|0.202|指标空值/覆盖不足|否|
|[d071](https://thesistrace.com/research-runs/run_b7c13b5faf204513807a)|QS11 1y lowamount LOO_breadth60 H10 R5|none|20/20|1.04%|10.22%|0.148|指标空值/覆盖不足|否|
|[d072](https://thesistrace.com/research-runs/run_c8122e4b7e914572a01f)|QS11 1y lowamount LOO_breadth120 H10 R5|none|10/20|6.79%|12.63%|0.444|指标空值/覆盖不足|否|
|[d072](https://thesistrace.com/research-runs/run_63f6ef00c5b84c5293e1)|QS11 1y lowamount LOO_breadth120 H10 R5|none|20/20|6.13%|14.00%|0.431|指标空值/覆盖不足|否|
|[d073](https://thesistrace.com/research-runs/run_3d1cb390f66a44179d81)|QS11 1y lowamount coverage120_control H10 R5|none|10/20|2.04%|16.99%|0.206|最高组/配对差也未过|否|
|[d073](https://thesistrace.com/research-runs/run_1b92377ef53a47579fac)|QS11 1y lowamount coverage120_control H10 R5|none|20/20|3.49%|24.19%|0.274|最高组/配对差也未过|否|
|[d074](https://thesistrace.com/research-runs/run_bf75e6b2470e4e149808)|QS12 1y lowvol LOO_weak_breadth20 H10 R5|none|10/20|2.81%|10.54%|0.363|指标空值/覆盖不足|否|
|[d074](https://thesistrace.com/research-runs/run_1f0edcbe8731453a8041)|QS12 1y lowvol LOO_weak_breadth20 H10 R5|none|20/20|3.98%|11.30%|0.487|指标空值/覆盖不足|否|
|[d075](https://thesistrace.com/research-runs/run_64cbaef8c4124373a82c)|QS13 1y overnight_mom20|none|10/20|-4.49%|37.71%|0.152|原因子门槛通过|否|
|[d075](https://thesistrace.com/research-runs/run_7b73782d1631488e8d17)|QS13 1y overnight_mom20|none|20/20|-23.37%|42.10%|-0.395|原因子门槛通过|否|
|[d076](https://thesistrace.com/research-runs/run_5e28135b464b40d0a617)|QS13 1y intraday_mom20|none|10/20|15.41%|42.21%|0.547|最高组/配对差也未过|否|
|[d076](https://thesistrace.com/research-runs/run_6a38c542f88c4cb1a327)|QS13 1y intraday_mom20|none|20/20|9.51%|42.06%|0.440|最高组/配对差也未过|否|
|[d077](https://thesistrace.com/research-runs/run_aa30dc2f204a47af8d6a)|QS13 1y low_overnight_risk20|none|10/20|-2.59%|14.46%|-0.177|最高组/配对差也未过|否|
|[d077](https://thesistrace.com/research-runs/run_af2b9e8dcb4e420f8118)|QS13 1y low_overnight_risk20|none|20/20|0.46%|13.29%|0.100|最高组/配对差也未过|否|
|[d078](https://thesistrace.com/research-runs/run_32e3a504893246b1b7ed)|QS13 1y clv_volume20|none|10/20|-6.93%|40.77%|0.025|最高组/配对差也未过|否|
|[d078](https://thesistrace.com/research-runs/run_09f74d346e4c475ba72c)|QS13 1y clv_volume20|none|20/20|-14.52%|36.43%|-0.309|最高组/配对差也未过|否|
|[d079](https://thesistrace.com/research-runs/run_1c69e0e8caad492598f6)|QS13 1y amihud20|none|10/20|3.62%|33.10%|0.282|最高组/配对差也未过|否|
|[d079](https://thesistrace.com/research-runs/run_692e5affac7c42e782c7)|QS13 1y amihud20|none|20/20|-3.67%|30.40%|0.012|最高组/配对差也未过|否|
|[d080](https://thesistrace.com/research-runs/run_eac1cfcf87f94f2ab955)|QS13 1y near_high252|none|10/20|-30.45%|45.03%|-0.732|仅IC条件未过|否|
|[d080](https://thesistrace.com/research-runs/run_ff80a9845bb3416e836c)|QS13 1y near_high252|none|20/20|-13.38%|32.16%|-0.218|仅IC条件未过|否|
|[d081](https://thesistrace.com/research-runs/run_aa814c655423400bb497)|QS14 1y intraday_reversal20 H10 R20|none|10/20|-24.17%|44.97%|-0.635|原因子门槛通过|否|
|[d081](https://thesistrace.com/research-runs/run_c514e854a88a4306893d)|QS14 1y intraday_reversal20 H10 R20|none|20/20|-16.83%|37.57%|-0.434|原因子门槛通过|否|
|[d082](https://thesistrace.com/research-runs/run_62ccbec1662247099e0c)|QS14 1y clv_volume_reversal20 H10 R20|none|10/20|-9.50%|29.31%|-0.241|原因子门槛通过|否|
|[d082](https://thesistrace.com/research-runs/run_59a79ac183fe4a23bd16)|QS14 1y clv_volume_reversal20 H10 R20|none|20/20|-11.23%|32.81%|-0.341|原因子门槛通过|否|
|[d083](https://thesistrace.com/research-runs/run_ce498bb41bae4b4182dd)|QS14 1y overnight_mom20_industry H10 R20|industry|10/20|-27.74%|36.15%|-0.696|原因子门槛通过|否|
|[d083](https://thesistrace.com/research-runs/run_13708ce23eba4bed9a0c)|QS14 1y overnight_mom20_industry H10 R20|industry|20/20|5.33%|37.84%|0.331|原因子门槛通过|否|
|[d084](https://thesistrace.com/research-runs/run_bcd85d81ef374770b079)|QS15 1y wq006_strong_breadth20 H10 R10|none|10/20|-17.64%|23.94%|-1.266|指标空值/覆盖不足|否|
|[d084](https://thesistrace.com/research-runs/run_02a73e3bcfb14c34a5c6)|QS15 1y wq006_strong_breadth20 H10 R10|none|20/20|2.18%|13.22%|0.230|指标空值/覆盖不足|否|
|[d085](https://thesistrace.com/research-runs/run_b7339f39af8046599828)|QS15 1y wq006_weak_breadth20 H10 R10|none|10/20|5.64%|15.99%|0.403|指标空值/覆盖不足|否|
|[d085](https://thesistrace.com/research-runs/run_8ed2f120b90c4e7a86c0)|QS15 1y wq006_weak_breadth20 H10 R10|none|20/20|15.85%|8.47%|1.035|指标空值/覆盖不足|否|
|[d086](https://thesistrace.com/research-runs/run_3a0053684378436a80b5)|QS15 1y overnight20_percentile90 H20 R20|none|10/20|-10.17%|43.56%|-0.137|原因子门槛通过|否|
|[d086](https://thesistrace.com/research-runs/run_3f53d9cb02b6411b9540)|QS15 1y overnight20_percentile90 H20 R20|none|20/20|9.95%|27.53%|0.469|原因子门槛通过|否|
|[d087](https://thesistrace.com/research-runs/run_4fa825f36c2c4dd38254)|QS15 1y wq006_percentile90 H20 R10|none|10/20|27.11%|19.40%|1.052|原因子门槛通过|否|
|[d087](https://thesistrace.com/research-runs/run_ee66760001be4d3994bc)|QS15 1y wq006_percentile90 H20 R10|none|20/20|20.91%|18.44%|0.919|原因子门槛通过|否|
|[d088](https://thesistrace.com/research-runs/run_47ea70c439c04218a2be)|QS16 1y market_switch_amount_lowvol H10 R5|none|10/20|3.72%|12.93%|0.307|原因子门槛通过|否|
|[d088](https://thesistrace.com/research-runs/run_95532804370941fd8ea7)|QS16 1y market_switch_amount_lowvol H10 R5|none|20/20|9.44%|14.79%|0.685|原因子门槛通过|否|
|[d089](https://thesistrace.com/research-runs/run_9fd7fd8f7d2a45c29e5f)|QS16 1y common_valid_amount_cash H10 R5|none|10/20|0.89%|10.40%|0.137|指标空值/覆盖不足|否|
|[d089](https://thesistrace.com/research-runs/run_1b9a96a9c42b4d19803c)|QS16 1y common_valid_amount_cash H10 R5|none|20/20|5.23%|10.04%|0.490|指标空值/覆盖不足|否|
|[d092](https://thesistrace.com/research-runs/run_3cbd7537dd7a4a2b999d)|QS18 1y amount_cv60_low|none|10/20|-0.36%|25.58%|0.084|原因子门槛通过|否|
|[d092](https://thesistrace.com/research-runs/run_2cdc9b788a394081894a)|QS18 1y amount_cv60_low|none|20/20|7.66%|19.59%|0.507|原因子门槛通过|否|
|[d093](https://thesistrace.com/research-runs/run_c04cdea597634ddf845e)|QS18 1y amount_cv60_high|none|10/20|-27.19%|54.37%|-0.640|最高组/配对差也未过|否|
|[d093](https://thesistrace.com/research-runs/run_ada08979e69c48d98fb1)|QS18 1y amount_cv60_high|none|20/20|-22.24%|48.04%|-0.583|最高组/配对差也未过|否|
|[d094](https://thesistrace.com/research-runs/run_259b855e449c405a92da)|QS18 1y chl_spread20_low|none|10/20|-25.55%|38.85%|-1.081|最高组/配对差也未过|否|
|[d094](https://thesistrace.com/research-runs/run_d97c8080b1554041b048)|QS18 1y chl_spread20_low|none|20/20|-16.23%|26.68%|-0.702|最高组/配对差也未过|否|
|[d095](https://thesistrace.com/research-runs/run_7dab1f107d344b338c97)|QS18 1y chl_spread20_high|none|10/20|-30.32%|51.53%|-0.519|仅IC条件未过|否|
|[d095](https://thesistrace.com/research-runs/run_a13d6f846d1d4abf9e54)|QS18 1y chl_spread20_high|none|20/20|-12.68%|45.14%|-0.074|仅IC条件未过|否|
|[d096](https://thesistrace.com/research-runs/run_d4735fbfd2ba4edfa075)|QS20 1y ar1_increment60|none|10/20|16.17%|27.96%|0.574|仅IC条件未过|否|
|[d096](https://thesistrace.com/research-runs/run_9ae9e9c0213c4c4fab27)|QS20 1y ar1_increment60|none|20/20|-15.19%|32.47%|-0.260|仅IC条件未过|否|
|[d097](https://thesistrace.com/research-runs/run_41faef649cda4938ac80)|QS20 1y reversal1_ar_coverage|none|10/20|-36.99%|49.85%|-1.198|最高组/配对差也未过|否|
|[d097](https://thesistrace.com/research-runs/run_7db18cdae236482292b0)|QS20 1y reversal1_ar_coverage|none|20/20|-20.96%|37.53%|-0.569|最高组/配对差也未过|否|
|[d098](https://thesistrace.com/research-runs/run_ca1d2fa5162d4eb8bdd1)|QS20 1y historical_vol_instability20_60_low|none|10/20|4.05%|32.39%|0.288|原因子门槛通过|否|
|[d098](https://thesistrace.com/research-runs/run_9746504e8af8470380a1)|QS20 1y historical_vol_instability20_60_low|none|20/20|11.15%|27.81%|0.538|原因子门槛通过|否|
|[d099](https://thesistrace.com/research-runs/run_12ba53e001414fe0b5ff)|QS20 1y lowvol20_instability_coverage|none|10/20|4.14%|11.57%|0.426|最高组/配对差也未过|否|
|[d099](https://thesistrace.com/research-runs/run_966cdd3adfbf4876a99a)|QS20 1y lowvol20_instability_coverage|none|20/20|-0.43%|14.21%|0.015|最高组/配对差也未过|否|
|[d100](https://thesistrace.com/research-runs/run_5217e68dd8b042c895be)|QS23 1y FIP winner continuity|none|10/20|-19.52%|46.48%|-0.325|最高组/配对差也未过|否|
|[d100](https://thesistrace.com/research-runs/run_e58d282438cd45278471)|QS23 1y FIP winner continuity|none|20/20|-3.05%|42.70%|0.121|最高组/配对差也未过|否|
|[d101](https://thesistrace.com/research-runs/run_1390dec03069469995b7)|QS23 1y winner momentum matched control|none|10/20|-14.65%|45.98%|-0.036|仅IC条件未过|否|
|[d101](https://thesistrace.com/research-runs/run_f6591f2c646e40b18606)|QS23 1y winner momentum matched control|none|20/20|-21.78%|49.58%|-0.245|仅IC条件未过|否|
|[d102](https://thesistrace.com/research-runs/run_00ecac8335e84072aec0)|QS23 1y continuity formation control|none|10/20|-20.00%|48.13%|-0.369|仅IC条件未过|否|
|[d102](https://thesistrace.com/research-runs/run_eb05c3b38a3f4e92a575)|QS23 1y continuity formation control|none|20/20|-18.30%|41.95%|-0.400|仅IC条件未过|否|
|[d104](https://thesistrace.com/research-runs/run_44a49ef4a6af4836b774)|QS25 1y total_daily_skew20_low|none|10/20|8.52%|24.23%|0.490|最高组/配对差也未过|否|
|[d104](https://thesistrace.com/research-runs/run_4653447e1cb9491fad3d)|QS25 1y total_daily_skew20_low|none|20/20|1.79%|19.83%|0.192|最高组/配对差也未过|否|
|[d105](https://thesistrace.com/research-runs/run_6ecf418d55de40e580be)|QS25 1y lowmax20_skew_coverage|none|10/20|-4.44%|15.86%|-0.261|原因子门槛通过|否|
|[d105](https://thesistrace.com/research-runs/run_3bba94b76c944560b325)|QS25 1y lowmax20_skew_coverage|none|20/20|-0.12%|14.97%|0.053|原因子门槛通过|否|
|[d106](https://thesistrace.com/research-runs/run_8249230e8a2c41efaada)|QS25 1y lowvol20_skew_coverage|none|10/20|3.41%|10.62%|0.363|最高组/配对差也未过|否|
|[d106](https://thesistrace.com/research-runs/run_f439efe5c1594464b8fa)|QS25 1y lowvol20_skew_coverage|none|20/20|-0.63%|14.39%|-0.004|最高组/配对差也未过|否|
|[d107](https://thesistrace.com/research-runs/run_74da4341ee61432884f4)|QS27 1y mrat21_200|none|10/20|-31.45%|54.82%|-0.381|仅IC条件未过|否|
|[d107](https://thesistrace.com/research-runs/run_d9f6fdf019c747a38766)|QS27 1y mrat21_200|none|20/20|-31.76%|53.77%|-0.420|仅IC条件未过|否|
|[d108](https://thesistrace.com/research-runs/run_1084118cf5914384bec9)|QS27 1y momentum120_skip20_history200|none|10/20|-17.32%|49.16%|-0.091|原因子门槛通过|否|
|[d108](https://thesistrace.com/research-runs/run_77c4448588c34400b3c6)|QS27 1y momentum120_skip20_history200|none|20/20|-19.81%|50.05%|-0.204|原因子门槛通过|否|
|[d109](https://thesistrace.com/research-runs/run_2fb6708c379049e2ba4d)|QS27 1y price_to_ma200|none|10/20|-12.15%|50.64%|0.070|仅IC条件未过|否|
|[d109](https://thesistrace.com/research-runs/run_25dec76b6ff4452e8e3c)|QS27 1y price_to_ma200|none|20/20|-26.27%|51.29%|-0.288|仅IC条件未过|否|

本轮已有7个完整净值路径用50位Decimal独立核对。每242个净值点使用241个相邻收益区间，不额外添加零收益。[净值、回撤、Sharpe与费用复算](round28-nav-audits.json)。

[正Sharpe与负累计收益的账户复核](ROUND28_ACCOUNT_DIAGNOSTICS.md)。

[三组个股状态切换的固定日期独立评分复算](ROUND28_SWITCH_PROOF.md)。

[129份来源、71个精确复用案例及segment2检查点的独立清单核对](ROUND28_INVENTORY_REVIEW.md)。

[非流动性正比例变体的完整公开账户路径比较](ROUND28_SCALE_PROOF.md)。

[市场切换的固定频率对照、接近门槛的案例与长回看执行边界](ROUND28_SEGMENT3_DIAGNOSTICS.md)。

[第三段原始证据与五条净值的独立复核](ROUND28_SEGMENT3_REVIEW.md)发现一处比较范围歧义，已修正并复查。

本轮另有1次提交前准入拒绝，这些被拒绝的请求未创建回测；与随后另行接受的任务和运行失败分别记录。[逐项审查与保留原输入的恢复安排](round28-admission-resolutions.json)。

[策略首屏与Sharpe、回撤、费用帮助的四步走查](product-audit/ROUND28_METRIC_HELP_AUDIT.md)。

全年实际账户通过，才按原持仓/调仓参数跟进固定三年、近期季度及完整净值复算。季度重新建仓与全年账户截取分别报告。以上历史区间已反复参与研究，不能称作未见样本外；此审计也未执行多重检验校正或证明未来收益。

原轮次按各自协议关闭，本轮统一审计不改写旧结论，也不为某个结果较好的公式单独放宽条件。同公式、日期、数据、参数与计算契约的已完成结果复用；只有汇总值相同的不同公式不自动合并。

活跃或尚未观测任务：0；成功待采集：0；本轮失败任务：3。
