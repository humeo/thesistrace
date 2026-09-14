# 01 — 统一现有字段目录、准入和家族合同

**What to build:** 先用现有 12 个字段贯通一个 Field Catalog 和当前 Data 合同，让 Researcher 从页面、HTTP/MCP 或 Agent 查询和提交公式时得到相同的可用性判断；既有研究仍能用其冻结的数据重试。为后续逐个接入来源提供可运行的基础。

**Blocked by:** None — can start immediately

**Status:** complete

**Execution contract:** 在从 main 创建并核实的新 worktree 中，严格按 01→08 串行执行。每票开始实现前先记录 Plan；完成实现后逐项验收，进行代码审查、修复及复审，更新 tracker 并形成该票独立 git commit，完成后才开始下一票。审查同样串行，不并行委派实现或审查。

**Latest user decision:** 按用户最新要求，直接实现当前合同，不做兼容、版本迁移或 vXX 升级链；这覆盖母规格中有条件引入迁移的旧提议。保留数据、原有字段语义与必要研究引用的要求继续有效，不将“不迁移”解释为允许清库。

**Execution order:** 01；完成本票验收、复审、tracker 更新和独立提交后再开始 02。

- [x] Data 统一拥有字段身份、来源语义、家族、覆盖、研究可见时间和读取；Alpha Language 继续负责作者名与表达式。原有 12 项的作者名、Canonical Field 身份、单位、期间及范围保持不变，不新增别名或供应商 DSL。
- [x] 用实际所需字段和家族集合替换财务布尔开关及固定两组分派。区分系统支持、Generation 包含、研究范围可用；HTTP/MCP、Web、Worker 和 Agent 全部使用一个当前合同，不保留旧响应或旧开关分支。
- [x] Catalog 与 Overview 基于同一次 Head 读取并携带相同 Generation；提交研究固定 Head 后重新验证实际依赖。财务未就绪时，仅使用 close 的公式仍可提交，依赖未就绪财务字段的公式明确拒绝。
- [x] 旧 Generation 按自身声明的字段子集通过同一套格式、校验和读取规则。不能因为全局目录扩容而判旧根无效，也不能为旧根补挂新字段或退回当前 Head；已有 Run 重试的冻结坐标保持。
- [x] 统一读取按所需字段、股票、Session 和 Calculation Warm-up 工作；保留财务稀疏版本。缓存隔离 Generation 与读取范围，成本按实际依赖计量，不为单字段读取展开整个目录。
- [x] 家族组合和刷新以目标家族为更新边界，保留所有非目标已验证引用及其字段、覆盖。用现有行情、财务和行业的刷新证明该规则，不继续维护只枚举旧家族的特殊保留清单。
- [x] Data 页仍为四个顶层区块；Market 和 Financial 依据研究分类聚合实际家族，部分来源未就绪不能显示整类全部 ready。目录数量、中文/DSL 搜索、用途/来源/期间筛选、公式补全与 HTTP/MCP 一致。
- [x] 字段信息支持含义、单位、期间、范围、可见规则、来源、适用性和覆盖；Agent 按需查目录，不把未来 226 项全部塞入每轮提示。页面遵守现有设计规范。
- [x] 以现有 12 字段 Generation 演示查询目录、提交公式并完成研究；另验证目录查询后 Head 变化时按新冻结依赖重查，以及旧 Run 用旧根读取。通过受影响公开模块、合同、组件及必要的真实依赖验证。
- [x] 直接调整当前实现及其调用方，不设计版本迁移、vXX 升级链或旧版本兼容路径。复用现有格式和已存来源构建必要候选，保留原始历史与被引用数据；不得自动清库或改 schema 指纹绕过校验。

**Verification:** 母规格 T01、T09、T10、T11、T15、T16 中涉及既有字段的部分。独立演示使用现有数据；本票不宣称新来源已采齐，也不单独上线。

## Comments

- 2026-09-12：用户确认发布工单。已纳入最新的串行执行、每票 Plan / 验收 / 审查修复复审 / tracker / 独立提交，以及不兼容、不做版本迁移的要求。

## Plan — 2026-09-12

执行位置：独立 worktree `codex/field-expansion-226`，从 main 的 fc94e3aa270b3c9a2c809de63b8d0b755aa2995c 建立并验证为干净 checkout。原工作区的并行修改不带入实现；本功能规格、字段附件和工单已复制到隔离工作区。

1. 先建立目录按实际字段集合筛选、依赖按 Canonical Field 所属家族解析、旧 Generation 按自身声明校验的失败回归；保留原 12 项语义。
2. Data 统一提供每家族实际字段、覆盖及可用性；Catalog 与 Overview 共享冻结 Generation 坐标，HTTP/MCP/Agent 改用同一合同，研究准入仍重新固定并验证其依赖。
3. 修正读取、缓存和成本边界，以及刷新只更换目标家族并保留其他家族引用的规则；不增加兼容分支、迁移或新格式版本链。
4. Data 页面按目录研究分类聚合家族，提供实际数量、状态、中文/DSL 搜索和用途/来源/期间筛选，更新所有当前合同消费者。
5. 依次运行受影响公开模块、HTTP/MCP 合同、Web 类型/组件及必要的隔离真实依赖测试；以当前 12 字段演示查询、提交、执行和旧根重试，保存证据。
6. 串行执行 Standards 审查和 Spec 审查，逐项修复并复审；验收项满足后更新 tracker 并独立提交本票，然后才开始 02。

当前状态：Plan 已记录，实现与验证尚未完成。审查采用 code-review 技能的双维度，遵循用户串行要求依次执行，不并行委派。

## Implementation progress — 2026-09-12

- 已按 Plan 建立并复现失败回归：目录实际字段筛选、Canonical Field 重复身份、实际家族依赖、旧根在支持目录扩容后重开、行情刷新保留旧家族字段子集、单快照页面加载、跨家族目录聚合。
- 已实现目录实际字段筛选及 Generation 坐标；HTTP/MCP 去掉财务布尔目录开关；Data/Research 页面通过一次 Data 响应取得目录与覆盖。来源元数据和中文字段名由 Data 字段定义提供。
- 已实现依赖保留实际字段和 Canonical Family 集合、旧根按自身声明校验、读取拒绝旧根缺少字段，以及行情刷新保留非目标家族引用和声明。
- 已实现逐家族支持/实际字段、覆盖与部分就绪描述，Data 页面按研究分类聚合，并增加中文/DSL 搜索和用途/来源/期间筛选。
- 已通过的阶段验证：Alpha/HTTP/依赖 68 项；旧根/刷新/就绪定向 4 项；逐家族状态 3 项；Data/Research Web 阶段曾通过 30 项。最新元数据与家族展示修改后的完整复验仍在进行，不能将此前阶段结果视为最终通过。
- 尚需完成：当前 MCP schema/尺寸基准与所有 fixture 更新、完整受影响测试及 lint/typecheck、实际依赖准入/读取/成本和刷新验收、搜索筛选交互/真实浏览器、串行 Standards 与 Spec 审查修复复审、tracker 完成与独立提交。未开始 02。


## Acceptance and review checkpoint — 2026-09-12

- 修正定向 columnar 测试的来源声明：该用例确实读取 6 个价格字段，使用合法的完整市场字段目录；共享最小 fixture 仍只声明 close。真实 HTTP 最小 fixture 的期望同步为 close 和市场 partial。
- 新增三种公开 slice 读取的冻结字段准入回归，先复现 read_market_slice 未拒绝缺失字段（1 failed / 2 passed），再补齐入口检查。修复后 mounted generation、financial candidate、family availability 合计 112 passed（51.64s）；此前 mounted generation 单独 61 passed。
- Web AlphaCatalog 类型补齐当前 Generation 坐标，tsc --noEmit 通过。
- Standards 与 Spec 已严格串行审查同一冻结 working-tree 快照：/var/folders/py/j9ws8lpn57g_syngj3b58b6h0000gn/T/field226-issue01-review-jkqp0lcg。以下 findings 尚未全部关闭，不得视为验收通过。

### Standards

1. P2：新筛选控件未满足 DESIGN 的手机 44px 触控尺寸。已补真实浏览器尺寸回归，先得到 40px 失败，再纳入现有手机/粗指针样式。桌面 1280px 和手机 390px 的搜索、来源/用途/期间筛选、无匹配与尺寸断言全部通过：2 passed（10.3s）。仍需在最终修复快照复审。
2. P2（判断性代码气味）：实际家族集合尚未成为准入和读取的共同事实，部分消费者仍压缩成 financial 布尔值并重新划分市场/财务两组。未修完。

### Spec

1. P1：ResearchRun / DailyTrack 的覆盖准入与两个存储读取入口仍未贯通实际家族依赖。需要更新所有当前消费者及不同家族覆盖的测试，不能把新依赖类型存在当作完成。
2. P2：行业组合仍通过旧 non-financial 清单加单独 financial 引用重建；根验证仍枚举四种旧家族组合。需要将已实现的市场刷新目标替换规则推广到其余组合并证明非目标字段、覆盖、引用完整保留。

### Running verification

真实依赖验收使用仓库隔离 integration 运行器，run id `20260912t125910z-40475-ca59eafe`，exec session `91572`。选择 Data/Financial/当前 Head/直接准入/生命周期/回收相关用例，并包含运行器所有后续重启阶段的目标。证据位于 `.local/test-runs/20260912t125910z-40475-ca59eafe/run.txt`。最近查询进程仍在运行，普通 pytest 已超过 68%，尚无最终结论；继续查询同一 session，不因等待或上下文切换重启测试。

下一步：收集当前隔离验收结果，按审查项完成家族依赖与组合规则；针对修改重新验证、串行复审、逐项验收及独立提交。01 未完成，02 尚未开始，不进行兼容或版本迁移。


## Family composition fixes — 2026-09-12

- 已复现 Spec P2 的实际缺陷：仅扩展可选家族注册集合，会令已有行业 Generation 在原格式校验中失效（新回归 1 failed / 1 passed）。根校验改为必需家族齐全、家族已注册、无重复且遵循稳定顺序；已存在内容无需重建或修改。
- 市场、行业、财务组合共用 `_replace_family_references`，只替换目标家族，保留其他已验证引用；移除行业组合的先剥离财务再拼回逻辑与四种组合枚举。维持当前持久化家族顺序和格式，未引入迁移或兼容分支。
- 修复后 mounted generation + financial candidate 回归 111 passed（47.32s）；新增行业、财务连续发布公开接口用例 1 passed，验证非目标完整描述、覆盖、字段、财务就绪声明及发布坐标保持。Ruff 和 git diff --check 通过。
- Spec P2 的实现修复已落地，仍待最终串行复审；Spec P1（实际家族依赖贯通 ResearchRun/DailyTrack/读取）仍未完成，不关闭本票。
- 真实依赖 session 91572 最近仍在运行，普通 pytest 已打印一个失败标记，尚未返回完整失败详情。不要重复启动同一测试；取得终态后先诊断该次证据。此隔离运行始于家族组合修复之前，不能用它证明后续组合修改的完整真实依赖验收。


## Family admission progress — 2026-09-12

- 已收取隔离 integration run `20260912t125910z-40475-ca59eafe` 的终态：209 passed、1 failed、262 deselected，普通 pytest 723.77s；退出 1，清理成功。失败发生在 `test_daily_track_uses_overlap_corrections_only_for_future_sessions` 对 `/api/data` 顶层键的旧清单断言；新增 catalog / generation_manifest_sha256 / available_field_ids / field_families 未纳入。该断言已更新，同时校验实际 Head、Catalog 坐标和字段集一致；整个用例仍待重跑。后续独立重启阶段未执行，不得声称通过。exec session 91572 已结束，不再轮询或复用。
- 新增逐家族覆盖准入失败回归，复现缺少公共检查方法后实现 `DataDependencies.unavailable_families`。每个实际依赖家族分别检查起止日期；字段计算包含 warm-up，行业仍按研究期。未依赖家族缺口不影响公式。
- Data 通过 `generation_family_coverage` 将已验证 Generation 的各家族覆盖投影为统一日期范围；已在真实候选组合测试中验证市场、财务与行业不同截止日期保持独立。
- `DatasetAdmissionSnapshot` 已改为必需 `family_coverage` 映射，删除单一 financial/industry 起止属性。当前全部 9 个测试构造器同步改用当前合同；ResearchRun 准入逐个处理实际缺口，不再使用 financial 布尔开关或单一财务覆盖。Operator 状态的同名展示属性不属于该准入合同，没有删除。
- 定向依赖、Snapshot、候选覆盖验证 9 passed（44 deselected，1.57s）；Ruff 与 git diff --check 通过。真实 HTTP/ResearchRun 对新准入合同仍待集成复验。
- 下一个具体步骤：把 DailyTrack 的覆盖裁剪/阻塞和两个 Series 读取入口接入相同实际家族依赖，删除剩余两组依赖布尔分派；补齐测试后复跑相关隔离验收（包括上述响应断言失败用例），然后对最终修改串行 Standards / Spec 复审。工单 01 仍未完成与提交，02 未开始。


## Unified family consumers and re-review — 2026-09-12

- DailyTrack 现在按相同 DataDependencies 检查实际家族覆盖与 warm-up，只取连续可用 Session 前缀，遇到缺口不跳过。Claim 保存具体 unavailable_families；缺口进入现有阻塞流程，财务/行业保留对应业务诊断，其他家族使用通用 Data Family 诊断。依赖对象的 financial / industry 布尔属性已删除。
- DataDependencies 增加请求字段按家族分组。行式与列式读取均通过同一个分组选择已注册解析器和冻结家族引用，去掉 MARKET_FIELDS / FINANCIAL_FIELDS 二分集合。价格仍提供执行必需行情事实，其他家族按请求字段解析；列式合并校验坐标一致。ColumnarResearchData 的附加值改为通用 family_values，所有当前构造器同步。
- 上述修改定向回归 130 passed（74.63s），Ruff 通过。随后自查补齐 DailyTrack 的实际 field_availability 子集检查，避免家族覆盖存在但字段未声明时误执行；对应依赖测试 5 passed。此后源代码修改仍需最终复审和真实链路复验。
- 串行复审快照 `field226-issue01-rereview-uxdunju6`：Standards 关闭手机触控与依赖所有权两项，未新增问题；随后 Spec 关闭原 P1/P2 实现问题，提出 P2 验收缺口：必须验证目录读取后、提交前 Head 变化。已新增 `test_admission_rechecks_head_after_catalog_read`，使用实际 12 字段目录 A → 发布缺财务字段 B → revenue 拒绝且零 Run → close 成功并冻结 B。用例实测正在进行，不能将新增测试代码当作通过。
- 集成 run `20260912t132148z-51049-d38f31ec`：32 passed / 2 failed（73.887s）；两项为被 pytest 预先加载的旧错误消息精确断言，当前文件已改成验证实际家族与日期。此前 overlap 修复用例在该轮通过。
- 复验 run `20260912t132503z-53019-0ee225fb` 已完整结束 exit 0：10 个普通用例、数据库重启与五个依赖重启阶段分别通过，清理成功。session 76653 终态，无需继续轮询。
- `pnpm test`（session 52997）结束 exit 1：工具测试 29 passed，Python 1233 passed / 2 failed；两个失败来自 Fake Agent 轨迹 fixture 缺新的 DataOverview 必需字段。已同步 fixture 的坐标、实际字段和家族覆盖，并修正不一致财务就绪声明。相关轨迹全部 11 passed（4.71s），Ruff 通过；不重复运行未变化的 1233 项。
- 快速检查剩余原始阶段通过 `quickCommands.slice(4)` 继续执行，session `43628` 最近仍在运行：Agent typecheck 与 648 项 unit 已通过，eval-preflight / Auth / 公共 TS / Web 后续结果待收取。不是重新定义快速检查范围。
- 最终目录切换和 DailyTrack 复验使用现有隔离 integration，run `20260912t133228z-64649-53957b36`，session `77553`，最近仍在运行。选择新目录切换用例、财务/行业 track 截止阻塞、直接准入及运行器所有恢复阶段。继续查询同一 handle，勿重复启动。

下一步：收取 session 43628、77553；修复实际失败；对上次复审后新增的字段子集准入、Agent fixture 和目录切换测试做串行复审，逐项核验 01 全部验收后更新 tracker、独立提交。未开始 02，不标 complete。

## Final acceptance — 2026-09-12

- 全部 10 项验收已完成；当前合同、12 字段语义、实际字段/家族准入、冻结 Generation、非目标家族保留与四区块目录均有上述公开接口或浏览器证据。未引入兼容或版本迁移。
- 最终冻结快照 `field226-issue01-final-review-0g_9p03u` 按 Standards → Spec 串行复审，两者均无新增发现，前述 P1/P2 全部关闭。
- 最终隔离 integration `20260912t133228z-64649-53957b36` 已终态 exit 0：普通用例 11 passed；数据库、RustFS factor/strategy/cancellation、Postgres batch/strategy 共六个恢复阶段均通过，清理 status 0。最后 strategy 恢复 1 passed / 67.59s。目录 A→Head B 的拒绝及成功执行均在该轮实测。
- 快速检查首次 Python 两项 fixture 失败已修复，相关 11 项轨迹复验通过；其余 1233 项首次通过。后续 Agent typecheck / 648 unit / 11 eval-preflight、Auth typecheck / 200 unit、公共 TypeScript 均通过。Web fixture 类型缺口修复后官方 typecheck 与 355 项测试通过。原始 pnpm test 进程曾失败；此处记录修复后的受影响阶段和剩余阶段通过，不声称原始命令一次通过。
- Data 真实 Chromium 桌面/手机 2 项通过；定向家族/读取/列式回归 130 项及最终实际字段准入 5 项通过；Ruff 和 diff 格式检查通过。未进行生产部署。
- 本票随独立交付提交完成；提交引用以包含本记录的 Git commit 为准。02 尚未开始，只有该提交成功后才进入下一票。
