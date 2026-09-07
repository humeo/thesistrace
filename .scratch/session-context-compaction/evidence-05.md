# Issue 05 实施证据

状态：05实现及验证完成，Standards→Spec复审各0findings，随05独立提交发布。基线04为b58132a，同一隔离worktree。下文按时间保留过程中间结果，最后一节为交付依据。

## 原生恢复接缝（2026-09-07）

- 真实Mastra Agent搭配Fake Provider验证当前Guard产生的length和明确context_length_exceeded都会进入公开processAPIError，保留ModelRequestFailure类型、本次预算和messageId，均未执行业务工具。2 passed，/tmp/thesistrace-ticket05-seam.log。
- 选择公开error processor作为统一恢复入口，无需为完成原因新增patch或外层Run重放。原有完整tool-call屏障保持；不可恢复分支仍明确终止。
- 新增共享恢复预算策略：小窗口禁用；length仅D受限；context与length均要求完整输入缩减、同模型容量和期望额度、合法D；length还要求D提高。
- acknowledgeRecovery失败回归：接口未实现时1failed/4passed，/tmp/thesistrace-ticket05-ack-red.log。实现只允许确认同一个pending failure且预算改善；保持steps和usage，辅助压缩可运行但不清主请求失败。新增与既有Guard测试64passed，/tmp/thesistrace-ticket05-ack-green.log。
- 原生retry验证：先成功工具步骤，再含完整tool-call的length，再独立替代回答。Fake模拟已提交压缩移除旧证据及无效正文；第三次Provider payload保留成功回执/原request_id，不含旧部分正文，工具只执行一次，响应ID独立，Run未留下终止失败。6passed，/tmp/thesistrace-ticket05-native-retry.log。
- 此处压缩提交仍由Fixture模拟，不能据此声称生产恢复已接入；下一步是PG持久化领取和关联、生产统一控制器、审计排除和页面状态。

## 恢复领取持久化（2026-09-07）

- typecheck发现原生内部变量maxErrorProcessorRetries不属于公开参数；改为公开maxProcessorRetries:1，原生retry6项及typecheck重新通过，日志 /tmp/thesistrace-ticket05-native-retry-r2.log、/tmp/thesistrace-ticket05-typecheck-r2.log。未通过类型绕过。
- 新增agent.model_step_recovery当前表：Session/Run复合归属、原响应和替代响应关联、0/1次数、原因、状态和前后预算；原ID/替代ID都查到同一记录，先事务领取再允许生成。
- recordModelStepStop/modelStepRecoveries/finishModelStepRecovery经现有Session锁和所有权检查。并发调用只有一个claimed，length与context交替不产生新次数；禁用恢复记录0次failed；成功结束还需预算改善。
- 失败回归因方法尚未存在而失败，/tmp/thesistrace-ticket05-recovery-store-red.log。schema:generate在隔离PG通过并更新当前catalog/grants，未迁移dev数据。
- 首轮测试业务断言及物理schema9项通过，但测试清理未先终止Run，被CHAT_SESSION_RUN_ACTIVE正确拒绝。修正Fixture生命周期后目标PG1passed/76skipped，/tmp/thesistrace-ticket05-recovery-store-r2.log；前次完整日志 /tmp/thesistrace-ticket05-recovery-store-green.log。新增接口typecheck通过 /tmp/thesistrace-ticket05-store-typecheck.log。
- 仍待生产错误hook/强制压缩/审计排除接入，恢复中的取消与崩溃终止、完整替代状态与UI、完整矩阵/浏览器、串行审查和独立提交。当前方法和接缝验证不等于05完成。

## 生产恢复与可见审计（2026-09-07）

- 强制压缩复用04控制器，在提交候选前验证I缩减和length的D改善；所有有效历史读取与E选择统一排除持久化无效响应ID。controller/selection/recovery 34 passed，/tmp/thesistrace-ticket05-force-final.log；schema+领取+既有大历史PG11passed，/tmp/thesistrace-ticket05-force-pg.log。
- 接入原生error processor，恢复开始前领取PG记录，成功候选后记录afterBudget，只有最终Run完成才标记succeeded；失败和Host重启终止未完成恢复。新增RECOVERY_FAILED安全错误及声明。
- 审计回归先失败：时间线随机ID使恢复关联找不到原文，原文实际已在timeline持久化。修复投影保留实际响应ID，仍隔离工具前后的重复ID文本段。无需把失败正文重新注入模型Memory。projector/model/controller34passed，/tmp/thesistrace-ticket05-projector-green.log；公开Run恢复+审计排除1passed，/tmp/thesistrace-ticket05-audit-fixed.log。
- 时间线SQL从恢复表投影recovery/supersedes，后到文本不会覆盖状态；没有正文的context拒绝创建空审计锚点。现有Run流发出仅含runId的安全通知，UI立即读取持久化投影。前端39passed，/tmp/thesistrace-ticket05-ui-tests.log；公开Run+并发领取PG2passed，/tmp/thesistrace-ticket05-ui-pg-fixed.log。
- 失败矩阵发现原生error hook的messageId与input processor实际返回ID不同，造成重复领取。改为由每步输入记录真实响应ID，错误钩子按该ID定位同一逻辑步骤。第二次length、length/context交替、Observer失败和成功恢复共5passed，/tmp/thesistrace-ticket05-stop-matrix-fixed.log。Observer失败保持旧快照并显示COMPACTION_FAILED，第二次回答失败显示RECOVERY_FAILED。
- SQL回归同时修复failed分支afterBudget为空时写JSON null违反对象约束的问题，保持SQL NULL。
- 仍待05剩余取消/重启/完整输出额度/小窗口/工具执行矩阵、最终类型与回归检查、浏览器验收、Standards→Spec串行审查及独立提交；05/06未完成。

## 扩展失败与取消验证（2026-09-07）

- Agent全部单元测试632passed，/tmp/thesistrace-ticket05-agent-suite.log；Agent/Web类型检查通过，/tmp/thesistrace-ticket05-types-final.log、/tmp/thesistrace-ticket05-web-types-final.log。
- 全PG首次84passed/1failed，/tmp/thesistrace-ticket05-full-pg.log。唯一旧失败用例把D受限的OUTPUT_LIMIT当作直接结束；将该组Fixture明确设为完整maxOutputTokens=1000，继续验证无自动恢复的原终止/重放/显式新输入契约，7passed，/tmp/thesistrace-ticket05-full-output-contract.log。没有删除行为覆盖。
- 新增完整输出额度、小窗口length、小窗口context拒绝，公开Run均无辅助调用、恢复次数0，已包含上述84项通过结果。
- 真实Run在Observer等待期间分别Stop和Host关闭，终止恢复、不发布快照；重启后连接旧Session不重新调用模型，持久化次数仍1。2passed，/tmp/thesistrace-ticket05-cancel-pg.log。等待采用abort-aware可控屏障；修正Fixture的promise属性后实际通过。

## 浏览器与完整工具屏障（2026-09-07）

- 最新完整PG88passed，/tmp/thesistrace-ticket05-pg-current.log，包含无E保护；Agent/Web最新类型检查通过。该全套结果早于以下工具屏障加固，最终需复验。
- 使用in-app browser打开隔离Vite15174的生产ChatTimeline组件fixture，依次验证recovering、succeeded、reload后独立替代正文、failed保留部分正文以及展开工具组显示Completed。临时Tab已关闭。此项仅证明真实浏览器组件展示；持久化由公开Run+真实PG证明，不能冒称完整生产浏览器端到端已验收。
- 工具矩阵首次3failed/1passed，/tmp/thesistrace-ticket05-tool-stop-fixed.log：末步含完整工具参数的截断响应仍被Mastra重建并执行。诊断证明发生在失败的第二/三次回答；不是此前成功工具的合法执行。
- 保留整个tool-input-start/delta/end及tool-call序列到有效finish，阻止错误路径参数重建。完整工具矩阵4passed，/tmp/thesistrace-ticket05-tool-barrier-fixed.log。工具正常成功路径和完整全套尚待本次加固后复验；已移除临时诊断日志。
- 新增工具定义会增大完整请求I，Fixture历史从1800降至1700重复，显式断言前两个请求都是answer，确保测试覆盖异常恢复而非提前正常压缩。这不是生产触发线调整。

## 串行审查与修复（2026-09-07）

- Standards首轮：0硬性违反，1项P3判断性重复Fixture建议；提取本文件seedRecoveryHistory与可取消等待helper，保留各场景独立断言。
- Spec首轮：1项P2，Stop/超时/Host关闭在替代正文已经开始时，入口abort会跳过invalidReplacement更新，可能把半份正文再次送入模型。新增公开Run回归先失败：invalidReplacement实际false，/tmp/thesistrace-ticket05-partial-cancel-red-r2.log。初版测试缺少helper闭合括号的语法失败未计作行为复现。
- 修复为替代响应默认invalid，只有原生processOutputStep确认stop/tool-calls、无模型失败且Run仍running，才持久化为可用；最终Run失败保持已经有效完成的工具步骤。恢复成功仍只由Run完成边界确认，不暴露提前succeeded更新入口。同步当前schema默认值与生成的catalog，不添加迁移。
- schema:generate通过 /tmp/thesistrace-ticket05-completion-schema-r2.log；相关真实PG16passed，/tmp/thesistrace-ticket05-completion-green.log。
- 取消未完成替代正文：审计保留、标记invalid、重启后后续输入排除。取消发生在替代工具已成功、后续步骤才开始时：标记仍valid，工具证据保留且只执行一次。2passed，/tmp/thesistrace-ticket05-completion-evidence.log。
- 首轮审查快照 /tmp/thesistrace-ticket05-review。修复后仍需Standards→Spec复审及最终当前代码验证；05未完成、未提交。

## 05交付依据

- 审查修复后Agent全部单元632passed（/tmp/thesistrace-ticket05-review-fixed-unit.log）、真实PG90passed（/tmp/thesistrace-ticket05-review-fixed-pg.log）、Agent类型检查通过（/tmp/thesistrace-ticket05-review-fixed-types.log）。Web相关39passed及类型检查见上文；之后未改变Web产品代码。git diff --check通过，无临时诊断日志。
- Standards复审0findings：重复Fixture建议关闭；Spec复审0findings：替代正文中途取消P2关闭。共同审查冻结快照 /tmp/thesistrace-ticket05-review-r2，原main checkout排除。复审后只更新本票tracker/计划/证据。
- 单次持久化恢复、预算改善、错误分类、默认排除未完成替代消息、有效工具证据保留、完整工具输入屏障与UI状态均已交付。06尚未实施，未声明最终pnpm check/image-smoke或真实模型摘要质量已经通过。
