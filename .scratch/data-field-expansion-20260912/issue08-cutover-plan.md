# 08 发布操作方案与执行结果

> 2026-09-14 最新状态：当前产品代码 7b3ce5b6 已部署；真实备份恢复、限定结构升级、226 字段 Head 切换、新旧研究和 Track 验收完成。正常行情、财务及行业刷新均成功，最终 Head 4c334073 和 Data 页四块、226 字段已核验。三表 4 个、指标 13 个待处理来源边界仍如实保留。最终记录已通过串行审查并提交为 260c5e2e，tracker 已关闭。事实及回执见[生产发布记录](issue08-production-release.md)；下文早期等待/失败均为历史阶段。

下文是切换前操作方案快照，不是当前执行回执；实际生产变更见上方发布记录。源、候选和历史来源资格见 [候选交接](issue07-candidate-handoff.json)，实际验证与审查见 [08 验收记录](issue08-release-verification.md)。

## 固定输入与停止条件

- 源 Head：`17f5694f6a9d47b915ffde326928b919a55181e75a4908cb661934850ac8c983`。
- 候选：`77d45ba1e49444b235308bc05fe1803e4e727532d0a8aec6e30bfe2a3b138e5d`，覆盖至 2026-09-09。
- 当前实现及main验收记录已提交至 `e2ff4e88e72239793b194d5c44eb32a601e2920a`；部署分支仅在本地从main快进，尚未推送或发布。
- 组件必须来自最终 main 集成版本及从 main 合并的部署版本；发布前填写提交 SHA、实际镜像 ID、配置校验结果，不能用镜像名称代替证据。
- 当前生产结构缺少以下三表和两列。数据库处理决策、真实依赖演练及备份恢复证明完成前，不停止线上服务、不执行部署。

## 已获授权的结构边界

生产 Core 合同为 `6f04fe84573259465442c092856b69714ed339c2093d51dcf67ba4b68aaa359f`。本功能仅增加：

1. `data.financial_indicator_report_targets`：公告报告待处理目标。
2. `data.financial_indicator_reconciliation`：每只股票已核对的日期和来源观察引用。
3. `data.financial_indicator_collections`：核对使用的采集观察记录。
4. `data.financial_daily_refresh_operations.indicator_collection`：可空 JSONB。
5. `data.financial_daily_refresh_operations.indicator_candidate_manifest_sha256`：可空摘要，带格式约束。

现有八个 Core schema 的其他 DDL 不变。三个新增表的完整约束以当前 `data/schema.sql` 为准。旧 Run、Result、Track、数据集引用均不需要重算或改写。

保留原数据库并增加上述结构属于数据库升级，不能把它改称“硬切”来规避用户“不做版本迁移”的要求。建议明确允许这一次限定源/目标的结构升级：先备份和恢复演练，单事务执行完整 DDL、结构核验和执行记录，成功后才记录新合同；失败整体回滚。重复执行必须验证已完成状态。应用继续只有当前合同，不加入运行时兼容或双读路径。

用户在本轮回复“允许”，已授权上述限定范围、保留数据的结构升级。授权不替代本地验收、备份恢复演练和结构核验；尚未执行生产升级。不允许清库，也不允许只改 schema 指纹。

## 获得结构授权且验收通过后的执行顺序

1. 复核 main 重叠文件的原始字节与现有备份，保留用户改动后集成。08 形成独立提交；部署分支只从 main 合并。目标版本验证完成后推送部署分支。
2. 已通过07验收的候选可先上传到目的服务器独立暂存目录，逐对象复核地址摘要与完整引用闭包；暂存不写生产卷。传输排除候选目录自带的旧 `HEAD.json`。合并生产卷须等待全部门禁、下述写入与清理Worker暂停，以及真实备份恢复验证完成。
3. 暂停新研究准入、Agent 提交、刷新及 Track 推进；允许现有执行按当前语义完成，核对队列和租约后停止写入组件及清理 Worker。保留 PostgreSQL、对象存储和共享网关所需网络。
4. 在受限权限的本次发布备份目录保存 PostgreSQL 备份、对象与数据引用清单、Head、组件镜像 ID、Run/Result/Track 引用摘要；验证备份可恢复。记录实际路径和 SHA-256 后才继续。
5. 再读 Head。若与固定源不同，停止发布该候选，组合已推进家族并重新验证；不得覆盖后续刷新。按获批且已演练的方案处理数据库结构。
6. 在写入及清理Worker暂停期间，将暂存内容合并进现有Canonical卷：先比较全部同名文件字节，冲突则停止；仅增加缺失文件，不删除目的文件，也不写HEAD.json。保留源数据、旧候选及全部被引用对象。同步部署当前消费者；使用现有 DatasetLifecycle 的候选保护、完整校验和 compare-and-swap 发布，expected Head 必须等于本次复核值。发布前错误保留源 Head；回执错误先读实际 Head 和操作状态，禁止盲目重试或自动回退。
7. 核对健康、226 字段及各家族覆盖，恢复入口。验证新研究固定新 Head、已有结果可读取、Track 保留 Origin/历史检查点并推进，再执行一次正常刷新，确认各家族与新增字段没有丢失。
8. 记录实际提交、镜像、备份、切换时间、前后 Head、各项验证结果。出现失败时停止新的写入，按演练过的备份与匹配镜像恢复方案处理，不清库或修改引用绕过校验。

实现提交已经产生；真实生产备份坐标和切换回执尚未产生，当前不得将此方案当作发布完成证明。

## 只读路径与空间核对

2026-09-13 UTC核对生产Compose目录为 `/opt/thesistrace/deploy`，Canonical卷宿主路径 `/var/lib/docker/volumes/thesistrace_canonical-data/_data`，容器路径 `/var/lib/thesistrace/canonical-data`；benchmark对应 `thesistrace_benchmark-data`。剩余空间164720386048字节，本地候选目录约8.1GiB。实际暂存与备份前再次检查空间。

本地候选目录的 `HEAD.json` 仍指向源17f5694f…，不代表候选已经发布。该文件绝不通过目录同步覆盖生产指针；最终候选77d45ba1…只能通过DatasetLifecycle保护及compare-and-swap发布。此次仅检查路径、空间和源文件，没有上传或改动生产。

暂存准备已获工具审批并开始执行：创建 `/opt/thesistrace-staging/field-expansion-226-77d45ba1e494/candidate-data`（父发布目录与数据目录0700），rsync排除根HEAD.json上传。传输日志 `/tmp/issue08-candidate-staging-upload.log`；当前仍待传输终态及目的内容校验。没有合并生产卷、暂停服务、变更生产数据库或发布Head。

暂存传输后续状态：原rsync已在保留断点后暂停，计划启用压缩续传以减少JSON传输量；压缩续传被自动审批拒绝，认为缺少对具体数据与目的地的明确外传授权。已向用户请求确认，当前待答复，未绕过审批或继续传输。前述“开始上传”是历史状态；目的完整性验证尚未完成。


### 候选远端暂存完成 — 2026-09-14

用户于2026-09-13T19:43:14.591Z回复“允许”，对应完整约8.6GB候选续传至 `thesistrace-contabo:/opt/thesistrace-staging/field-expansion-226-77d45ba1e494/candidate-data/`、排除根HEAD.json的具体授权。此项授权已落实，前述等待上传授权是历史状态。

压缩单流曾因SSH连接重置失败（session95827，SSH255）；重新逐文件核验后，仅续传3641个缺失或不完整文件，共1609154596字节。13个串行批次全部成功，session1774退出0，记录 `/tmp/issue08-candidate-batches-upload.log` 与 `.local/field-expansion-226-integration-backup/stream-batches-r2/`。

旧传输附带44451个AppleDouble文件（7245513字节），逐个验证格式及移动前后SHA-256后，保留至同一暂存父目录的 `candidate-upload-metadata-backup-r2/`，没有删除。正式候选最终严格核验文件集合、大小和全部SHA-256通过：71929文件、8593065687字节，无HEAD.json；候选77d45ba1e49444b235308bc05fe1803e4e727532d0a8aec6e30bfe2a3b138e5d，传输清单SHA-256为90e96508648136cc0bef5786758790a7caffde8fdccac574f7cdd8073fce345c。回执 `.local/field-expansion-226-integration-backup/candidate-transfer-verification.json`，只读验证session50131退出0。

本地部署分支仅从已核验main快进至e2ff4e88e72239793b194d5c44eb32a601e2920a；未推送。自动审批单独拒绝向 `git@github.com:humeo/thesistrace.git` 推送 `codex/contabo-deployment`，认为候选上传许可不涵盖代码外传；已单独询问用户，尚未收到该问题答复。不得用上传源码绕过此限制。

生产未暂停、未执行真实备份/结构升级、未合并Canonical卷、未发布Head。当前仅证明候选暂存完整，不证明上线完成；工单08保持未完成，真实生产备份恢复、新研究、旧结果、Track及正常刷新验收仍待执行。

## 最终执行结果 — 2026-09-14

前述等待授权和未发布描述均为历史阶段记录。授权随后获准；备份恢复、限定结构升级、候选合并、原子 Head 切换、新旧研究与 Track 验收已完成。当前代码 7b3ce5b6 已发布；正常行情、财务及行业刷新均成功，最终 Head 4c334073。全部 13 家族保留，最终 Data 页仍为四块、226 字段，财务缺口按部分就绪呈现。完整执行依据见 [生产发布记录](issue08-production-release.md) 及其回执；tracker 关闭须在最终记录审查、提交后完成。
