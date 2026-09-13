# 08 — 完成统一验收并一次硬切发布

**What to build:** 将经过验证的 226 字段能力、完整历史候选及所有消费者一次切换到同一当前合同；用户继续在原四个 Data 区块使用扩展后的字段，既有研究、跟踪历史和后续刷新保持正确。

**Blocked by:** 07 — 构建并验证 226 字段完整历史候选数据集

**Status:** ready-for-agent

**Execution contract:** 在从 main 创建并核实的新 worktree 中，严格按 01→08 串行执行。每票开始实现前先记录 Plan；完成实现后逐项验收，进行代码审查、修复及复审，更新 tracker 并形成该票独立 git commit，完成后才开始下一票。审查同样串行，不并行委派实现或审查。

**Latest user decision:** 按用户最新要求，直接实现当前合同，不做兼容、版本迁移或 vXX 升级链；保留数据、原有字段语义与必要研究引用的要求继续有效，不将“不迁移”解释为允许清库。用户随后明确批准本票切换方案的三表两列保留数据结构升级，作为限定源/目标的一次例外；详见下方授权补充，应用不增加运行时兼容。

**Execution order:** 08；必须先完成 07 的验收、复审、tracker 更新和独立提交。

- [x] 汇总母规格 T01—T16 的实际证据，确认不存在未完成的来源资格、历史采集、字段合同或高风险 review 项。226 个唯一作者入口、19 个新 TTM、原 12 项语义及全部可用性门槛成立，不能用完成目录或绿灯卡片替代数据验收。
- [x] 所有能力在 main 完成集成、必要 review 和提交，通过跨模块最终产品门禁。使用仓库既有隔离入口；镜像、启动和发布恢复按实际影响增加必要验证，不无故重复未变化的全部阶段。
- [x] 在真实浏览器完成 Data 查询、中文/DSL 搜索、用途/来源/期间筛选、公式补全及混合来源研究提交。页面仍为四块，全量就绪时 Market 22、Financial 204、合计 226；来源落后时显示实际状态，HTTP/MCP 与 Agent 同一目录。
- [ ] 真实依赖验证旧 Run 重试仍用其冻结 Generation，新 Run 固定新 Head，Track 新 Attempt 使用已验证当前 Head 且保留 Origin 和旧检查点。切换前已发布结果和引用的不可变字节不被改写或回收。
- [ ] 制定具体且可执行的切换记录：源 Head 与最终候选、各组件目标版本、备份坐标、在途 Attempt 处理、暂停与恢复条件、失败处置和核验结果。候选后源 Head 有更新时重组并重验，不能忽略 07 之后的刷新。
- [x] 直接使用最终当前合同，不开发版本迁移、vXX 升级链或旧版本兼容分支。通过复用原始数据、构建候选和验证后切换完成扩容，保留历史结果、被引用数据及必要备份。
- [ ] 按现有完成或恢复语义处理在途 Attempt，在统一部署窗口暂缓新的研究准入、刷新发布及 DailyTrack 推进；同步升级 Data、Alpha Catalog、读取准入、HTTP/MCP、Worker 和 Web 后核验 Head 与就绪状态，再恢复入口。
- [ ] 遵守 main 为唯一开发与集成基准的发布顺序：验证并提交 main，再由部署分支从 main 合并、推送部署分支并更新服务器；不在部署分支直接开发、不 cherry-pick 独立实现。
- [ ] 实际切换沿用原子 Head 发布和生命周期保护。切换前失败不动原 Head；切换成功后回执失败先核对已发布坐标并恢复状态，不自动回退指针。应用或发布失败按经验证的保留数据方案恢复，不清库、不改指纹绕过校验。
- [ ] 恢复入口后验证一条新研究、既有研究读取和 Track 推进，并完成后续正常刷新，确认新字段及各家族覆盖仍保留。操作结果、候选/Head 身份和浏览器证据与最终集成版本对应。
- [x] 应用仅保留当前合同，不引入双版本运行、双读双写、旧 API fallback 或逐行换源。Data 页不新增来源大卡片或期间差异界面，Operator 权限边界保持。
- [ ] 最终交付说明区分已实施、已测试、已发布及仍受来源覆盖限制的范围。只有验收、必要 review、提交和切换核验全部完成后本票才标 complete；不把准备好候选等同于完成生产切换。

**Verification:** 母规格 T01—T16 的最终证据汇总，重点 T13、T15、T16。执行跨模块产品门禁、真实浏览器与必要的镜像/发布恢复验证；生产操作按当次执行上下文及仓库发布规则开展，工单发布本身不执行任何线上动作。

## Comments

- 2026-09-12：用户确认发布工单。已纳入最新的串行执行、每票 Plan / 验收 / 审查修复复审 / tracker / 独立提交，以及不兼容、不做版本迁移的要求。

## Plan — 2026-09-13

- Predecessor07 is committed as4ed13765 after all11acceptance criteria and serial Standards/Spec reviews. Continue in the verified codex/field-expansion-226 worktree. Its only untracked files are the excluded original inventory builders and ticket-drafts; preserve them.
- Audit T01–T16 against committed evidence and current consumer code. Reuse the verified finalcandidate77d45ba1e49444b235308bc05fe1803e4e727532d0a8aec6e30bfe2a3b138e5d and19-hash handoff. SourceHead17f5694f6a9d47b915ffde326928b919a55181e75a4908cb661934850ac8c983 is a pinned preparation coordinate, not a claim of current productionHead.
- Inspect Data page search/filter/completion, HTTP/MCP/Agent catalog, research/Track admission and operator release controls. Add a failing regression only for a demonstrated missing behavior, then implement the smallest current-contract fix. Verify the existing four sections and22Market/204Financial counts in a real isolated browser, including mixed-source research submission and partial readiness.
- Run the existing final release gate for this cross-module production cutover, with isolated dependencies and current tool versions; preserve first-failure evidence and rerun only affected scopes after fixes. Browser evidence must identify its actual build/data coordinate. Existing07history qualification remains separate from deterministic release fixtures.
- Capture current production Head, version, in-flight operations and retained result/checkpoint references read-only. Prepare a concrete cutover record covering verified candidate transport, backup coordinates, admission pause/drain, component versions, atomic Head/lifecycle publication, recovery and entry resumption. Reconcile any sourceHead advancement before publication.
- Current code adds indicator ledger tables and two operation columns to data/schema.sql. Inspect the existing schema initialization/fingerprint rules and actual destination schema before any deployment. Do not invent a migration/version chain, wipe/recreate shared data or change only the fingerprint to bypass validation. If preserving existing production data requires a schema operation that conflicts with the user's no-migration instruction, surface that concrete release decision after completing unaffected implementation/verification.
- main is an ancestor of the worktree, so integration is currently fast-forwardable. Its dirty domain docs and untracked original design artifacts must be preserved; compare overlaps and retain exact backups before any authorized integration. Validate and commit main before the deployment branch merges only main; no direct deployment-branch implementation or cherry-picks.
- Once pre-release implementation/acceptance and serial review/fixes are complete, integrate the validated code on main and perform the concrete authorized release sequence. Verify previous results, one new research, Track progression and a normal refresh after resuming; verify retained family/field coverage and publication recovery without automatic Head rollback.
- Record exact tested, committed and deployed versions, source limitations and any blocked release boundary honestly. Close08and the overall goal only after all12criteria, finalreview, independentcommit and actualcutoververification are proven.

## 授权补充与结构实施计划 — 2026-09-13

用户本轮明确回复“允许”，批准切换方案列出的三表两列、限定源/目标且保留数据的显式结构升级。这是上述禁止迁移要求的一次具体例外；不授权清库、修改指纹绕过校验或运行时兼容。

- 使用现有显式升级入口风格，固定生产来源合同与当前目标合同；只新增指标账本三表及刷新操作两列，验证完整受影响表结构后才记录合同与执行回执。
- 先以真实历史 schema 在隔离 PostgreSQL 验证原数据保留、重复执行、结构漂移拒绝及晚期失败事务回滚，再完成 Standards → Spec 串行审查。
- 生产执行前备份并验证恢复；提交后的恢复使用备份与匹配镜像，不添加长期双合同运行分支。现有回归失败仍是发布前置条件，授权不代表已经发布。

## 预发布实现验收 — 2026-09-14

已完成限定源/目标的三表两列结构升级及保留数据演练；完成当前226字段合同下的回归修复、最终62文件Standards→Spec串行复审（均0）。最终新镜像13项受影响E2E及完整镜像资格入口通过。快速与真实依赖检查的首次失败、修复和定向通过详见[统一验收记录](../issue08-release-verification.md)。

保存本票独立代码提交，但状态继续ready-for-agent：尚未完成main集成、干净提交release gate与真实生产切换。候选外传暂停等待具体授权，不以本地验收替代线上发布。

## main 集成状态 — 2026-09-14

预发布代码39e4b88c及测试修正dde78933/e85d5a76已快进main；目标main的227项定向契约与Agent/E2E类型检查通过。详见[验收对应表](../issue08-acceptance-matrix.md)及[发布记录](../issue08-release-verification.md)。全量产品检查保留一次日志读取失败，修正后定向通过；完整镜像资格已通过且产品代码未变，不宣称整条check:release零退出。

上传因自动审批要求对具体候选和目的地的授权而暂停，用户答复待到达。生产备份、数据传输完整性、结构升级、Head发布及线上复核尚未完成，本票不关闭。


## 候选暂存验收状态 — 2026-09-14

上述等待候选上传许可的段落为历史状态。用户已经明确授权完整候选上传；13批续传全部成功，最终远端文件集合、大小及全部SHA-256严格核验通过：71929文件、8593065687字节，无HEAD.json。AppleDouble额外元数据已校验并保留到独立备份目录。完整回执与失败/恢复过程见[发布记录](../issue08-release-verification.md#候选远端暂存完成--2026-09-14)，记录提交1ffef374已进入main。

将main集成及产品门禁条目标为已验证：依据完整产品各阶段结果、日志缓冲修复后的定向E2E，以及相同产品代码的完整镜像资格结果；不宣称单次check:release命令零退出。

目前剩余权限阻断为部署分支向git@github.com:humeo/thesistrace.git推送的独立授权，用户尚未答复。生产备份恢复、结构升级、Canonical卷合并、Head切换与线上研究/旧结果/Track/正常刷新仍未执行。08保持ready-for-agent，不能关闭。
