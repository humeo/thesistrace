# Issue 05 实施计划：截断后最多恢复一次

状态：已完成实现、验证与Standards→Spec复审，随05独立提交发布。基线04为 `b58132a`；在同一隔离worktree串行执行，证据与审查修复见evidence-05.md。

## 已确认的接入事实

- `GuardedLanguageModel` 已完整缓存 tool-call，只有合法完成原因才释放；length产生携带本次预算的 `ModelRequestFailure`，且可读text仍流入时间线。生产回归确认还必须一起保留tool-input start/delta/end，否则Mastra错误路径可从参数重建调用；完整序列在有效finish后释放。
- 当前 `RunModelObservation.requestFailure` 会阻止后续请求。恢复必须由控制器在持久化领取机会、成功压缩且确认预算改善之后显式确认；不能全局清错误或把不可恢复失败吞掉。
- 当前Mastra1.63.1公开 `processAPIError` 接收结构化错误、messageId、messageList、旋转响应ID、共享processor state，并支持有界retry。流中错误也可进入此入口。先用实际原生Agent回归验证Guard的length/上下文错误都能到达、消息独立且工具零执行，再接生产调度；不通过私有反射。
- 原生 `processOutputStep` 在业务工具之前，但terminal TripWire不保证空工具列表。本实现保留Provider的完整调用屏障；终止使用明确异常。不得以isContinued=false代替工具执行验证。
- `SessionContextController.prepare` 已实现90%正常压缩和原子快照；需要增加明确的强制恢复入口，复用同一候选流程，提交之前核验I实际下降、D改善，不在失败后发布无改善快照。
- 原生连续assistant会合并，04已给内部控制消息禁用合并。本票还需在每个主模型步骤建立独立响应边界，避免排除截断正文时误排除前一步成功工具证据。

## 实施顺序

1. **原生恢复接缝回归。** 通过Fake语言模型+真实Mastra证明结构化length和上下文拒绝进入受控恢复，完整/半份tool-call在恢复、不可恢复和耗尽分支均零执行。证明独立响应ID和历史中成功工具组保留。按证据选择公开error/output hook；只有公开入口的实际缺口才扩展已有patch，不再建外层Run重放循环。
2. **持久化恢复契约。** 在现有Session repository/PG增加ModelStepRecovery，保存所属Session/Run、逻辑步骤ID、原响应/替代响应ID、已领取次数(最多1)、原因、状态和安全预算统计。以消息关联找到同一逻辑步骤；length与context错误共用记录。所有领取/转换校验所有权及running状态，用事务与唯一约束拒绝并发。先领取后生成，取消/崩溃使恢复终止，重启不自动继续。
3. **可见审计和有效输入隔离。** 每步独立响应ID；截断可读正文在现有timeline持久化审计保留；raw Memory继续保存已完成历史，不额外注入框架未保存的失败正文，持久化排除其响应引用。主模型恢复、普通下一请求、E选择和后续M/S统一排除此类无效响应；前面成功工具步骤不被排除。原文不删除，不新增工具结果文件存储。
4. **统一强制压缩与重试。** C>=K且length的D<min(P,L)，或Provider明确context溢出，才领取一次。保存原始完整预算，复用04周期；新输入必须缩减且合法，length还要求D提高，才提交和执行替代请求。旧M/S无法装入、无E、无改善、取消/超时或候选失败终止，不能借模型/换算法/裁剪原文。辅助调用共享本Run usage/剩余时间；恢复计数不会因换错误类型或ask_user重入清零。
5. **时间线状态。** 扩展现有assistant条目投影，显示部分回答、恢复中、恢复成功或恢复失败，保存supersedes关联。仅成功的替代响应才标旧回答已替代；失败仍保留部分正文和安全错误。持久化写入必须抵抗后到文本事件覆盖恢复状态。小窗口直接报错不显示正在恢复；已成功业务回执保持可见并提示不要重复提交。
6. **验证与交付。** 同步当前Schema/catalog/grants和契约，使用隔离生成入口，不迁移dev。受影响测试/typecheck、真实PG并发/重入/重启、组件与隔离浏览器流程；Standards→Spec串行审查、修复复审、tracker和独立提交。06随后执行最终全产品验收。

## 必须证明的边界

- Full P(包括P<L)耗尽不恢复；D受输入限制才允许length恢复；C<K所有路径零辅助/零重试。
- length→context及context→length交替仍只有一次；并发领取只有一个成功，ask_user不重置同逻辑步骤，新的prompt/Continue是新Run。
- 强制压缩发布前确认缩减和输出改善，无改善不得先推进快照再失败。
- 三条length分支不执行业务工具；此前成功操作只一次；未完成参数不执行。
- 旧部分正文可重放显示但不在恢复Provider payload或Observer/S输入；独立替代消息和supersedes在刷新后相同。
- 取消和Provider/Run时限终止整个周期，原文/旧成功快照/新模型选择保留。日志只记录次数、预算、usage和耗时。

## 当前范围

不增加兼容、迁移、fallback、自动回切或崩溃续跑。保留原main工作区与thesistrace-dev容器、卷和Dataset Head。浏览器验收仅操作隔离环境。工程Fake通过不表示真实模型摘要/缓存效果通过，后者属于06。
