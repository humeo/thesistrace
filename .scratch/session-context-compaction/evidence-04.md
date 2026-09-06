# Issue 04 实施证据

状态：进行中，未复审、未提交，不能标 complete。实施前计划见 [plan-04](plan-04.md)。基线为03独立提交 `08bddce`。

## 增量原文和首次后续周期（2026-09-07）

- `selectContextHistory` 增加前一快照有效引用选择：所有引用仍指向原始 message/part，稀疏part不重新编号；已处理历史排除，解除固定的旧请求只入E一次。普通恢复仍使用固定R和水位后追加原文。
- 失败回归 /tmp/thesistrace-ticket04-selection-red.log 后修复，selection 5 passed。
- 生成器硬切换为 `generateSessionContext`：Observer读取旧M并产生新增观察；增量S读取旧S、新E和候选M，采用更新提示词。首次模板仍共用同一路径。没有保留旧名字的兼容入口。
- 增量生成先失败 /tmp/thesistrace-ticket04-generation-red.log，修复后generation12 + selection5 =17 passed。
- 控制器移除已有checkpoint时的一次性限制，核验领取周期revision一致，按旧快照选择有效E/R，候选仍一次原子发布。第二周期回归先失败 /tmp/thesistrace-ticket04-controller-red.log，再修复到controller16 passed，日志 /tmp/thesistrace-ticket04-controller-green.log。Agent typecheck通过。
- 公开Run隔离PostgreSQL验证首次发布、重启固定前缀以及第二周期revision=2；旧已摘要正文不再进入Observer，新E送入Observer，旧S参与更新；原始消息始终保留。1 passed /74 skipped，exit0，日志 /tmp/thesistrace-ticket04-second-cycle-pg.log。这是针对性回归，不宣称全PG套件已重跑。

## 当前剩余工作

- 按完整辅助请求预算分批，单条超长中文原文分段与来源覆盖。
- 逐批M反思、读取全部原始E的增量S，以及长轮次前半段独立摘要/合成。
- 多批部分失败、取消、并发、Continue/ask_user/跨日期/模型切换与小窗口零辅助的完整验收。
- Standards→Spec串行审查、修复复审、tracker、独立提交。05与06未开始。

## 辅助请求准备入口

新增 Observer.getCandidateInput 纯入口用于完整输入预算，callCandidate 使用同一消息构造。缺失入口回归先失败；实现后实际Provider对比仍失败，定位为原生TokenCounter会给输入消息附加内部tokenEstimate字段。候选计数改对structuredClone副本进行，不再变更原文。ESM/CJS与声明同步，正在冻结安装及验证；尚未接入完整分批器。

- 准备/执行对比在修复计数副作用后只剩Mastra本地createdAt差异，该字段Provider不接收；测试同时比较去除内部元数据的正文和统一tokenx预算，并验证输入原文不变。相关4文件43 passed，/tmp/thesistrace-ticket04-current-tests-green.log；typecheck通过。冻结安装通过，lock diff仅Memory patch哈希3处引用，无包版本变化。


## 完整分批与长轮次（2026-09-07）

- 新增 ContextEvidenceBatches，按完整消息/跨消息工具组选择普通批次；超长单组仅在辅助输入序列化后分段，片段携带来源引用、UTF-16偏移和总长度，Unicode代理对不切断。完成位置显式校验，预算拒绝/取消不推进位置。
- Observer逐批读取新E，合并M并逐批检查Reflector阈值；S独立再读取全部原始E，使用旧S更新。辅助分批预留两倍文本目标用于正文和推理，实际输出仍受01的动态预算约束；不改变90%主模型触发线。
- 长轮次分别摘要更早历史和当前轮次前半段，再生成一份预算内S。工具组跨边界时保持同组。所有中间产物均为局部候选，最终仍只有一次提交。
- 分批3项和长轮次失败回归修复后，generation13+controller16+batches3=32 passed，Agent typecheck通过。日志 /tmp/thesistrace-ticket04-long-turn-red.log 与 /tmp/thesistrace-ticket04-long-turn-green.log。
- 全Agent单元612 passed，隔离PG75 passed，日志 /tmp/thesistrace-ticket04-unit-full.log、/tmp/thesistrace-ticket04-pg-full.log。
- 后续补充后批次取消/S失败、跨日期固定前缀、小窗口I=55000超过90%但D合法继续、过大输入拒绝且旧快照不变。controller17+generation15=32 passed，/tmp/thesistrace-ticket04-boundaries.log。
- 当前数据契约中的data_generation_id/research_run_id/batch_id/track_id/folder_id/folder_cursor已补入精确引用校验，先失败再修复，针对性回归1 passed。
- 真实Run拓展到180条历史，Observer和S均多批，随后重启、第二周期、小窗口可用/过小拒绝和保留新模型选择均通过：1 passed/74 skipped，/tmp/thesistrace-ticket04-multibatch-pg.log。
- ask_user跨重启恢复正在验证；Continue、权限变更、逐批条件反思的额外验收及串行review尚未完成，本票未提交。


## ask_user 恢复缺陷及修复

- 长历史流程的ask_user回答在Host重启后返回CONTEXT_COMPACTION_FAILED；原始失败 /tmp/thesistrace-ticket04-ask-user-pg.log。缩小到20条历史、一次压缩和一次问题后仍失败（2.72s），/tmp/thesistrace-ticket04-ask-minimal.log。
- 排查水位、身份、协议三个假设。安全探针确认CONTEXT_SOURCE_CHANGED，消息顺序/头部未变；最终证明part的JSON键从type/text变为text/type，反转键序后的哈希与旧水位完全匹配。正文未改变。探针日志 /tmp/thesistrace-ticket04-ask-order-probe.log，仅输出键名和布尔值。
- 水位改用规范JSON对象键顺序；提取复用Session repository已有canonicalJson，不增加兼容/迁移或忽略正文/协议字段。数组和文本顺序仍受保护。
- 键序回归先失败 /tmp/thesistrace-ticket04-key-order-red.log，修复后state+controller21 passed。原文改写拒绝断言继续通过。
- 最小及完整180条多批/第二周期/模型切换/ask_user重启流程一起2 passed/74 skipped，/tmp/thesistrace-ticket04-ask-fixed.log；Provider可见前缀逐项一致，旧快照不改写，同Run内部标识只一条。所有DEBUG-context-resume诊断代码已删除。
- 本票仍待Continue、权限变化、逐批条件反思验收和串行复审，未提交或标complete。

## Continue 与最终审查前回归

- Continue 初次入口失败是测试默认模型未注册；修正后暴露内部控制消息被合并。加入实际 Provider 请求断言后证明模型已执行，而内部 ID 丢失；失败 /tmp/thesistrace-ticket04-continue-provider-red.log（75 passed / 1 failed）。
- 原因：Mastra MessageList 默认合并连续 assistant 消息。内部控制消息使用现有 add(..., { merge: false })，仍沿用原生响应边界旋转。完整压缩/重启/ask_user/Continue/权限撤销流程通过，/tmp/thesistrace-ticket04-continue-fixed.log（1 passed / 75 skipped）。Continue 没有新增用户消息、重复工具操作或重复内部 ID。
- 新增逐批条件 Reflector 验证：第一批低于预算不 Reflect，第二批合并超限才 Reflect，后续批次读取精简 M；旧 M 无法进入合法辅助请求时零调用且明确失败。generation17 passed，/tmp/thesistrace-ticket04-reflect-check.log。
- 真实 PostgreSQL 增量周期加入 M 成功而 S 无效：旧 revision 和原始增量证据保持，下一次请求重新处理并发布 revision2。既有 PostgreSQL claim/revision/并发追加/取消/重启契约继续覆盖原子性。
- 最终审查前 Agent 单元619 passed、隔离PG76 passed、ChatTimeline16 passed；日志 /tmp/thesistrace-ticket04-unit-final.log、/tmp/thesistrace-ticket04-pg-final.log、/tmp/thesistrace-ticket04-ui.log。
- typecheck 首次发现测试 UUID 模板类型与持久化 string 不匹配，显式 string[] 修复后通过，/tmp/thesistrace-ticket04-typecheck-final-r2.log。无运行逻辑变化。
- 尚待 Standards→Spec 串行审查、修复复审、tracker 和独立提交。本票未 complete，05/06尚未开始；未运行最终镜像/真实浏览器/真实模型保真度验收。

## 第04项交付结论

捕获工作区范围 `/tmp/thesistrace-ticket04-review`（基线08bddce）。Standards与Spec严格串行，均0 findings，无待修复项。Agent619、隔离PG76、ChatTimeline16、typecheck和diff whitespace通过。tracker随本票独立提交完成；05长度恢复/UI与06最终验收尚未交付，整个spec/goal保持未完成。
