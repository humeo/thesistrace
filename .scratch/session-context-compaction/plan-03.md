# Issue 03 实施计划：首次压缩后继续回答

状态：本票已完成实现、验收及串行复审，随独立提交归档。01 `99e16db`，02 `0ca3b7a`。以下接口调查与顺序保留为实施前记录；当前证据见 [evidence-03](evidence-03.md)。整个压缩功能尚未完成，04—06待执行。

## 已核实的当前接口

- 主 Agent 的 memory 工厂仍按模型/effort缓存，`createResearchMemory` 对大窗口启用原生 OM；必须在接通新控制器时硬切换为只负责原始历史持久化/完整加载，不能并存两个调度器。
- 01 已有 `model-context` 的完整Provider输入估计与动态输出预算；辅助调用与压缩检查复用它，不新增独立估算算法。
- Mastra `ObservationalMemory` 公开只读 `observer` / `reflector`，两个 runner均有公开 `call`；当前返回类型没有完成原因，Observer存在默认内容格式化、退化重试与extractor行为，Reflector提供带marker/stream参数的调用。需要逐项验证纯候选行为，不能仅凭公开接口假设安全。
- `ResearchSessionRepository` 已有Session变更事务、所有权检查、完整消息读取、Run持久化和删除路径；当前 `durableMessages` 输出AG-UI投影，压缩必须读取保留全部Provider协议内容的Mastra原始消息，而不是浏览器消息。
- Run identity 和Continue当前追加到system指令，每Run都会改变前缀；改为稳定身份的内部消息，公开时间线与主指令分别处理。

## 实施顺序

1. **先验证候选调用边界。** 用Scripted/Fake捕获Observer/Reflector请求与返回，证明完整输入覆盖、完成原因可判定、取消有效且没有存储/marker/extractor写入。只针对已证实缺口扩展现有Mastra patch与声明；不使用私有反射、`as any`或其他摘要算法替代。
2. **定义Session快照与原始历史接口。** 在现有Agent schema/repository增加单Session checkpoint，包含revision、冻结消息/part水位、M/S固定文本、固定保留引用/连续尾部边界与安全统计。消息以稳定ID/part位置定位，原文保留。生成前只短事务读取/占用周期；提交短事务校验所有权、revision及已冻结前缀未变；追加在水位后的消息保留。Session删除级联清理快照。
3. **实现首次单批候选生成。** 从完整历史选连续约20k尾部并固定当前请求/未完成工具组，按原顺序去重；只将移出原文E交给Observer和Pi式首次S生成。M允许为空，执行状态只在S维护；超过M预算才反思。辅助调用使用当前Run模型/effort、usage、取消、剩余时限与统一预算，不挂业务工具。
4. **核验并原子发布。** 校验完成原因、结构、关键资源/请求/游标引用与文本目标；超长候选最多纠正一次。只在新完整输入低于90%且输出空间合法时提交M/S及边界。M成功S失败、取消、竞争、水位变化或预算不足都不发布半份结果。
5. **接入下一次模型调用前控制器。** 输入钩子覆盖完整工具批次、最后一个结果、新用户输入、Continue和ask_user恢复。C>=K且I>=T正常压缩；无合法D允许一次保护性周期；C<K完全禁用辅助生成。已完成回答时不提前压缩。本票只支持完整E可装入单批的首次周期，未支持的增量/多批明确失败，由04沿同一路径扩展。
6. **固定请求前缀。** 新请求按F+M+S+R+N组装；M/S仅成功提交时绝对日期渲染，R不滑动。保留全部Provider reasoning/工具配对信息。原生OM独立阈值、后台缓冲、marker与相对日期重渲染关闭，移除50条有效历史截断。内部Run/Continue消息仅保存一次且不进入浏览器用户消息。
7. **验证、复审、提交。** 先公开Run接口回归，再隔离PG验证原子性/并发/隔离/删除，以及明确失败页面。Standards→Spec串行审查，修复复审后独立提交并更新tracker。

## 本票验证与边界

- Scripted/Fake：90%以下/等于/以上、K以下/等于、无合法D、最后工具与多结果累计、单批M/S成功继续推理、M为空、Reflector条件触发、S失败/截断/取消不发布。
- 原始消息选择：多part稳定引用、工具调用结果配对、当前用户请求固定、E完整覆盖且不重复，连续后续请求复用同一M/S/R。
- PostgreSQL：生成期无长事务，revision竞争只允许一个提交，水位后追加不丢失，同用户不同Session也隔离，失败/取消/提交中断保持上一完整状态，删除清理。
- 前端：新增压缩失败原因的契约与可见错误；内部快照不经安全投影输出。
- 运行对应Agent单元/类型与隔离集成入口；不调用真实付费模型验证工程行为。真实模型摘要质量评估及最终全量check/image/browser闭环在06完成。
- 不启动崩溃Run自动续跑；不实现04的增量、多批、长轮次生成或05的长度恢复；不增加兼容、迁移、fallback，不改变dev容器/数据卷/Dataset Head。

## 2026-09-07 候选入口进度

- 公开native call已核实不满足受控候选要求：Observer单工具默认10k token裁剪且已完成调用的格式化路径不携带原始args；Reflector内部会自动升级多次生成。返回值未透传完成原因。
- 扩展已有Memory patch的ESM/CJS及公开声明，新增纯 `callCandidate`：复用Mastra提示词、解析和Agent执行；完整原始JSON，不截断，单次生成、无工具/extractors/marker/存储写入，返回finishReason与usage，取消前后检查。
- 先建立缺失入口的3项失败回归，再验证大工具完整性、空M、length无自动重试、取消、无持久化。主运行时尚未切换到新入口，快照/选择器/调度仍待实施，本票未完成或提交。
- pnpm patch首次因沙箱网络失败；获取当前锁定包后完成patch。移除工具自动加入的无关peer解析变化，仅保留Memory patch哈希更新，frozen install通过。
