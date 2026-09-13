# 08 — 统一验收与发布记录

状态：进行中。01–07 已提交，08预发布代码已独立提交为 `39e4b88cd4f6f595472a225c51b06a9436c0d030`。本文不代表生产发布成功。

## 当前结论与未完成项

以下正文按时间保留首次失败和后续修复记录；早期“尚未授权”“运行中”等描述仅代表当时状态。

- 01–07 已分别提交；08 的结构升级已获明确授权，本地升级五项测试和独立备份恢复演练通过。
- Core静态schema、MCP编译缓存、预算连接占用与上下文读取已调整，业务池等待10秒、MCP连接复用5秒发现期限。测试代理旧barrier竞态已修复。最终新镜像20260913t171901z-40746-a02f1901的13项定向E2E全部通过（3.4分钟），含50并发、Host/context及研究保留，清理0。
- 最新Agent 651单元和类型检查通过；真实依赖完整99通过/1等待断言失败，修正该测试的明确等待边界后定向通过。完整Core505、Auth145以及先前其余E2E通过范围见下文；保留所有首次失败，不声称首次全套无失败。
- 完整镜像资格验证已通过；干净提交上的最终 release gate、main 集成、生产真实备份及切换后研究/Track/刷新核验仍未完成。局部通过不能替代这些要求。
- 原 main 的用户改动与备份保持；生产未执行本票结构升级或 Dataset Head 切换。恢复执行前仍须重新核对生产状态。

## 生产只读预检 — 2026-09-13

通过 `thesistrace-contabo` 的 `thesistrace-api-1`，使用现有 Core 数据库连接执行只读结构查询，并读取 DatasetLifecycle 当前指针。未暂停服务、修改数据库或发布候选。

- 当前 Head：`17f5694f6a9d47b915ffde326928b919a55181e75a4908cb661934850ac8c983`。
- 当前 data identity：`9be9862e820efe59695873922057671823c82caad1a625968fb70b246ae2de85`。
- 覆盖：2010-01-04 至 2026-09-09，共 4,053 sessions。与 07 固定源一致；实际切换前仍须重新核对。
- 生产 schema 指纹：`6f04fe84573259465442c092856b69714ed339c2093d51dcf67ba4b68aaa359f`。
- `information_schema.columns` 查询未发现 `data.financial_indicator_*` 表或 `data.financial_daily_refresh_operations.indicator_*` 列。
- 当前 initializer 对已有数据库只校验合同，不能自动补充结构。尚未批准或执行结构变更；不能只修改指纹绕过检查，也不能将缺失结构描述为已就绪。
- `docker ps` 确认现有 API、Web、Auth、Agent、Data Operator、Tracking、Publication Maintenance、三个 Research Worker、两个 Batch Worker 和 PostgreSQL/RustFS 正在运行。镜像名称并不证明构建 revision；精确组件版本仍待读取。

后续只读在途与保留引用预检：ResearchRun 共 943（919 succeeded、24 failed），Run Attempt 155 succeeded/8 failed；Batch 209 succeeded/2 failed；1 条 active Track、0 条 session progression、1 个 Track checkpoint；3 个 Market Refresh 和 1 个 Financial Daily Refresh 均 succeeded。当前查询未发现 queued/running/cancelling 研究或运行中刷新。以上是预检时点，切换前仍须重新读取并暂停新准入。

按 Run ID 排序、聚合不可变输入摘要及结果 manifest 引用得到 MD5 `5a764db058eef76e709ac9c1dc6716f8`（943 行）。仅作为变化检测摘要，不替代逐引用校验或数据库备份。未输出用户公式、凭证或结果内容。

只读 `docker inspect` 保存的切换前镜像 ID 如下。这六个容器均没有 `org.opencontainers.image.revision` 标签，因此不能由标签确认源码提交。

| 组件 | 镜像 SHA-256 |
|---|---|
| API | `e48eaefc28d10ef5578e52e80418161f7af84972b81030629d8183aa22577147` |
| Web | `3c3a9bb37f23da2fa217d91f308da7444ca1c760c436d7ce0629d080241d148d` |
| Auth | `9c7d9a6736133df0ae83a8fe83985366c32f7bc07e575a9ee61a7cb01e3a3ee7` |
| Agent | `f846484f3123a6732f411911fdbc2443c581d28bcd0f4c796b7c6f2ff7c25e13` |
| Data Operator | `93d8fdf95daa839e9f231e224bc702c47ddc288f7e68cdb2edadba287d2e9f44` |
| Tracking | `d5859879463e1148c0b36dced51bbf4061d3a17dcd4bce627de12f0a61119dc9` |

候选：`77d45ba1e49444b235308bc05fe1803e4e727532d0a8aec6e30bfe2a3b138e5d`。完整历史与来源资格沿用 [07 验收索引](issue07-acceptance-index.md)，不以确定性测试 Fixture 替代。

08 交接复核重新计算了 `issue07-candidate-handoff.json` 引用的 19 份证据文件 SHA-256，并直接校验实际候选根 manifest 字节与其地址一致；全部匹配。这是交接完整性复核，不是再次执行全历史采集或读取。

## 产品门禁

首次 `mise exec -- pnpm check` 已结束，退出 1。Core 集成证据目录：`.local/test-runs/20260913t112536z-53777-585a28de/`。

- 快速 Python 测试：1,421 passed；一条已有多线程 forkpty 弃用警告。
- 快速检查阶段已结束并进入浏览器阶段。
- 浏览器组件：32 passed（45.5 秒）。其中真实浏览器运行的 Data 组件覆盖 226 字段目录、四区块、来源部分就绪、中文/DSL 搜索、用途/来源/期间筛选及新增字段补全；HTTP 数据来自 Fixture，不是生产端到端证据。
- 真实依赖 Core 集成：485 passed、8 failed、8 deselected，1054.96 秒；诊断与清理成功。两项失败为旧测试响应未提供当前三表源列，六项为历史迁移目标与当前 schema 指纹不匹配。此轮没有执行后续 Auth/Agent 集成、依赖重启及 E2E 阶段。
- 完整研究提交 E2E、镜像验收、main 集成和生产切换尚未完成。

已扩展现有 `core-shell.spec.ts` 的 Financial catalog / DailyTrack 用例为 `Complete field catalog composes one Formula and starts its DailyTrack`：真实 API 页面要求 226 available、四区块、163 个指标来源字段、中文搜索和 19 个 TTM；研究公式改为 `rank(close_raw) + rank(pe) + rank(roe) + rank(revenue)`，沿用实际 Worker 执行、结果和 Track 断言。该新增验收尚未运行。当前集成进程继续执行原 Python 基线；此 E2E 编辑不作为已通过的快速检查或浏览器组件证据。

独立夹具复现：使用 `ReplayTushareProvider` 请求产品 Replay 的 `fina_indicator`，证券 `000001.SZ`、范围 `19900101..20260805`、完整 `FINANCIAL_INDICATOR_SOURCE_FIELDS`，命令退出 1，具体原因是 `Unrecorded indicator response`，对外为 `REPLAY_REQUEST_MISMATCH`。产品 Replay 当前仅记录三表；这与请求字段不足或请求期间越界不同。

`prepare_current_data.py` 已加入通过 `FinancialIndicatorCollector`、`FinancialIndicatorCandidateStore`、Generation 组合及 DatasetLifecycle CAS 准备初始指标的路径。待补齐 Replay 响应并运行隔离 E2E；不以准备代码存在替代通过证据。Ruff 首次发现导入格式问题，整理后 0 remaining。当前长集成进程尚未终止，未修改它使用的生产 Python 实现和 Replay 文件。

后续修复与复验：

- 产品 Replay 已补齐指标响应，最小复现退出 0；核对 `000001.SZ` 的 2009/2025 两个报告返回预设 ROE 13/16。其他未指定指标保持 null。这是合成工程 Fixture，不是供应商来源资格证据。
- 两个旧三表 Fixture 增加当前合同要求的源列，新列保持 null；既有数据值不变。产品 Replay 的配套 capability Fixture 同步更新。
- `20260913t114527z-60640-52490742`：`test_real_private_financial_command_uses_product_replay` 与 `test_financial_generation_pin_protects_transitive_evidence_until_release` 均通过，2 passed / 499 deselected，4.44 秒，退出 0、清理成功。测试准备文件 Ruff 通过。
- 历史迁移的六项失败尚未修复；既有脚本的目标版本防护没有放宽，也未新增迁移脚本。
- 已启动以 `Complete field catalog composes one Formula and starts its DailyTrack` 为过滤条件的现有隔离 `pnpm test:e2e` 入口，结果待取得。

后续历史回归与浏览器诊断：

- 六项历史迁移失败来自测试输入引用今天的 schema，而脚本固定目标属于旧发布。新增仅测试使用的 `historical-core-schema/publication-maintenance-release.zip`，来源为 `fc94e3aa270b3c9a2c809de63b8d0b755aa2995c` 的完整八 schema；加载时验证真实计算指纹 `6f04fe84…`。既有迁移代码及其源/目标保护均未修改，不用于升级生产库。
- `20260913t114928z-62806-6b4f34c3`：两个历史迁移文件的全部 8 项测试通过（含先前六项失败），493 deselected，2.58 秒，退出 0、清理成功；保留原数据、重复执行、失败回滚和结构漂移断言。Ruff 通过。
- 首次定向 E2E `20260913t114655z-61295-b03bdce4` 退出 1，清理完成。数据准备及所有组件启动通过，失败发生于自动 researcher fixture：`openDataOverview` 仍等待已不再发出的 `/api/alpha/catalog` 请求。失败页面快照实际显示 Market ready、Finance ready 和 226 available；尚未执行四来源研究与 Track 主体。
- 修复 `openDataOverview`，只等待并校验 `/api/data` 的目录快照；不恢复第二个目录请求、不放宽超时。已重新启动同一定向 E2E，结果待取得。

- 第二次定向 E2E `20260913t115046z-63432-80669e2c` 退出 1、清理成功。已通过 Data 的 226 字段、来源/期间筛选、四来源研究执行、创建 Track 和数据落后后的阻塞断言；失败发生在恢复 Fixture 的 `protect_candidate`。
- 精确原因：恢复辅助函数固定 `finished_at=2026-08-11`，早于本次 CLI 实际保存的报表时间，触发 `FINANCIAL_SOURCE_COLLECTION_INVALID` 的观察时间校验。修复为真实操作时间；校验与生产代码保持原样。
- 同时让恢复步骤通过既有指标采集器重新确认至目标日期，组合候选时保留先前 collection/discovery 证据。刷新 Replay 只补入合成指标响应，三表缺失仍保留，用于原有 lagged → blocked → recovered 流程。新增字段值未随意填充。
- 两个辅助 Python 文件 Ruff 通过；第三次同一定向 E2E 已启动，尚无最终结果。

- 第三次定向 E2E `20260913t115456z-65201-e71bba27`：1 passed，浏览器阶段 67 秒，退出 0、清理成功。研究执行、创建 Track、覆盖落后阻塞、恢复后的冻结目标重试与推进至 2026-08-11 全部通过；最终观察有持仓且 session 正确。分组汇总：`.local/e2e-runs/1789300494428-65178/results.json`。
- 在该闭环上补充直接验证 22/204 分类计数、DSL 搜索和用途筛选；新断言随下一轮验证，不追溯计入上次通过。
- 已启动修复后的完整 `mise exec -- pnpm check`，用于共享 Data 导航辅助函数、产品 Replay 和历史测试夹具的全产品回归。此轮与最终干净提交的发布资格记录仍须明确对应，不把局部通过替代未执行的后续阶段。

- 该次完整门禁在 Ruff 阶段退出 1：之前对根目录辅助文件运行的定向 Ruff 未显式指定 Core 配置，两个文件的第三方/项目导入分组不一致。用 `--config apps/core/pyproject.toml --fix` 修正，两处问题均关闭；再次启动完整门禁，当前尚在运行。此后针对根目录 Python 辅助文件必须显式使用同一配置。

## main 集成准备

[重叠检查](issue08-integration-overlaps.json) 是对原 main 工作区的只读比较：分支变更与原工作区未提交文件存在 38 个重叠路径，其中 14 个字节不同，主要是旧工单、规格和字段目录。原工作区未被改动。实际合并前必须保存原字节及路径，逐项处理这些重叠；不能用覆盖或删除来省略保留工作。其余不相交的用户改动继续保留。

已将上述 38 个文件（686,204 字节）复制到本 worktree 的 `.local/field-expansion-226-integration-backup/preflight-original-main/`。`backup-manifest.json` 记录原路径、每文件 SHA-256 和字节数；复制后逐文件复核备份及原文件字节一致。原工作区未改动，实际合并前仍须重新核对是否出现后续编辑。

当前完整门禁续报：显式 Core Ruff 配置通过，Python 1,421 passed（186.19 秒），Agent 648 passed；其余阶段仍在同一进程中执行，尚不能标记全门禁通过。

续报：Web 355 passed，浏览器组件阶段完成并进入 Core 集成。当前集成运行坐标为 `20260913t120507z-79654-3d9f96f6`。浏览器测试生成的无关移动端截图已恢复为本分支原字节，不纳入 08 提交。

上线前 Standards 审查已开始，使用固定工作区快照 `/var/folders/py/j9ws8lpn57g_syngj3b58b6h0000gn/T/issue08-review-r1-kr8uuxxx`，基线 `4ed13765`；完成后才开始 Spec 审查。范围仅本票实现/验收/证据文件，排除原库存构建脚本、ticket-drafts、原工作区用户修改和已完成票的提交。不将此次上线前审查等同于整票完成或生产发布批准。

后续必须记录首个失败原因、修复、受影响范围复验，以及最终干净提交的实际发布版本。未勾选的 08 验收项继续保持未完成。

## T01–T16 证据衔接

继续修复已跑完的浏览器文件：Host 重启以确切 ResearchRun 资源卡片和 Rank IC 指标确认结果；DailyTrack 以确切 ID 导航和 Core 实际 observation 指标/日期确认当前视图，重载比较业务字段而不是刷新时间。上下文压缩用例检查持久化工具活动包含完成的 context/catalog，且所有活动终态完成，不再固定分页调用总数。以上均待独立 E2E 复验与串行复审，不能从首轮其他用例通过推断这些修正已通过。

开始修复首轮中已执行完的 `auth-flow.spec.ts`：登录标题按实际页面 `Welcome to QuantTrace` 更新；用户隔离用例使用当前 `page/page_size`，验证 A 的两页精确对应两个新建 Run，切换到 B 后页面不含 A 的 Run，保留跨用户资源404和草稿/回执/文件夹隔离断言。此文件修改不追溯计入正在运行的首轮结果，仍需定向复验和串行复审。其余正在执行的用例保持不变。

镜像第四轮 `20260913t124749z-1138-5fece3ec` 退出 1、清理 0；OOM 修复通过，指标准备也执行完成，但概览仍为 ready_with_gaps。进一步沿 `describe_family_fields` 核对：镜像行情研究日历从 2009-12-07 开始，既有三表夹具覆盖从 2010-01-01 开始，当前合同正确将三表家族判为 partial。此前将整体缺口全部归因为缺少指标家族不够准确。保留真实起点，整体预期改为 ready_with_gaps，并新增明确断言：三表41字段/起点2010-01-01/partial；指标163字段/起点2009-12-07/ready。这样不会把缺失指标或错误起点也放行。Ruff 通过，新增断言需复审；第五轮镜像已启动。生产完整候选的起点对齐及资格继续以07独立证据为准。

E2E 首轮中途诊断（整体仍运行，不是终态汇总）：至少 12 项失败，包含旧登录标题、旧 Web 游标预期、旧 Batch/Run/Track 表格与导航断言、上下文工具活动固定计数，以及 50 并发容量测试在 20 秒内只观察到 13 个被代理挂起的调用。当前 `ResearchResourceCards.tsx` 使用按 ID 读取的资源卡片、ResearchRun/Track ID 导航和定义列表；旧表格/固定标题断言需按公开行为重写。容量问题尚未证明是过时断言，必须单独复现及核对实际准入/调用状态，不能直接增加超时或降低并发数宣称通过。保留本轮全部页面、trace 和日志后再定向复验。

OOM 三行测试修正已完成 Standards → Spec 串行复审（固定快照 `issue08-review-oom-xaqk_v58`），两轴 0 新增发现。实际 `tests/image-checks.sh verify_research_child_cgroup_oom_detection` 入口退出 0，证据 `/tmp/issue08-oom-shell/research-child-cgroup-oom.json`；完整第四轮镜像 `20260913t124749z-1138-5fece3ec` 继续执行且已越过该故障阶段。main 集成备份再次逐文件校验：38 个原文件/备份摘要全部匹配，main 仍为 `fc94e3aa270b3c9a2c809de63b8d0b755aa2995c`，未修改原工作区。

镜像第三轮 `20260913t124008z-95178-6b0477af` 在 `image-smoke-research-child-cgroup-oom` 退出 137，清理 0；尚未运行新财务夹具。用同一当前 Core 镜像、相同 192 MB 上限定向复现，监督进程 RSS 约 128 MB，容器退出 137 且 OOMKilled=true。故障注入原本未指定受害者，内核可杀监督进程。只修改测试注入子进程写入 `oom_score_adj=1000`，维持原内存上限和生产监督代码；复验退出 0，实际 oom_kill 从 0 增至 1、child=-9、资源耗尽正确分类并发出退出事件，子进程已回收。两个诊断容器随后清理。新增 shell 改动还需复审和完整镜像验收，不以一次复验代替整体资格。

完整 E2E 仍在运行，已观察到旧登录标题与旧 `limit/cursor` Web 列表参数预期失败。实际 Web 合同是 `page/page_size`，旧游标参数被忽略；后续应验证分页内容按 Researcher 隔离，不把旧参数的 200 当作跨用户泄漏，也不弱化隔离断言。测试尚未结束，未对这批运行中的浏览器文件做修改。

最新夹具增量复审：固定快照 `issue08-review-fixtures-6ai3g3mj`，范围 Agent 集成的比较组件断言及镜像财务准备脚本；Standards → Spec 串行完成，均 0 新增可操作发现。Agent TypeScript 类型检查退出 0。完整 E2E 运行 `20260913t124120z-95726-de0035a1` 和镜像第三轮 `20260913t124008z-95178-6b0477af` 仍在执行，未声明通过。

后续完整门禁：Auth 18 文件、145 测试通过（112.42 秒）。Agent 首轮 94 passed、2 failed，`pnpm check` 因此退出 1，未执行 E2E；失败日志位于 `/tmp/issue08-agent-batch-repro.log`，对应真实依赖证据目录 `thesistrace-agent-test.3hSbZP` 与定向复现 `thesistrace-agent-test.M7M6ry`。两项均为旧展示标题断言，实际 A2UI 已包含正确 `ResearchComparison` 和有序子 Run 引用。改为公开组件与 runIds 断言，保留持久化、重放及不重复准入断言；定向复验 2 passed、80 skipped，退出 0（`/tmp/issue08-agent-batch-fixed.log`）。单独继续未运行的完整 E2E，避免重复已经通过的 Core 和 Auth 阶段。

镜像第二轮 `20260913t122856z-89168-e4ca8280` 退出 1、清理成功。实际概览确认种子预期已正确，唯一剩余差异为 `financial_research_readiness=ready_with_gaps`。镜像独立准备脚本只发布三表，未调用 E2E 已具备的指标采集/组合路径。现复用 `publish_indicator_fixture`，为 30 只证券扩展四接口回放，保留两个指标历史报告；初始和恢复路径均发布完整财务家族。离线夹具核对和 Ruff 通过。第三轮完整镜像资格 `20260913t124008z-95178-6b0477af` 已启动，结果待取得。新增两处测试文件修改需继续串行复审，不能沿用之前仅两文件的审查结论。

Core 完整集成入口 `20260913t120507z-79654-3d9f96f6` 已退出 0、清理 0：普通 493 项通过，六个专门恢复阶段各 1 项通过，JUnit 均 errors/failures/skipped 为 0。六阶段覆盖数据库读取、RustFS 依赖、策略、批量取消及 PostgreSQL 批量/策略恢复。普通阶段的 `8 deselected` 是该阶段过滤结果，不应被解释为后续实际执行八项；以六份恢复 JUnit 为准。完整 `pnpm check` 已继续进入 Auth 集成，整体结果仍待取得。

R2 后增量审查覆盖 `tests/production_image_smoke.py` 和 `issue08-cutover-plan.md`，固定快照 `/var/folders/py/j9ws8lpn57g_syngj3b58b6h0000gn/T/issue08-review-delta-2oux6m72`。按 Standards → Spec 串行完成，两轴均 0 新增发现。明确保留结构授权前提；此结论不替代运行中门禁或发布批准。

完整门禁的 Core 普通集成 `20260913t120507z-79654-3d9f96f6` 已完成：493 passed、8 deselected，1462.49 秒。首轮八项失败本轮均通过。剩余八项由入口的专门依赖重启阶段执行，尚不声明完整集成门禁通过。保留一条既有 JUnit `record_property` 警告。

镜像资格首轮 `20260913t121902z-85741-32cafe2d` 退出 1，诊断与清理成功。失败阶段 `image-smoke-before`：`production_image_smoke.py` 的概览断言仍要求旧 `latest-pre-start-annual-flow-and-balance-facts`，而当前三表构建器提供 `annual-stock-and-ttm-dependency-seeds`。已同步当前合同预期，断言失败将输出实际概览，Core 配置 Ruff 通过；重新启动同一隔离完整镜像入口验证其余差异。首轮通过的启动、恢复、权限和 Operator 阶段不代表整项资格通过；后续 Auth/Agent/Caddy 独立镜像阶段尚未运行。此测试文件新增修改不在先前 R2 审查范围，需追加审查。

具体发布方案已另存 [08 切换方案](issue08-cutover-plan.md)，列明生产缺少的三表两列、数据保留约束、暂停/备份/CAS/恢复顺序和未授权结构边界。该文档尚未纳入先前 R2 代码审查。完整产品门禁仍运行；另已启动现有 `pnpm test:image:qualification`，隔离运行 `20260913t121902z-85741-32cafe2d`，当前镜像构建与新卷阶段通过，整体结果待取得。未运行生产操作或最终干净提交的 `check:release`。

上线前串行审查已完成：Standards 首轮唯一 P3 为测试夹具依赖私有 `_fingerprint`，已改为校验固定历史归档的 SHA-256；复审 0 新发现。修复后真实数据库复验 `20260913t120810z-81244-6a33e198`，8 passed，退出 0、清理成功。Spec 审查固定 R2 快照（17 个文件哈希一致），0 项需修复的实现问题。两项结论仅覆盖准备代码，不代表完整门禁、main 集成或生产切换完成。

授权核对：用户“允许”对应 2026-09-13 生产 2.6 GB canonical-data 和 204 KB benchmark-data 复制请求，07 已完成该操作。不能将其解释为另行批准数据库结构升级。当前生产结构差异仍按本票 Plan 的具体发布决策处理。

下表是现有证据的索引，不表示 08 最终门禁已通过。01–07 的提交与验收日志保留在对应工单中。

| 规格 | 已有证据 | 08 剩余边界 |
|---|---|---|
| T01–T02 | 01–06 目录/单位公开接口测试；07 四来源逐字段资格与最终 226 列离线读取 | 最终发布版本的 HTTP/MCP/Agent 目录一致性 |
| T03–T06 | 04 TTM 验收；`test_ttm_research_series.py`；指标序列的单位、空值与冲突测试；07 三表冲突归因 | 全产品回归中的计算消费者 |
| T07 | 07 三表种子闭包测试、全部历史身份资格报告，333 个退市身份保留 | 切换前再次校验源与候选坐标 |
| T08 | 02/05 分片、上限、重试及 pending 验收；07 每日数据上限回归 | 当前真实依赖集成、发布后正常刷新 |
| T09–T10 | 01/05 准入与消费者集成；07 禁网完整候选读取、单字段/多字段等值报告 | 最终端到端混合公式与冻结输入 |
| T11–T13 | 07 完整候选刷新保留测试、12 项真实依赖边界及 1 项发布前故障测试，详见 07 索引 | 生产旧结果、Track 检查点、实际切换及刷新 |
| T14 | 快速门禁中的 Factor/Strategy/Tracking 与 TTM 缺失覆盖测试 | 当前真实依赖和研究 E2E 的最终结果 |
| T15 | 32 项浏览器组件测试中的桌面/移动 Data 全目录行为 | 真实 API 驱动的研究提交、生产四区块状态 |
| T16 | 01–07 当前合同实现与 Operator 边界测试；已读生产结构和 initializer 规则 | 保留数据的结构处理决定、镜像验收、main 集成及实际发布恢复证据 |


## 2026-09-13 13:19 UTC — 当前验收进度

- 完整 E2E 的共享组 `20260913t124120z-95726-de0035a1` 已完成：46 passed、25 failed（23.3 分钟）。后续隔离组继续执行，完整入口尚未终止。226 字段闭环隔离组 `20260913t130747z-12448-5c22a3b1` 1 passed（1.2 分钟），包含此前新增的 22/204、DSL 和用途筛选断言；下一组 Draft 闭环也已通过。不得将共享组修正追溯计入首轮结果。
- 已修正已执行文件中的旧卡片/导航、旧登录标题及密码流程、Web 游标分页和目录概览假数据。资源卡按绑定 ID、顺序及 Core 数值断言；重载比较业务指标，不比较读取时间；保留准入回执、权限、研究/跟踪独立性和重放不重复创建检查。登录先等待验证码表单，避免在发送请求完成前读取邮件夹具。此批尚待独立浏览器复验。
- 容量测试仍使用 50 个实际请求与原资源上限，准入饱和条件改为数据库中 50 个已准入活跃 Run，另确认有响应被代理挂起；不要求所有请求同时进入远端 Tool。第 51 个浏览器请求拒绝、释放全部请求以及显式重试的原断言保留。此修改需复验，不据此宣称此前容量失败已解决。
- 镜像第五轮 `20260913t130001z-8625-e94a5e89` 退出 1，清理 0。覆盖起点、41/163 家族与 ready_with_gaps 断言已通过；`image-smoke-before` 随后在公开目录预期字段集合失败，原断言未包含实际字段。补充 missing/actual 与两次 Generation 坐标后启动第六轮 `20260913t131507z-17539-82966fd0`，用于明确原因，暂未改目录预期或生产实现。
- 当前新增浏览器测试 TypeScript 检查通过；镜像辅助脚本按 Core 配置 Ruff 通过。Standards 复审固定快照 `issue08-review-browser-1rvhke5n`（11 文件）正在进行，完成后才启动 Spec。以上不是完整资格、08 完成、main 集成或生产发布证明。

- 镜像第六轮 `20260913t131507z-17539-82966fd0` 退出 1、清理 0。诊断明确缺少 `open/high/low/volume/amount`，overview/catalog 同为 `983ad04b7c019bc3dbe4667f509d7829c8dcff5bfb48a94fa5dc48eb50f9392b`。实际行情列存在，问题是夹具沿用 `build_market_benchmark_stream` 仅声明 close 的目录；产品目录按当前真实发布字段过滤是正确行为。镜像专用夹具改为标准 `field_catalog`，性能基准和生产实现不改。离线核对 7 个 canonical 字段、90 行全非空通过；首次离线核对脚本写错 volume/amount 的 canonical ID，查源码纠正后通过。Ruff 通过。第七轮镜像 `20260913t132448z-24040-df52e7ce` 已启动，结果待取得。
- 浏览器复审 R1 Standards 两项：代理 held 状态一次性读取竞态、删除了当前移动控件44×44断言。已改有界轮询并恢复尺寸检查，R2复审0新增。R2 Spec 一项：provider恢复只检查卡片可见，未证明结果展示；已补 succeeded 与对照Core的1/5/20S Rank IC。R3 Standards增量复审0新增，Spec复审仍待结果。最新固定快照 `issue08-review-browser-r3-xqfshn3j` 共13文件，TypeScript检查通过。
- 原完整 E2E 的 Operator navigation 隔离组 `20260913t131355z-16529-2dec53d5` 在旧 `ThesisTrace home` 名称超时失败，尚未通过；已在该用例完成后改为当前 `QuantTrace home`，并更新同文件旧登录标题。其余隔离组继续执行，各组以实际构建和加载版本为准。

## 本轮授权与回归修复 — 2026-09-13

- 用户本轮“允许”明确批准切换方案的三表两列保留数据结构升级；先前“尚未授权”记录是历史状态。已补充08实施计划，生产尚未执行。
- daily_basic 原始规范值经过 decimal128 Parquet 读回会多出尾随零，导致相同来源值被判为变化。公开 Store 往返测试先失败；读取改为不舍入的十进制文本规范化后，daily_basic单测7 passed。
- 新增真实刷新参数化回归：R1证券ID错误、R2共享幂等键冲突、R3目录顺序错误均为新夹具问题。R3离线逐键对照仅field_catalog顺序不同，真实Tushare adapter按field_id排序；同步夹具后R4 `20260913t134713z-37707-6cc2431c` 2 passed（3.64秒）、清理成功。两种有/无daily_basic都验证no_change、Head不变及刷新时间推进。Ruff通过。
- Chat资源卡迟到高度变化使恢复历史后底部脱离视口。新增组件测试先失败，ResizeObserver在允许跟随且无锚点/动画时保持底部；21组件测试通过、Web类型检查通过。更新镜像的E2E尚待验证。
- 定向E2E `20260913t132828z-26692-c8ae9777` 移动资源控件实测36px（要求44px）。480px窄屏规则补齐Reload与资源导航44px，保留原断言，尚待新镜像复验。另有并发/Host恢复/上下文终态/滚动等失败，不能声明整体通过；后续隔离Operator组仍运行。
- 最新8文件固定快照 `issue08-review-regressions-r2-ntish3rp` 完成Standards→Spec串行审查，各0新增发现。审查不替代最终镜像、浏览器和线上恢复演练。

### 结构升级与后续门禁的最新状态

- 新增显式入口 `thesistrace.migrations.financial_indicator`，固定来源6f04fe…与目标624c31…，三表两列之外不改原业务行；在单事务内核验受影响结构、执行DDL和记录合同。新建隔离历史数据库回归先5项ModuleNotFound失败；实现后 `20260913t135419z-42679-54c4cbc9` 5 passed（7.41秒）、清理成功，Ruff通过。生产备份恢复演练仍未执行。
- 新8文件快照 `issue08-review-upgrade-7b_c_8d1` Standards 0新增发现，Spec审查进行中。包括升级入口/真实数据库测试/授权计划与文档，以及本轮已证实的浏览器夹具修正。
- 定向E2E R1已终止：共享组16 passed/9 failed；Operator access隔离组通过，Dataset/Worker恢复隔离组通过，researchers/invitations组在发送证明验证码时收到429失败。汇总 `.local/e2e-runs/1789306101453-26587/results.json`。新增镜像E2E已开始复验Batch滚动、DailyTrack资源、provider终态、窄屏控件和Folder摘要；本轮过滤表达式没有匹配Operator Market的实际标题，Market必须另行定向运行。
- 镜像R7 `20260913t132448z-24040-df52e7ce` 退出1、清理0。已越过原目录缺失；失败点是RustFS恢复后的夹具指标采集：目标2026-08-11超过Replay声明的request_end。仅为镜像fixture设置本次目标end，保留Replay拒绝未记录区间的生产规则；完整镜像复验尚未运行。

- 升级快照 `issue08-review-upgrade-7b_c_8d1` 的Spec已完成0新增偏差，与Standards串行完成。镜像fixture离线Replay实测初始2026-08-05及恢复2026-08-11各返回2份指标报告。Web类型检查退出0。
- 当前最新镜像定向E2E运行 `20260913t135621z-44031-eaddb034`，共6测试，日志 `/tmp/issue08-e2e-regressions-r2.log`；此刻尚未终止，不记为通过。后续仍须单独验证Operator Market（实际标题Operator Market submission and response recovery）、并发/Host/context失败、验证码429及完整镜像恢复。

## 后续验收推进 — 2026-09-13

- E2E `20260913t135621z-44031-eaddb034` 已终止并清理：5 passed/1 failed（4.4分钟）。两类Batch、DailyTrack、provider恢复及移动44px控件均通过。Draft在进入Data前仍显示Checking access，仅get-session200，5秒页面等待超时；此次未进入Draft主体，不能判定其功能通过。汇总 `.local/e2e-runs/1789307779144-43992/results.json`。
- OTP失败定位为测试在填写后取消步骤仍重复发送验证码，触发当前email-code每60秒5次限制。三处取消只填占位码；真正发送若429，严格核对RATE_LIMITED及1..60秒Retry-After，等待服务期限后仅重试一次，仍要求200。生产规则未变。固定快照 `issue08-review-otp-vv8ay0gx` Standards→Spec各0新增，E2E TypeScript检查退出0。
- 已启动剩余E2E `/tmp/issue08-e2e-remaining-r3.log`，过滤并发、Host恢复、Core单/批上下文、Draft以及Operator邀请和Market；前一重型E2E已终止后才启动。当前未声明通过。
- 隔离备份恢复首轮 `20260913t140110z-45762-eff0460f` 在pg_restore失败，退出1、清理0；本机pg_dump为18.0，首次脚本未保留restore stderr，不能断言确切原因。R2改用同一PostgreSQL容器内的pg_dump/pg_restore并保留经凭证脱敏的错误，日志 `/tmp/issue08-backup-restore-r2.log`，结果待取得。仅创建和删除本次独立演练数据库，未触碰生产或共享开发数据。

### 备份恢复通过与生产只读复核

- 隔离演练R2 `20260913t140453z-47714-f4c8a577` 退出0、清理0。使用同一PostgreSQL镜像客户端导出181267字节、权限0600，SHA256 `7cf7120f595413313c2d1499db2d84d0ef3cd6bb9fffa48164f4e8587c4c72fb`。先升级源演练库，再将升级前备份恢复到另一独立库：55张业务表逐行一致、旧合同一致，恢复库再升级及当前合同核验通过。此为历史fixture演练，不能代替生产切换前的真实备份/恢复验证。脚本及摘要保存在 `.local/field-expansion-226-integration-backup/rehearsal/`。
- 2026-09-13T14:07:28Z生产只读复核：Head仍为17f5694f…，4053sessions、截至2026-09-09，schema仍6f04fe…；Run919succeeded/24failed，Batch209succeeded/2failed，未发现非终态。生产未改变；切换前仍需暂停入口并复核所有相关Worker/Track/刷新租约。

### 剩余E2E第三轮与容量边界

- 共享组 `20260913t140508z-47905-67f5ecf7` 4 passed/1 failed（3.1分钟）：Host重启、单/批上下文压缩和Draft通过。容量测试本轮已验证50个同时accepted/running及代理held，失败转到满载后首次加载Chat：14:07:30Z bootstrap POST503耗时3092.7ms，页面显示Workspace setup unavailable，未发出第51次请求。Core middleware记录unmatched503，Auth验证边界2秒；确切底层耗时原因仍未确认，不将此失败宣称已修复。后续held运行约98–101秒后MCP_TRANSIENT失败是此测试未释放期间的观察，不能作为50请求完成证据。
- 容量测试仅将页面初始化提前到施加50个并发请求之前，继续验证实际第51次拒绝、未新增Session、50个最终成功及显式重试，保持所有超时与资源上限。固定快照 `issue08-review-capacity-2ja3gjhp` Standards→Spec均0新增；此测试不证明满载首次导航可用。
- Operator邀请隔离组 `20260913t141045z-51264-800b3ce6` 1 passed（29.6秒），OTP取消和限流处理修正已通过真实UI路径。Market隔离组 `20260913t141253z-52726-0edc1d1f` 仍运行。

- 剩余E2E R3现已终止：共享4通过/容量1失败，两个Operator隔离组均通过。Market组 `20260913t141253z-52726-0edc1d1f` 1 passed（43.0秒），包括相同as-of刷新no_change及响应丢失恢复，证实daily_basic文本规范化修复。容量独立R4已启动 `/tmp/issue08-capacity-r4.log`；此前重型E2E入口退出1并完成清理后才启动。
- 满载初始化503进一步证据：Auth同窗会话核验成功耗时8–533ms；Core记录503约2588ms，目标14:07:30附近缺少对应Auth完成记录。尚不能区分连接、调度或其他延迟，不基于这一结果修改生产认证截止时间或添加自动重试。

- main集成前备份复核：原main仍fc94e3aa…，38个原文件与对应备份逐字节长度/SHA256均一致；此次未修改main。已同步工单索引与08顶部的最新授权说明，避免将最初“仅发布工单”和原禁止结构升级的描述误读为当前执行边界。容量R4 `20260913t141524z-54325-8ba5a2ec` 仍运行，不重启或并行启动其他重型门禁。

### 容量准备阶段复现与执行限制

- 容量R4 `20260913t141524z-54325-8ba5a2ec` 已退出1并清理：20秒期望50/50/50，实际45/45/15。38个MCP_TRANSIENT、3个INTERNAL_FAILURE均停在step_count=0，仅4个完成。未通过。
- 保留环境诊断轮 `20260913t141959z-56986-6cfcd21b` 已退出1；50个accepted/running曾满足，随后浏览器未收到AGENT_CAPACITY。脱敏终态日志计51个运行：32个MCP_TRANSIENT（均step_count=0，约3.2–4.6秒），19个完成。说明本轮容量在准备失败后释放，第51个运行被接纳；不能通过修改提示断言解决。令牌交换、MCP连接或发现的具体失败边界仍未分离。
- 保留失败项目 `thesistrace-test-20260913t141959z-56986-6cfcd21b`，run.txt标记cleanup_status=kept，终端session94565退出1。最后一次Docker只读盘点确认隔离容器仍在；不存在仍运行的E2E测试进程证据。
- 已准备 `/tmp/issue08-mcp-preparation-probe.mjs`，通过现有私有Auth fixture及实际McpRunFactory分开记录令牌交换/发现耗时与状态，50并发、不打印凭证。尝试执行被自动审批拒绝：审批服务额度用尽。该脚本尚未执行、未经验证，不作为实测证据；没有改用其他执行路径绕过拒绝。
- 快速准备阶段诊断、完整镜像资格验证和最终验收仍待完成。08未提交，main及生产未切换。审批执行能力恢复后需先运行阶段诊断，再按证据修复、复审和验收，最后清理本次保留环境。

### MCP 容量准备失败定位与修复

- 额度查询恢复 ordinaryUsageAllowed=true 后，重新申请原命令并获准，未绕过审批。快速实际工厂循环R1：50次令牌交换全部200、21次MCP准备成功；单次准备171ms通过。直连Core50次仅29次成功，证明代理不是唯一来源；带阶段计时直连13/50，Agent事件循环最大69ms，server/discover部分触及2000ms、tools/list约4秒。
- 单独profile50轮静态目录：1900次schema生成累计12.152秒，总12.86秒；重复Pydantic JSON Schema生成占约95%，在Core异步请求线程中同步执行，拖延其他发现/握手。
- 修复在registry按模型类型有界缓存静态schema，每次返回深复制；请求权限、可见工具及业务handler仍请求独立。公共schema嵌套变更隔离测试新增，原权限/协议合同一并验证43 passed（2.75秒），Ruff通过。容量原E2E已是修复前失败回归，未新增基于机器速度的计时断言。
- 仅将该文件应用隔离API容器并重启后，同代理同超时实际工厂50/50成功，exchange最长170ms、discovery最长1150ms、整体最长1320ms、Agent事件循环最大16ms。此为快速定位证据，不能替代最终镜像。诊断脚本及无凭证阶段结果保存在 `.local/field-expansion-226-integration-backup/capacity-diagnosis/`。
- 保留项目通过现有cleanup入口退出0清理；已启动新镜像原容量E2E，日志 `/tmp/issue08-capacity-schema-fixed.log`。固定两文件快照 `issue08-review-schema-12oepf0n` 的Standards审查进行中，完成后再启动Spec；尚未声明整票通过。

### 第二处容量根因：预算策略读取占用数据库连接

- 新镜像容量 `20260913t143643z-64672-9d42b285` 失败：原50同时接纳及第51次容量拒绝已成立，无MCP准备失败；释放后32完成、13 INTERNAL_FAILURE（step1）、5 CONTEXT_COMPACTION_FAILED（step0）。已终止清理，不能记为整体通过。
- 保留环境轮 `20260913t143903z-66071-1ba8562b` 同样未完整通过；直接HTTP50调用、加回工具挂起/释放、仅重启Agent后三种最小化均50/50完成。原浏览器临时副本R1再现执行失败，R2/R3暂时通过，API及Agent冷启动R4再现，并出现AGENT_UNAVAILABLE；不将暂时通过视为解决。
- 仅隔离容器临时安全诊断确认 DATABASE_UNAVAILABLE 来自pg-pool.connect，调用位置分别是model-budget.reserve及context仓库读取，无需输出原异常或凭证。原预算预留拿着连接和研究者事务锁等待远端Auth，串行占用连接池。诊断jsonl已保存到 `.local/field-expansion-226-integration-backup/capacity-diagnosis/`。
- 新增真实数据库回归：单连接池在等待受控Auth策略时其他查询应可用。旧实现1failed/5passed，精确错误timeout exceeded when trying to connect。仅将每次Auth策略读取提前到获取连接前，锁内额度总额检查和写入保持；修复6passed（641ms测试），Agent build通过。固定 `issue08-review-budget-f5gf12g6` Standards→Spec各0新增。
- 已移除隔离容器DEBUG注入，源代码及正式dist无DEBUG-i08；两服务冷启动后原容量浏览器临时副本完整1passed（20.6秒）。临时测试副本已移到.local诊断目录，不纳入最终suite或提交。该快速容器复验不代替新构建镜像。
- 原正式容量用例恢复到施加50运行后才首次打开Chat，同时保留50同时运行、第51次拒绝、50全部成功及显式重试。这样继续覆盖此前满载初始化503，未延长超时或降低并发。新镜像验收仍待执行。

- 容量测试恢复满载首次导航增量 `issue08-review-capacity-restored-8tonidu_` Standards→Spec各0新增。保留诊断环境已由现有cleanup入口退出0清理。已启动完整 `pnpm check`，日志 `/tmp/issue08-final-product-check.log`；各阶段仍串行，最终结果待取得。

### 完整产品门禁首段与续跑

- `/tmp/issue08-final-product-check.log` 的 `pnpm check` 退出1：tooling29通过、Ruff通过、Python1422通过/1失败（158.45秒）。唯一失败是test_core_has_one_operational_output_schema_and_no_log_files的精确CLI清单尚未登记新升级入口；并非结构升级输出错误。
- 显式清单仅新增 `migrations/financial_indicator.py`，定向测试1passed（0.83秒）。其余输出限制不变。快照 `issue08-review-cli-receipt-xdplbzhv` Standards0新增，Spec待完成。
- 使用 `.local/issue08-continue-product-check.mjs` 原样读取仓库quickCommands剩余条目（slice(4)），然后依次现有test:browser、test:integration、test:e2e入口；日志 `/tmp/issue08-final-product-remaining.log`。这是失败修复后的分段验证，不宣称前一pnpm check命令退出0；不重复未变化的已通过Python范围。
- 临时浏览器诊断副本已从tests目录移除，故障分类和无凭证数值记录保存在.local；临时浏览器trace/video证据目录已清理，正式隔离运行器证据保留。

- 续跑首轮在Agent类型检查退出1，原因新增测试Promise.withResolvers不在现有TS lib中；已改显式Promise resolver，不更改生产代码或编译配置。语法增量 `issue08-review-budget-test-syntax-_8w6otdk` Standards→Spec各0新增。续跑R2日志 `/tmp/issue08-final-product-remaining-r2.log`，Agent类型检查/648单元、Auth类型检查/200单元、Web类型检查/356单元及E2E类型检查均通过；浏览器32项通过，进入Core完整集成 `20260913t150221z-84303-355d07ab`。先前CLI清单Spec亦0新增。
- 浏览器测试生成的无关 `.scratch/research-global-sort/metric-filters-mobile.png` 已恢复为本分支HEAD字节，不纳入08。

- 服务器只读空间/路径预检后，审批允许创建独立0700候选暂存目录并上传07已验证数据，rsync排除HEAD.json。暂存路径 `/opt/thesistrace-staging/field-expansion-226-77d45ba1e494/candidate-data`，日志 `/tmp/issue08-candidate-staging-upload.log`，传输尚未完成。此为发布准备，不是生产卷合并、结构升级或Head发布；后者仍待门禁。

- Core完整集成 `20260913t150221z-84303-355d07ab` 普通499 passed（1169.69秒）及6项依赖重启场景全部通过，隔离环境清理完成。完整续跑进入Auth、Agent集成，E2E尚未完成。
- 暂存/合并方案快照 `issue08-review-cutover-staging-63_f7rzw` Standards→Spec均0新增。候选传输清单已从本地逐文件SHA256生成：71929文件、8593065687字节，清单SHA256 `90e96508648136cc0bef5786758790a7caffde8fdccac574f7cdd8073fce345c`；路径 `.local/field-expansion-226-integration-backup/candidate-transfer-manifest.json`。该清单排除HEAD.json，目的端校验仍待上传完成。

## 母规格验收映射（发布前汇总）

01–07 的独立提交及其工单记录保留具体红绿测试过程；真实来源与全历史候选统一引用 [07 验收索引](issue07-acceptance-index.md)。以下本轮工程证据来自完整快速检查的已通过部分、失败单项修复后通过，以及Core完整集成 `20260913t150221z-84303-355d07ab`；不据此宣称原始 `pnpm check` 命令退出0或生产已切换。

| 母规格 | 实际证据与范围 | 尚待发布验证 |
|---|---|---|
| T01 | Field/Alpha合同和真实候选226列读取；19新增TTM及原字段语义见01、03、06、07验收 | 当前消费者部署后的目录复核 |
| T02 | 07逐来源资格报告、实际DSL读取及单位规范化测试；明确历史修订证据限制 | 不以上线消除历史证据限制 |
| T03–T04 | `test_financial_series.py` 的累计转TTM、修订可见性和缺失行为；真实三表重建及差异归因见07 | 无额外历史补采要求 |
| T05 | Alpha公开合同与 `test_ttm_research_series.py`，覆盖期间传播、运算缺失及样本覆盖 | 新研究沿用当前合同 |
| T06 | 指标证据/序列及三表公开读取测试；07公告和隔离报告 | 历史回填不宣称完整PIT |
| T07 | 候选种子闭包测试、5550身份及333退市身份的07完整历史资格 | 不开放pre-2010研究 |
| T08 | 供应商适配、采集、指标进度及每日刷新真实依赖测试 | 切换后正常刷新 |
| T09 | daily_basic适配/Store与依赖准入合同；指标缺失和仅价格准入边界 | 新Head目录与准入复核 |
| T10 | 普通/Batch/Track离线读取一致性和实际候选列投影，详见05、07 | 切换后新研究与Track |
| T11 | Store、多家族刷新与每日刷新集成；本轮Operator Market定向E2E通过 | 生产正常刷新保留新增家族 |
| T12 | Head并发、发布前失败、回执故障恢复与GC真实依赖测试 | 生产保护/完整校验/CAS回执 |
| T13 | 07固定研究输入及GC验收、当前Generation collection及研究/Track集成 | 实际旧结果读取、引用保留和Track推进 |
| T14 | Alpha缺失规范、TTM研究序列与现有策略/Track计算测试 | 新研究结果核对 |
| T15 | 32项浏览器组件通过；226字段混合来源研究和Track定向E2E通过 | 完整E2E终态及发布浏览器核验 |
| T16 | 明确授权的结构升级5项集成、备份恢复fixture演练及权限合同 | 最终镜像资格、真实备份恢复、部署与切换 |

Auth完整集成 `20260913t152605z-91721-f6869fd2`：145 passed；Agent完整集成 `20260913t152751z-92435-96a237cb`：97 passed，含预算连接占用回归。两者清理完成。完整E2E启动于 `20260913t152943z-93362-d4339fb3`，结果尚未产生。

- 最终整合快照 `issue08-review-final-18lzp74e` 共46文件，Standards→Spec均0新增可操作发现。结论仅覆盖发布前代码/方案，不替代后续实测。
- 完整E2E共享组 `20260913t152943z-93362-d4339fb3` 在容量及Host重启再次失败：容量已通过50同时接纳、满载导航、第51次拒绝及资源上限，但释放后的请求并非全部正常结束；Host退出143但stdout未出现agent_shutdown_completed。快速定向通过不足以证明全套环境稳定；此前两处修复不能声明解决所有容量问题。
- 当前运行结束事件可见多项INTERNAL_FAILURE/CONTEXT_COMPACTION_FAILED、另有后续AGENT_RUN_INTERRUPTED；只读PostgreSQL日志未发现死锁、语句/锁超时、连接数或OOM类别。精确本轮底层异常尚未取得，不能据此调整超时或并发。完整套件仍继续执行，保留首轮证据，不重复已通过的Core/Auth集成。

- 共享E2E已记录四项失败：capacity、Host restart、context normal（输入框disabled直至90秒）、admitted artifacts/Track（Delete Chat菜单点击时不稳定/DOM脱离，240秒）。后者尚未发起删除，不构成研究丢失证据。容量附件记录596869120字节内存及相同峰值，低于4GiB上限；仍需精确定位剩余并发异常与可能的后续影响。
- 临时诊断准备 `.local/field-expansion-226-integration-backup/capacity-diagnosis/pool-probe.mjs`，只记录连接获得/占用耗时、池数量与事件循环延迟；尚未执行，不作为实测，不纳入生产代码或提交。

- 删除菜单最小真实浏览器回归先失败：研究内容实际scrollTop变为100后菜单消失。SessionHistoryList原document捕获scroll关闭了无关内容滚动；修复仅在滚动目标包含触发器时关闭，保留resize/outsidepointer等行为。sidebar-layout三项3passed7.9s，Web类型检查通过；三文件快照 `issue08-review-sidebar-scroll-logkwrf3` Standards→Spec各0新增。原完整E2E镜像尚不含本修复，研究保留用例仍需复验。
- 候选8.593GB中JSON5.668GB，计划启用传输压缩。已获工具审批仅SIGINT停止核实PID86214的原rsync，原session39503退出20且保留partial-dir。恢复压缩rsync被自动审批拒绝，理由缺少用户对具体数据及目的地的明确外传授权；未改走其他路径。已向用户单独请求允许继续上传至同一独立暂存目录，当前待答复，传输暂停。原已传内容保留，生产卷/DB/Head未变。

### 完整E2E续跑终态

`/tmp/issue08-final-product-remaining-r2.log` 的session50379退出1：共享组67 passed/4 failed（17.9分钟），后续8个隔离组全部通过，合计75 passed/4 failed。最终汇总 `.local/e2e-runs/1789313372507-93248/results.json`；隔离环境与镜像清理已完成。通过范围包括完整226目录混合研究/Track、Draft、Operator会话撤销/权限/邀请、Market、Financial/Industry及Dataset/Worker恢复。四项失败不能因其余通过而忽略。

仅在完整入口终止后，启动缩小序列 `THESISTRACE_TEST_PLAYWRIGHT_GREP='Chat Batch|Chat saturation' mise exec -- node tooling/test/cli.mjs e2e --keep-environment`，日志 `/tmp/issue08-capacity-after-batch-r1.log`，复现Batch后的容量失败并保留故障环境。未扩大超时、并发额度、连接池或资源上限。

### 容量失败的进一步定位与修复

保留环境的 R2/R3 四例序列均为 3 passed/1 failed。安全探针测得事件循环最大延迟 2812ms、连接获取最大 3004ms；R3 CPU 采样按模块累计 MCP SDK AJV 12.232 秒，表明重复同步编译 schema 占据事件循环。未扩大超时、连接池或容量。

新增工厂作用域、128项、有界的完整 schema 内容缓存；每种内容沿用 SDK 默认 AJV 独立编译，同一 `$id` 的不同内容不共享编译结果。仅缓存编译器，不缓存认证、连接、权限或业务结果。新增现有 SDK 2.0.0 的直接依赖，锁文件其他依赖保持不变。12项定向测试、Agent build/typecheck 通过；固定五文件快照 issue08-review-mcp-validator-cz79orjz 的 Standards→Spec 均0新增发现。

R4 同一隔离负载 4 passed（1.4分钟），日志 /tmp/issue08-pool-browser-r4.log，CPU 证据 capacity-diagnosis/batch-r4-agent.cpuprofile。该结果来自诊断容器内复制正式构建，尚不等于最终镜像验收；随后清理整个诊断环境，使用仓库入口重建镜像复验 Batch、容量、Host restart、context 及研究保留流程。临时探针与复制测试不进入提交。

R3/R4 AJV采样CPU累计12.231686秒→0.549283秒（不同采样空闲时长，比较同四例负载的模块累计值，不当作完整请求时延）。汇总 mcp-schema-cache-cpu-comparison.json。保留环境通过既有cleanup入口退出0；临时浏览器原始目录R2/R3/R4已清理，安全性能证据保留。正式镜像定向E2E日志 /tmp/issue08-final-affected-e2e-r3.log，当前执行中。

正式镜像定向运行20260913t163349z-23711-869141ba：12 passed/1 failed（3.5分钟）。Batch三项、Host restart、context全部及研究/Track删除保留通过；容量50接纳与51拒绝通过，但释放后12项INTERNAL_FAILURE，故容量问题尚未解决。只读终态汇总确认12个INTERNAL_FAILURE；R4一次通过不构成稳定性证明，禁止通过增加超时或额度掩盖。继续缩小定位其底层异常。

### 进一步区分容量剩余边界

正式13例（20260913t163349z-23711-869141ba）12通过/1容量失败；环境清理0。单容量R5（20260913t164350z-28034-5beb2d19）49 INTERNAL_FAILURE/1完成。仅分类探针R6确认原始DATABASE_UNAVAILABLE来自session-repository.withSessionMutation获取连接，调用为context checkpoint/raw messages。被动池事件R7观察10连接满、128等待、最长占用1277ms；不替换connect/release。带连接池包装探针的通过受时序影响，不用作最终验收。

contextInput合并三次Session上下文读取到一次既有锁/ownership事务，新增真实DB权限与发布输入断言先红后绿；22单元、build/typecheck通过。固定四文件issue08-review-context-input-tzy931ao Standards→Spec均0。但独立R8容量仍失败，不能将合并读取单独认定为修复。

驱动源码证实connectionTimeoutMillis同时限制网络建连和已建连接池排队；2秒在合法事务排队中提前终止已接纳工作。真实DB故障注入10连接各占用2.2秒，50查询排队，原值失败。业务池改为10秒有界等待（也影响业务新建连接），与现有Session事务上限相称；health/initializer仍2秒、pool10、资源与测试时限不变。回归通过。Standards发现注入成功未断言，补齐所有占用查询fulfilled后重跑1通过2.27秒；R2 Standards、Spec均0，快照issue08-review-pool-wait-r2-o3n7_rka。历史记录“不改超时”仅指此前阶段，本次有明确排队证据的业务等待调整须如实披露。

R9在该修复下48完成/2请求超时，数据库空闲且另2仍running。发现测试代理竞态：holdResponse在上游fetch前捕获，切pass仅释放已登记barrier；迟到上游响应在pass之后仍按旧hold进入90秒barrier。正在建立确定性HTTP回归（受控上游在模式切换后才返回），未修正生产HTTP逻辑或放宽E2E时限。

代理竞态确定性HTTP测试两项先红Timeout，修复后2 passed350ms；仅test-fixtures控制轮次revision与两项回归，Standards→Spec均0，快照issue08-review-proxy-barrier-ze81qlfu。R10先因重启后动态端口变化未进入负载；更正端口后同fixture身份重复创建拒绝，亦不算容量验证。改新身份R11正式进入负载为33完成/18 MCP_TRANSIENT，无数据库等待失败。

真实共享工厂诊断mcp-shared-factory-r12.json：50/50成功，eventloop峰58ms，但server/discover1801ms、tools/list1839ms，接近2秒连接截止；完整Run额外准备占用使余量不足。connectTimeout改复用原5秒discovery期限，Run与工具调用总期限不变，无重试fallback。原配置回归1fail8pass→12pass，build通过；固定issue08-review-mcp-budget-wzb_o5oq Standards→Spec均0。此处明确调整2秒握手期限，非仅schema性能修复。

R12移除全部已加载探针、冷启动Agent后的完整容量1 passed28.2s（/tmp/issue08-pool-browser-r12.log），含满载首次导航、50同时接纳、第51拒绝、50全部完成、显式重试。该结果仍为保留环境装载正式构建；接下来完整清理并用新镜像复验受影响流程。临时浏览器R5–R12原始目录已清理，安全诊断证据留于.local。

最终Agent快速检查：651单元通过35.96秒，类型检查通过，诊断环境20260913t164350z-28034-5beb2d19清理0。完整Agent集成20260913t171759z-40210-795ecd54为99 passed/1 failed（148.42秒）。失败仅overlapping Thread独立运行测试的默认1秒vi.waitFor；错误数组在报告时已达到期望两项，未见产品终态失败。该case无1秒SLA，改两个条件等待为5秒、整体15秒，所有行为/权限/持久化断言保留。定向1 passed（case3.239秒，总9.89秒），日志/tmp/issue08-overlap-wait-green.log。单文件固定issue08-review-overlap-wait-or65815c Standards→Spec均0。不能写成第一次完整集成100通过，应记录99+定向修复1。

最终新镜像13项定向E2E20260913t171901z-40746-a02f1901运行中，日志/tmp/issue08-final-affected-e2e-r4.log。最新应用包含MCP缓存/5秒发现、上下文合并、10秒业务池等待；故障代理轮次修复由仓库只读挂载提供。尚待正式终态与后续镜像资格验收。

最终新镜像定向E2E session1696退出0，13 passed3.4分钟，环境清理0。完整镜像资格R8已启动，日志/tmp/issue08-image-qualification-r8.log，当前尚未完成。

### 预发布代码验收终态

完整镜像资格 R8（/tmp/issue08-image-qualification-r8.log，session61946）退出0；Core run20260913t172742z-44945-89c40f54的所有阶段通过，包括故障恢复、Operator真实浏览器、最终证据与secret scan，cleanup_status=0。后续Auth、Agent、Caddy独立镜像检查均执行成功，顶层入口正常完成。404/502等输出属于网关拒绝/故障场景，不能单凭日志文字误判失败。

最终62文件固定快照issue08-review-final-r3-eiiu4neo，Standards后Spec串行审查均0新增可执行问题。最后一次Agent类型检查session92663退出0。准备以独立提交保存08的已验收实现和切换计划；工单仍不关闭，生产切换、真实备份、main集成及干净提交release gate尚待完成。候选上传保持暂停，等待具体目的地的数据传输授权。

### 干净提交发布门禁 R1

提交39e4b88cd4f6f595472a225c51b06a9436c0d030已保存62文件；原有inventory构建器、223旧清单及ticket-drafts仍排除。新建并验证干净detached worktree field-expansion-226-release，锁定依赖离线安装；MISE仅在命令环境显式信任已经读取的固定工具配置。

/tmp/issue08-clean-release-gate-r1.log，session17943退出1。工具29通过、Ruff通过、Python1422通过/1失败（176.86秒）。失败为test_agent_host_is_a_private_node_package_without_research_authority精确依赖白名单遗漏新增直接@modelcontextprotocol/client；SDK仍沿用原锁定2.0.0。补齐单项白名单，不删除依赖/禁止导入断言。原文件9测试通过0.10秒、Ruff及diff检查通过。后续阶段未执行，不能声明release gate成功。

单行固定快照issue08-review-sdk-allowlist-1mi_45eu的Standards→Spec串行复审均0新增。保留首次门禁失败证据，独立补充提交后继续干净提交门禁。

### 干净提交发布门禁 R2 与最后一项测试修正

R2固定dde78933，/tmp/issue08-clean-release-gate-r2.log，session15660退出1。快速检查全部通过：Python1423、Agent651、Auth200、Web356、工具29及全部类型/lint；浏览器组件33通过。Core集成run20260913t180352z-77993-3dadfda6为499普通+6重启全部通过，普通阶段1305秒；Auth145、Agent100真实依赖全部通过。

E2E共享run20260913t183254z-87604-95e8b428为70通过/1失败（11.7分钟），后续8隔离组全部通过，合计78通过/1失败；汇总在field-expansion-226-release/.local/e2e-runs/1789324361277-87391/results.json，清理记录均0。唯一失败是MCP断连用例serviceLogs未读出Agent日志，之前MCP_TRANSIENT和代理计数断言已经通过。

原helper未记录error.code；对该次最终脱敏Agent日志重放，默认spawnSync缓冲得到ENOBUFS，8MiB得到完整1146499字符、退出0。这支持缓冲不足诊断，不伪称当时已直接保存ENOBUFS。证据.local/field-expansion-226-integration-backup/log-buffer-replay.json。单行改用同目录chat-privacy现有8MiB上限，保留完整日志、隐私断言和10秒超时。类型检查通过，固定快照issue08-review-log-buffer-97rcmbe0 Standards→Spec各0新增。

定向真实E2E run20260913t191042z-16754-d22cc3e3（/tmp/issue08-mcp-log-buffer-e2e.log，session6964）1通过14.2秒、退出0、清理0；覆盖断连失败、完整日志隐私检查、刷新后持久化失败与显式恢复。最终代码相对完整镜像R8对应39e4b88c只变化测试白名单、测试日志缓冲及记录，apps/deploy/packages无变化，复用已通过的完整镜像验收，不无故重跑未变镜像。

必须区分：完整check:release命令R2没有零退出，且因E2E失败没有再次进入镜像阶段；当前结论是所有所需边界由本次完整产品检查、修正后定向验收和未变代码的完整镜像资格记录覆盖。不能写成首次整条发布命令通过。生产发布与最终main核验仍待执行。

浏览器测试生成了一张已跟踪截图差异，已保留到验收worktree的.local/issue08-generated-metric-filters-mobile.png，再恢复该隔离worktree中的原跟踪字节；没有提交生成差异，也未触碰main原文件。
