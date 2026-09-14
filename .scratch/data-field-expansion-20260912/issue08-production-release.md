# 08 生产发布与真实验收 — 2026-09-14

当前状态：代码、结构与 226 字段候选已发布；新研究、旧结果、原始引用保留和 Track 推进已通过。行情、财务及行业正常刷新均成功，最终 Head `4c334073` 与生产 Data 页核验通过；交付记录待最终审查、提交后关闭本票。下文按阶段保留失败、修复与恢复历史，最终结果见文末。

## 发布坐标

- 首次上线的 main、由 main 快进的部署分支及服务器 checkout：`142579e745d42beed2c4af4e14d24109d0466d71`。用户明确允许将部署分支推送到 `humeo/thesistrace` 后，实际 push 成功；没有 force 或 cherry-pick。
- 当前生产产品代码：`7b3ce5b6e7f97ef60616667269fbdf2a56b5c424`；后续修复同样经 main → 部署分支 → 服务器发布。最终 Head：`4c334073604bd7f6fc96515436aad6e41a4a766e6190739b98f9aeeb6efe9bfe`。
- 生产原版本：`b8359978ad8167e291a0fbe846268600b4183d89`。旧配置和镜像ID在受限目录保留。
- 原Head：`17f5694f6a9d47b915ffde326928b919a55181e75a4908cb661934850ac8c983`。
- 初始226字段发布候选：`77d45ba1e49444b235308bc05fe1803e4e727532d0a8aec6e30bfe2a3b138e5d`，身份`e42809eec3faf8157ed0cb9f1000ee9ef61abcb4cab8b44f3633b55baefe0840`。
- 后续正常行情刷新Head：`079283e9858c3c9d1b656e8fd2e1274fa868f0fe24f39636712aff53c1c97e50`，覆盖2010-01-04至2026-09-11，4055交易日。该Head是正常后续发布，不能再将77d45ba1称为当前Head。

## 真实备份与恢复

服务器备份目录：`/opt/thesistrace-staging/field-expansion-226-77d45ba1e494/release-backup-142579e7/`，权限受限。未将数据库备份、角色凭证或配置上传到Git。

暂停入口、Agent/API/Auth及研究、Track、刷新和清理Worker；核验无在途操作后生成真实生产数据库备份，91表、4668226字节，SHA-256 `c700cee4e81489f014b3e7474b5614cb814d2763b0416c1f1ea767fca126b071`。在无网络、无生产挂载的独立PostgreSQL中恢复，逐表行数及排序内容SHA-256全部一致，原Core结构合同一致。只清理本次隔离恢复容器，生产数据库和卷未删除。

Canonical 23946文件、Benchmark 2文件、RustFS 6651文件均归档、比较、解压及逐文件SHA-256核验通过。RustFS仅为取得一致备份短暂停止，之后恢复。详见[真实备份恢复回执](evidence/issue08-production/backup-restore-receipt.json)。

## 结构、数据及服务切换

仅执行用户明确批准的三表两列升级，源`6f04fe84573259465442c092856b69714ed339c2093d51dcf67ba4b68aaa359f`、目标`624c319e2f0a11425c5a5219d8125a10234c6885ae66531df57cd384e589a693`。preflight validated，apply applied，复核already_current；未改写业务记录，未增加运行时兼容分支。回执见[应用](evidence/issue08-production/schema-upgrade-apply.json)和[复核](evidence/issue08-production/schema-upgrade-verify.json)。

候选合并前先验证全部同名文件；23945匹配，新增47984文件/5911680291字节，原23946文件（含Head）逐个确认原字节不变，无删除和覆盖。详见[合并回执](evidence/issue08-production/candidate-merge-receipt.json)。

使用DatasetLifecycle.protect_candidate执行系统完整内容验证，再compare_and_swap_head，expected为实际复核的原Head；操作`field-expansion-226-cutover-142579e7`。全历史内容验证耗时较长，在原进程仍持续计算时，仅通过现有接口为同一候选续期保护至7200秒，没有中断、跳过验证或重复发布。session95115最终退出0，实际Head与回执一致。Head中的prepared_at来自候选准备时间，不代表实际切换时间。详见[原子发布回执](evidence/issue08-production/publish-head.json)。

仅更新Auth/Agent镜像标识和Agent build revision三项配置，其余生产设置保持原值。使用已构建镜像一次启动全部当前消费者；初始化退出0，API/Auth/Agent/Web/维护Worker/Postgres/RustFS健康，其余Worker运行。详见[旧镜像坐标](evidence/issue08-production/prebuild-receipt.json)和[新服务回执](evidence/issue08-production/production-start-receipt.json)。

## 生产浏览器及数据引用验收

- `/data`：原四个数据区块保留，daily 7/7、daily_basic 15/15、三表41/41、fina_indicator 163/163，合计226。中文“经营现金流”配合TTM期间过滤得到2字段；`pe_ttm`配合Daily basic/估值过滤得到唯一字段。行情先推进后，页面正确显示财务Partial和行业stale，并仍列226作者入口，没有伪报全量同日就绪。
- 新研究[run_1a51695777914bbab0a4](https://thesistrace.com/research-runs/run_1a51695777914bbab0a4)：`rank(total_mv) + rank(roe) + rank(operating_cash_flow_ttm)`；2026-08-03至09-09、Top300、无中性化、Factor Evaluation。真实Worker succeeded，28/28交易日，约10秒，页面展示各期IC和覆盖。Attempt固定77d45ba1候选。
- 旧研究[run_0de6565a394e4c389c60](https://thesistrace.com/research-runs/run_0de6565a394e4c389c60)：既有策略结果、因子摘要和图表正常读取，Attempt仍固定旧Generation `4723b071313705df8662131f4ec4137e4cf35a9680a7c63c1a0191eb66e83e7f`。
- 已有[Track](https://thesistrace.com/daily-tracks/track_5588d5af145043aba4cd)：正常Refresh从2026-08-27推进至09-09，9个新增交易日，Attempt固定77d45ba1。正常行情刷新后再次Refresh成功推进至09-11，页面Up to date，11个交易日观察、12个含初始点的观察记录，Origin仍08-27。
- 生产旧研究行、旧Attempt行、初始检查点行的排序SHA-256与真实备份完全相同；直接从服务器本地备份提取Track Origin并比较，内容相同。备份没有为此跨主机传输。详见[保留性回执](evidence/issue08-production/postcutover-retention-receipt.json)。

## 切换后正常刷新

`field226-postcutover-market-20260914`正常Data Operator行情刷新succeeded/published，as_of为2026-09-14T03:00:00Z，数据推进至09-11。全部13个家族保留，financial_pit与financial_indicator引用逐项完全一致；详见[行情刷新后家族回执](evidence/issue08-production/postrefresh-families-receipt.json)。

为使财务与行业覆盖追上行情，已提交财务刷新`field226-postcutover-financial-20260911`；其终态及后续行业刷新仍待记录。服务已恢复，后续刷新在正常后台流程执行。

## 初次切换后的待办（历史阶段）

财务与行业正常刷新终态、最终Head/覆盖核验、最终tracker与独立提交。此前完整产品门禁的失败/修复与通过边界见[统一验收记录](issue08-release-verification.md)，本文件不将单次check:release声明为零退出。

## 财务刷新上线回归修复

首次财务刷新自动尝试3次后为`failed / RETRY_EXHAUSTED`，末次根因分类`REFRESH_INFRASTRUCTURE_FAILURE`。服务器本地结构化日志聚合确认3次均为`KeyError`；只回传错误类型、阶段和计数，未导出原始生产日志。只读数据库聚合确认当前操作已保存discovery和indicator_collection，尚未构建指标/三表候选；查询范围内1条仅三表历史记录没有`instrument_ids`，1条已采集指标记录有完整映射。

使用既有TestRun隔离PostgreSQL和正常`DailyFinancialRefreshService.publish`构造同样历史边界。最初两次测试收集因辅助模块路径失败，第三次因测试历史行不满足发现证据约束失败；修正测试设置后，运行`20260914t042416z-4582-b433b235`准确复现`daily_financial_refresh.py`读取`instrument_ids`的KeyError：2失败、2通过。修复仅将指标发现证据限定为`indicator_collection IS NOT NULL`的刷新记录；不修改旧记录，不按新旧版本分支，不排除同日新发现。

运行`20260914t042505z-4892-97d34f4e`四个真实数据库场景全部通过（8.91秒），覆盖仅三表历史记录有/无、指标立即启动/延迟补齐；原有跨发布历史证据和轮转覆盖断言继续成立。两份Python的ruff检查、git diff --check通过。Standards和Spec冻结串行审查均0项发现。独立修复提交`7017713a41a9b2a86f92a5d1eca0d98dd8a14fd5`已快进main；main隔离复验`20260914t042748z-5747-26d5a830`四项通过（9.81秒）。随后仅从main快进部署分支并push成功，生产重试结果待后续记录。

修复已在生产部署完成，Core各服务重新构建并正常启动，初始化退出0、API及原有Auth/Agent/Web健康；配置字节不变，详见[修复部署回执](evidence/issue08-production/financial-fix-deployment-receipt.json)。真实浏览器重新打开混合字段研究，结果仍succeeded且可读取。

已通过现有`DataRefreshService.retry`从原失败操作创建显式重试`field226-postcutover-financial-20260911-retry-7017713a`，保留原失败记录；目标仍2026-09-11，没有手改状态或Head。指标采集已完成，聚合账本154条，当时仍在候选构建阶段，首次执行无失败码；最终回执确认没有生成新的指标候选。运行871秒时心跳年龄30秒，候选尚未保存；先前资源观测约103%CPU、243MiB内存。此处仅为进度证据，不能据此声明发布成功。最终财务及行业刷新终态仍待记录。

运行1995秒时观察到本次重试已新增18个Parquet对象、2818065字节，任务仍running、心跳年龄12秒、无失败码。相比此前0个新增对象，构建已产生实际文件进展；这仍不代替候选发布终态。


## 新市场身份初始指标采集修复

上述显式重试最终 succeeded/degraded，完成于2026-09-14T05:13:26.737112Z；三表候选已发布，指标候选未生成。Head推进到`c8596320a81163f1605caf2bb29bceaa2cbf2e1be9fdfd21acffceb987f82dbf`，三表发现覆盖09-11，但指标仍覆盖09-09。新Parquet对象只能证明文件构建进展，不能作为指标发布证据。三表有4个canonical_projection拒绝（FINANCIAL_DAILY_INSTRUMENT_INVALID），指标采集失败0、待处理13；这些待处理值保持缺失。

只读生产聚合确认行情身份5552、指标身份5550，差额2个身份均已在截止日前上市，却未进入本次77个采集目标。原因是初始历史采集只依赖公告触发或64个后台轮询额度；新身份未入选时，完整家族覆盖不能推进。修复从已有指标候选的身份映射识别已上市新增身份，优先与pending、轮询目标合并去重；采集失败时仍保持缺失并由后续正常操作继续处理，无运行时版本兼容路径。

真实数据库回归先排除listed_to测试fixture错误，再在`20260914t051930z-15552-934399e9`复现新增身份未被请求（实际只请求000002）；修复后`20260914t052106z-16070-60552c98`六项通过（13.07秒）。四份Python的ruff及diff格式检查通过，冻结Standards→Spec串行审查均0项发现。独立提交`4083a2bac1b406be63b2b4e6f66ee678fdf643ae`已快进main并保留无关改动；main复验`20260914t053059z-18058-55cc427c`六项通过（10.37秒），隔离资源清理成功。部署分支仅从main快进，GitHub推送成功；生产部署及新一轮普通财务刷新结果继续记录。

生产修复4083a2ba已部署，构建与启动均通过，初始化退出0，API/Auth/Agent/Web及基础服务健康，配置字节保持不变。见[新增身份修复部署回执](evidence/issue08-production/new-identity-fix-deployment-receipt.json)。已正常提交`field226-postcutover-financial-new-identities-4083a2ba`，目标2026-09-11，返回accepted；此为上一成功降级操作之后的正常刷新，保留原失败和成功操作记录，不修改状态绕过流程。

生产冻结计划只读核验确认新增身份2个、采集目标79个、新增身份全部入选；见[计划汇总回执](evidence/issue08-production/new-identity-dispatch-receipt.json)。该证据证明优先调度修复已在真实环境生效，不代替财务候选发布与覆盖核验。

后续只读账本核验进一步确认两个新增身份均已reconciled through 2026-09-11，不只是进入计划。待处理报告目标13个，其中7个report_period为空；其余6个只能确定仍未解决，尚不能仅凭账本将原因定为供应商缺失。首次只读辅助脚本因未打开连接池失败，补上现有open/close后查询成功；不是生产刷新失败。此时刷新仍running、attempt 1，未保存完整指标候选。

对本次已保存采集证据作服务器本地只读比对，13项待处理目标分类已明确：7项缺少报告期，6项有对应报告期但观察到的ann_date不满足目标announced_on至截止日的匹配条件。没有把旧公告的指标强行认作新公告数据，也不将本次无匹配解释为供应商永久缺失。见[指标待处理分类回执](evidence/issue08-production/indicator-pending-classification.json)。

运行2290秒时任务仍running、attempt 1、心跳年龄3秒且无失败码；本次提交时间之后的objects目录出现1个新Parquet对象、49916字节。该计数只作为文件构建活动证据，不代表完整指标候选或Head已经发布。

运行2451秒时指标候选、三表候选均已保存，4个报表处理检查点已记录；任务仍running、无失败码。只读reopen已保存指标候选`42b600f7479ea940643eebef4fab9aefc4379e682069155e4f5422641c332d7a`确认5552个身份、163字段、2010-01-04至2026-09-11、13个未解决来源目标。首次元数据辅助脚本误用家族descriptor的dataset_coverage键，修正为候选的research_sessions/instrument_ids字段后核验成功。见[新增身份候选回执](evidence/issue08-production/new-identity-candidate-receipt.json)。同期实际Head仍c8596320，全部13家族保留、10个非目标家族与行情刷新后引用相同；该候选证据不能替代最终Head发布。

## 完整发布验证内存故障 — 2026-09-14

本次操作在约89分钟后中断。内核2026-09-14T07:02:12.021411Z的global_oom事件明确匹配Data Operator Worker容器，确认首次中断为宿主机内存耗尽。当前docker inspect曾显示OOMKilled=false、exit 2，指向后续租约尚有效时的启动失败，不能据此排除首次OOM；最初“未发生OOM”判断已被内核证据纠正。后续日志仅OPERATOR_FAILURE，租约心跳停止但900秒有效期尚未结束。其余API/Auth/Agent/Web、研究、Track、Postgres/RustFS健康，无重启。

实际Head仍c8596320，未发布新候选；13家族和10个非目标引用保留。指标候选42b600f7及三表候选均已保存。为避免租约到期自动重跑再次耗尽宿主机内存，已停止单一data-operator-worker容器；不删除数据、卷或候选，不编辑任务/租约状态，其他服务保持运行。见[OOM核验回执](evidence/issue08-production/financial-publication-oom-receipt.json)。

下一步计划：基于当前完整验证调用链及保留的真实候选定位内存峰值；在隔离环境保留复现/资源证据，修复时维持完整内容验证和当前合同，不跳过验证或手工切Head。通过相关验证与Standards→Spec串行审查后独立提交、main复验并依发布顺序部署，再让已有恢复机制接续同一任务。财务和行业验收仍未完成，08不得关闭。


## 内存修复部署与原任务恢复 — 2026-09-14

修复提交 `7b3ce5b6` 已经 main → 部署分支 → 服务器一致发布。6,000 版本失败回归修复后通过；main 144 项数据测试、6 项隔离 PostgreSQL 测试通过；Standards → Spec 串行审查均 0 项发现。完整 1,242,613 行候选验证在 1,010.43 秒完成，峰值 688.69 MiB，退出 0。详细记录见 [内存修复验收](issue08-financial-memory-fix.md)。

服务恢复成功，配置摘要未变，初始化退出 0，其余服务正常运行。原财务任务 `field226-postcutover-financial-new-identities-4083a2ba` 按既有机制恢复为第 2 次执行，heartbeat age 10 秒，未记录失败码，三表及指标候选继续保留；尚未保存组合 generation。恢复后的首次 Worker 采样 CPU 92.17%、内存 238.3 MiB。没有新建替代任务或手改状态。

浏览器重载确认新字段研究 `run_1a51695777914bbab0a4` 仍 succeeded、28/28；切换前研究 `run_0de6565a394e4c389c60` 仍 succeeded、19/19，结果摘要与图表可读。最终组合 Head、财务刷新终态及行业刷新仍待完成，08 不关闭。

同一发布版本下 DailyTrack 浏览器确认：起点仍为 2026-08-27，Last observation/Data available through 均 2026-09-11，Up to date，11 个交易日、12 条观察记录。

## 原财务任务恢复成功与行业刷新受理 — 2026-09-14

原财务任务第 2 次执行已 `succeeded`，组合 generation 已保存并发布为 Head `cd5d70e0c6e20fd5b43c3512147ae0cf6d1cb6f070d65f254126ed25e14584c8`。重新读取实际 Head 确认全部 13 家族保留，10 个非目标家族与正常行情刷新后的引用完全一致；指标候选 `42b600f7` 已进入 Head，覆盖 5,552 个身份、2010-01-04 至 2026-09-11。指标 complete-through 为 2026-09-03，13 个待处理目标仍保留；三表候选 `efc7ee66` 的发现完成日为 2026-09-11，4 个未通过版本验证的更新仍待处理，未强行覆盖已有事实。见 [财务成功回执](evidence/issue08-production/postcutover-financial-success.json)。

确认上述成功终态、当前交易日及四个关键家族后，正式提交行业任务 `field226-postcutover-industry-20260911-7b3ce5b6`，目标 2026-09-11，服务返回 `accepted`。行业终态、最终 Head/UI 及工单收尾仍待核验，08 继续保持未完成。

## 正常刷新与最终页面验收完成 — 2026-09-14

行业任务首次执行成功，最终 Head 为 `4c334073604bd7f6fc96515436aad6e41a4a766e6190739b98f9aeeb6efe9bfe`；行业家族 `e77870cf` 覆盖至 2026-09-11，成员记录数 5,551。与刚发布的财务 Head 逐一比较，全部 12 个非行业家族引用和覆盖均相同；与行情刷新后比较，10 个非目标家族不变。见 [行业成功回执](evidence/issue08-production/postcutover-industry-success.json)。

最终生产 Data 页经真实浏览器读取与截图确认：四个顶层区块不变，226 available，行情 22、财务 204；daily 7、daily_basic 15、三表 41、指标 163。Market 和 Industry ready，行业观察截至 2026-09-11；Financial 显示 partially ready，三表 pending 4，指标完整覆盖日显示 2026-09-03，未把 observed-through 2026-09-11 伪称为全部完整。见 [最终 Data 页回执](evidence/issue08-production/final-data-browser.json)。

至此真实生产新研究、旧结果、Track 推进及行情/财务/行业正常刷新链路均已验收。剩余工作为交付记录最终串行审查、独立提交与 tracker 关闭；不再以未完成的运行任务阻挡收尾。

## 最终交付记录审查

30 文件（7 份 Markdown、23 份 JSON）的冻结 working-tree 快照按 Standards → Spec 串行审查。Standards 首轮发现 P3：部分顶部当前摘要残留过期状态；修正三个文档的当前摘要与历史阶段标记后，R2 确认该项关闭且新增 0。Spec 审查 0 项新增偏差，核对家族引用保留、四块及 226 字段、真实 pending 与分阶段门禁边界。

全部记录链接有效，23 份 JSON 可解析，git diff --check 通过；07 交接中的 19 个历史证据哈希重新校验一致，226 字段及 19 个 TTM 计数相符。8 票均存在 Plan 与独立实现提交，01—07 已 complete；08 代码及后续修复已提交并部署。本记录独立提交后再按 tracker 规则关闭最终交付项与母规格。
