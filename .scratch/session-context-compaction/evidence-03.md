# Issue 03 验证记录

状态：实施中，未完成、未提交。

## 候选生成入口

已用安装版本源码确认原生Observer/Reflector call的缺口：默认工具截断、已完成工具参数不完整格式化、内部重试/Extractor路径以及完成原因未透传。纯候选入口仅扩展现有固定版本patch，原有logger和resume历史修复仍保留，ESM/CJS声明与执行同时更新。

- 新增入口前：3项回归因callCandidate不存在而失败，记录真实red阶段。
- `pnpm --dir agent exec vitest run src/compaction-candidates.test.ts src/research-memory.test.ts src/guarded-language-model.test.ts`：69 passed，3文件。
- `pnpm --dir agent typecheck`：通过。
- 覆盖完整大工具结果及参数、空M与usage、length原样透传且无内部重试、取消前不请求、无OM/消息记录写入，以及ESM/CJS两种模块格式。
- Provider拒绝/终止回归会输出测试模型的预期OUTPUT_LIMIT异常；用例通过，不代表实际主运行时压缩已接通。
- frozen依赖安装通过，锁文件仅保留本次Memory patch哈希的变化，不升级依赖。

## Session 快照存储验证（2026-09-07）

- 新增 Session checkpoint Schema、权限和生成后的精确 catalog 契约；空 revision 不能附带快照，已发布 revision 必须包含非空 JSON 对象。Session 删除级联清理，Run 引用不会单独级联删除已发布快照。
- Repository 提供原始 Mastra 消息读取、周期占用、原子发布及有身份的释放；生成期间不持有事务。冻结消息头和每个 part 的哈希允许后续追加，拒绝已处理原文改写。
- 首次隔离 PG 测试发现 agent_run 没有 researcher_id 列（退出码 1，证据 `/var/folders/py/j9ws8lpn57g_syngj3b58b6h0000gn/T/thesistrace-agent-test.8vCUBA`）；修复为先锁定校验所属 Session，再以 Run/thread 联合查询。
- 增加真正的双 Repository 并发占用、无效 S 不发布、追加消息保留、重复提交拒绝、过期释放不影响新占用、源文改写拒绝、Host 重启保留快照并清理占用、删除级联。
- 最终定向隔离 PG：`pnpm --dir agent test:integration src/research-runtime.integration.test.ts -t 'publishes complete context snapshots'`：1 passed / 64 skipped，退出码 0；项目 `thesistrace-agent-test-20260906t190732z-61070-4a97e1b2`。没有声明整个集成套件通过。

## 原文选择与固定尾部（2026-09-07）

- 新增选择器：近期连续 part 尾部、当前用户请求、未完成工具交互取并集；以工具身份和推理/工具 step 补齐协议组，完整消息附件/Provider envelope 不拆成两份。
- E/R 按原顺序分区，不改原始消息；恢复按发布时固定引用加水位后的新增 part/消息组装，不重新滑动窗口。
- 共用 ModelInputTokenCounter 的 tokenx 序列化估计，不引入第二种估算算法；最终完整 Provider 预算仍须由控制器核验。
- 红阶段：选择器模块不存在导致回归 suite 失败（退出码 1）；实现后选择器 3 项、水位 2 项、Provider 保护 58 项，合计 63 passed；typecheck 通过。
- 水位额外拒绝在冻结消息前/中间插入新消息，避免已发布前缀改序。覆盖正常追加、重写拒绝和固定引用恢复。

## 尚未完成

首次M/S控制器、固定前缀/内部Run消息、关闭原生独立调度和公开Run闭环验收尚未实施。新入口目前不改变主运行时调度行为；本票不能标complete。

## 首次单批 M/S 候选生成（2026-09-07）

- 新增 generateInitialSessionContext：Observer 完整 E、超预算时 Reflector、独立结构化首次 S；只生成候选，不接触 checkpoint 发布或业务工具。
- 复用当前 Run 的 memoryLanguageModel/effort、Guarded Provider 预算/usage、取消和单步超时；S 读取原始 E，M 和当前请求仅作为一致性/目标参考。
- 校验 stop 完成原因、六节结构及非空内容、调用方指定的准确续读引用、文本预算；超长候选最多一次纠正。空 M 合法。S 失败、取消、Provider 长度停止、无合法辅助请求空间均不返回可发布候选。
- 反思用例初始重复文本触发 Mastra 退化校验（5 passed / 1 failed），改为 1500 条不同事实验证预算反思边界。没有绕过退化校验。
- 最终：`pnpm --dir agent exec vitest run src/session-context-generation.test.ts src/compaction-candidates.test.ts`，18 passed（11 + 7）；typecheck 和 diff whitespace 检查通过。
- 这证明辅助生成边界，不证明公开 Run 的 90% 调度、候选提交或固定前缀已经接通。下一步是完整请求预算与原子发布控制器，以及固定前缀/内部 Run 消息。

## 完整请求预算与发布控制器（2026-09-07）

- 新增 SessionContextController：以最终 Provider-shaped request 计数，低于 90% 且有输出空间则继续；工具定义同时计数。首周期生成后核验新请求低于 T、有合法 D，随后提交 M/S 固定渲染文本与原文边界。失败/取消/仍超预算时释放周期且不发布候选。
- 普通请求读取已发布快照，复用固定 M/S 文本与原文引用。主输出期望额度不在控制器提前缩小，仍交给 Provider guard 推导 D，保留以后长度恢复所需的期望额度。
- 通过 Mastra MessageList 原生转换重建 Provider 协议。发现 Core 1.63.1 的 aiV6.llmPrompt 运行时已调用 aiV5PromptToAIV6Prompt，但两个公开声明错误返回 V2。新增仅类型声明的固定版本 Core patch，修正为 V3；无运行时替代转换或类型断言。
- 初次媒体测试以非持久化的 SDK output 构造输入，被 MessageList 转为 JSON，断言失败；改用 Mastra 的真实 modelOutput 元数据契约，验证 image-data/file-data 原生转换。没有修改运行时来迎合测试。
- pnpm patch-commit 自动重算的无关 supports-color peer 变更已去掉。当前锁文件仅更新 Memory/Core patch 哈希及引用；CI=true pnpm install --frozen-lockfile 通过，包版本不变。
- 最终：controller 8、generation 11、selection 3、state 2，共 24 passed；typecheck 和 diff whitespace 检查通过。
- 当前控制器测试使用仓库接口的内存替身验证调度/发布决策；真实 PostgreSQL 原子性证据见上节，不能宣称主 Run 已接通。控制器接入前必须确保每步完整原文（尤其最新工具结果）已持久化并与最终请求对应。

## 下一步接入要求

- Mastra processInputStep 有原始消息、工具对象；最终 Provider 调用才具备完全转换后的 Prompt/tool definitions。保持每步原文捕获与 Provider 最终预算同一个控制器，不能只对消息估算90%。
- 接入完整原文同步、固定 F/内部 Run 消息、关闭原生 OM 调度；再做公开 Run 成功/失败/取消与页面错误闭环。此票仍未完成、未复审、未提交。

## 真实 Run 接线与固定前缀（2026-09-07）

- Session 输入钩子同步完整原始消息与本批工具结果；最终 main-model wrapper 在 Guarded Provider 之前调用控制器，以转换后的全部 Prompt/工具定义检查预算。辅助模型仍使用 Run 原有 guarded memory 模型，避免递归压缩。
- 原生 OM 调度硬切换关闭。ResearchMemory 只负责完整原始历史加载/持久化，不再启用原生50条加载、独立阈值或后台观察。
- 新增 CONTEXT_COMPACTION_FAILED 契约；辅助输入无输出空间或辅助输出长度停止不再误标为用户回答 OUTPUT_LIMIT。
- Run identity/Continue 改为每Run一次的内部持久化消息，工具定义按名称确定性排序，主系统指令不再含Run动态内容。浏览器投影排除内部消息。
- 真实验收发现 Mastra 会把紧随内部assistant消息的回答合并到该消息；通过公开 rotateResponseMessageId 建立回答边界后修复，用户回答正常保存/重放，冻结内容不被改写。
- 首次旧历史fixture错误按单词数推算token，实际 tokenx 对 `context ` 每词计2 tokens，使辅助输入超限；失败正确发生在Provider调用前。改成258k配置、实际刚越90%的单批历史，未禁用保护或静默截断。失败证据包含 isolated projects 194511 / 194634 / 194718 / 194818。
- `compresses old Session history` 已覆盖 M/S发布、继续回答、完整原文保存、usage、重启无需再次辅助生成、Provider请求前缀逐项相等、其他Session无该记忆与删除清理。与普通Run/小窗口完整历史共同运行：3 passed / 62 skipped，project `thesistrace-agent-test-20260906t195443z-71804-3b62aace`，exit0。
- 选择器现在按完整协议组的预算选择连续尾部；大于保留预算的最后完整工具组进入 E，不强制留在 R 导致无法压缩；当前请求/Run identity/未完成交互仍固定保留。
- 最后工具结果场景：历史本身未触发，工具返回使完整请求越过90%，同一Run压缩继续或明确失败，原始结果均保留且无私有日志：2 passed / 63 skipped，project `thesistrace-agent-test-20260906t195849z-72723-ccf681a5`，exit0。
- Scripted身份fixture改为独立内部消息，取最近的明确Run身份；修正依赖固定消息下标的用例。选择器/Batch/Daily：69 passed。
- Agent全快速回归：593 passed / 1 failed（旧缺失身份fixture仍只移除system字段）；修正该fixture后受影响文件29 passed。未把分次测试误报为全套一次通过。最新typecheck通过。

## 当前剩余验收

本票尚未完成。继续检查完整Agent PG回归、Continue/ask_user与并发/取消、精确90%边界和页面错误契约；复核原文同步与快照提交的取消竞态、所需运行指标，再串行 Standards→Spec review、修复复审、tracker和独立提交。04—06尚未开始。


## 串行验收及 Standards 首轮（2026-09-07）

- Agent 全单元回归 599 passed，聊天时间线 16 passed；前后端 typecheck 通过。
- 最新隔离 PostgreSQL 全回归 74 passed，exit 0，project thesistrace-agent-test-20260906t202250z-78359-f9ca0566；日志 /tmp/thesistrace-ticket03-pg-tests.log。包含取消在提交锁等待期间发生时不发布的回归。
- 精确 232199/232200/232201 完整输入及低于90%但无合法输出空间的保护周期已验证（controller 共12 passed）。
- 新增统计只输出计数、耗时和 usage 估计差值，M/S 正文不进入日志；异常 usage 和前端遗漏已先复现再修复。
- Standards 首轮发现2项 P2：Mastra parser 缺标签时宽松解析，以及长行静默截断。新增回归得到2 failed / 7 passed，日志 /tmp/thesistrace-ticket03-parser-red.log；正在收紧纯候选入口，不改动原生其他路径。Spec 尚未开始，本票未完成。


## Standards 修复后验证（2026-09-07）

- 新增纯候选结构检查：唯一完整 observations 标签；使用原生 parser 后逐字比较正文，拒绝宽松解析或清洗改写，明确空 M 合法。ESM/CJS 一致。
- 候选/生成 20 passed；全 Agent 单元 601 passed；隔离 PG 全量 74 passed；Agent typecheck 与 diff whitespace 通过。
- 日志：/tmp/thesistrace-ticket03-parser-green.log、/tmp/thesistrace-ticket03-agent-tests-r2.log、/tmp/thesistrace-ticket03-pg-tests-r2.log。
- 冻结安装成功，锁文件仍只包含本票 Memory/Core patch 哈希及引用变更，无依赖版本升级或无关 peer 变更。
- Standards 复审 0 findings。Spec review 正在进行，尚未更新 complete 或提交。


## Spec 首轮修复（2026-09-07）

- Spec 发现1项P2：候选格式拒绝/快照冲突抛普通异常，被归为 INTERNAL_FAILURE。prepare 的公开边界现在将未分类的压缩异常映射 CONTEXT_COMPACTION_FAILED；取消优先，已有预算和 Provider 安全分类保留，无私有文本匹配。
- 候选、claim、commit三个回归先得到3 failed，再修复至 controller 15 passed。日志 /tmp/thesistrace-ticket03-failure-red.log、/tmp/thesistrace-ticket03-failure-green.log。
- 真实 Run 的最后大工具结果 success / rate-limit / invalid Observer 三场景 3 passed，验证失败码重放、无半份快照、原文保留、无私有错误泄漏；日志 /tmp/thesistrace-ticket03-failure-pg.log。Agent typecheck通过。
- 新增代码继续 Standards→Spec 串行复审，尚未标complete。

## 第03项交付结论

Standards R3与Spec R3均0 findings，首次单批闭环已通过。全Agent601/PG74为严格parser修复后的全量结果；后续错误分类变更验证controller15、真实Run3场景及typecheck，聊天时间线16项通过。所有原始失败记录保留。第03项随独立提交完成；04—06未开始，未宣称完整功能或真实模型效果通过。
