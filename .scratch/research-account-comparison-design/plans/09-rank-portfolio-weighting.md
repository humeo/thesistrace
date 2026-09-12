# 09 — 入选集合内排名配权执行计划

基准：`d7da500`，隔离 worktree `research-capabilities`。08 已提交且工作区干净后开始。仅交付09，不提前实现10逆波动、11查询或12保留期。保持单一当前合同，不做迁移、别名或旧版本读取。

## 当前边界

- `research_kernel/strategy.py` 在 Selection Close 已集中选择候选并保存 `relative_weights`，后续交易和 Exposure 恢复使用冻结权重；当前这里只生成等权。
- `StrategyBacktestSpec`、不可变 Strategy、Kernel RunInput、Track Origin 和 Batch 子配置必须贯通同一 weighting 选择。当前固定 kind 名含 equal_weight，修改为如实描述当前多头 Top-N 的身份，不保留旧别名。
- Authoring 目录当前仅声明 equal_weight。网页/MCP 必须随行为发布 rank_weight，Factor 分支不能接受 Strategy 专属字段。

## 实现顺序

1. 明确当前公共 `weighting` 枚举：equal_weight 默认、rank_weight 新选项。规范化后显式冻结，更新普通 Run、Batch 子账户、读取来源/复用草稿、诊断、Kernel/Track 当前调用者和所需快照。
2. 在选股边界提取小型纯配权计算，沿用现有 Final Alpha/Instrument 排序与 Top-N。排名仅在最终 K 个入选者中计算；同分按占据名次的平均原始权重归一化。空名单无权重、单候选权重1。复用08交易循环和保留目标。
3. 目录和网页增加真正可执行的配权选择，默认等权，持久化/读取/提交同源；MCP Schema、诊断与返回来源保持一致。遵循 DESIGN.md。
4. 验证后依次 Standards → Spec → 修复/复审 → tracker → 独立提交。

## 验证

- 独立期望：K3分数不同1/2、1/3、1/6；前二同分5/12、5/12、1/6；Top-N边界并列身份决胜、候选不足、单候选和空集合。
- 账户验证权重×Exposure，零仓位保留权重/下一恢复，费用及取整后实际账户；新的加权不改变比例减仓语义。
- 普通/分段/Batch/Track共享配权，缓存缺失和历史修订不重算已决定权重。真实发布、来源和Track继承接受配置。
- 针对新增行为先失败回归后实现；复用当前隔离验收入口。网页组件/真实浏览器证明选择、草稿、诊断与提交。必要当前公共库存、快速检查通过后不无故重跑。

## 执行记录

- 2026-09-13：计划建立，09 尚未修改产品代码或测试。08 提交 `d7da500`；原工作区/dev/线上均未修改。

### 2026-09-13 — Selection weights and first current-contract slice

- Confirmed baseline `d7da500e`; only09 plan untracked before implementation. New pure `portfolio_weighting.select_portfolio` owns existing Final Alpha/identity Top-N ordering plus equal/rank weighting. Red import failure recorded;9 independent formula cases passed, including ties within selected boundary, insufficient/one/empty candidates.
- Added public default `weighting=equal_weight`, rank_weight enum and explicit immutable value through Run/Batch/Kernel/Track current contracts; current strategy kind is `long_only_top_n`. No old-name reader or adapter. Updated47 current test Strategy dictionaries explicitly. Catalog lists both implemented models.
- Integrated Selection with the existing08 execution loop. First manual rank restore case exposed float2/3 causing39999.999… targets and one-lot underbuy. **Current frozen relative_weights now uses canonical exact rational strings** (`2/3`, `1/3`, `1`), validated positive and exactly summing to1; no float fallback or approximate epsilon. Open computes capital×numerator÷denominator, preserving money precision and lot rules. This is the single representation; no duplicate approximate weight state. Terminal validator no longer assumes equal weighting for every model; pending/retained contract equality still enforced.
- Independent account expects rank2/3:1/3 restored at60% of100k ->4000/2000 shares at10,40000cash. Pure weighting plus manual33passed0.29s (`rank-account-exact.log`). Initial common regression16failed/36passed because raw test definitions lacked explicit current weighting; after fixture update52passed.
- Full Kernel525passed/1checksum snapshot failure54.49s (`kernel-all-first.log`); Alpha/labels/Factor checksums unchanged. Current Strategy snapshot updated to2fdbe31bc2bf68526fbe590836822da76dbdf9acf0fe6ebf34af1c818d41ce68; remaining characterization expectations2passed (`characterization-repair.log`). Source/tests Ruff and diff whitespace passed.
- Frontend draft/spec/frozen source now carries weighting, validates current values, defaults new drafts to equal_weight and resets Factor controls. Form adds equal/rank selection and Run source display. Updated current TS fixtures; final typecheck passed (`web-typecheck-second-repair.log`). Browser flow extended to select rank, reload, diagnose and submit same rule. Component and browser checks running.
- **09 incomplete/uncommitted:** check those results; update Track presentation/TS provenance if needed; current HTTP/MCP inventory and actual ranked Run/Batch/Track/cache tests still required, plus final checks and serial Standards/Spec reviews. No10 implementation.

### 2026-09-13 — Published contracts and actual acceptance

- Updated current MCP inventory metadata to173032bytes/SHA25652860b7ef786c56096197ed5842a9affde29c537db1414cc542908fa145f9eb9 after the expected two old-snapshot failures. Public default/Factor rejection plus MCP59passed3.42s (`public-weighting-contract.log`); existing current benchmark metadata updated, not a new benchmark or version.
- Web component54passed (`web-components-first.log`). First browser2passed/1failed because old global option selector also matched the new Rank weight select item; scoped autocomplete assertions to observed Completions listbox. Browser3passed6.7s. Screenshot inspection found stale equal-weight wording in Exposure help; corrected it to selected weighting and placed weighting across the full configuration row. Final browser3passed12.2s (`browser-final-layout.log`), screenshot inspected.
- Actual isolated ordinary Run/Batch/Track11passed67.36s, runner exit0 and cleanup complete (`rank-integration-first.log`). Common/dynamic Run cases submit rank_weight; Track provenance confirms inheritance; Strategy Sweep combines rank/equal items and matches each ordinary result byte-for-byte, including fixed accepted weighting.
- Rank-only row/columnar Track tests10passed12.53s (`rank-tracking-first.log`), covering multiple formula/neutralization/Exposure combinations, retained checkpoint and cache continuation, append windows and corrected historical data. The stored run-input weighting is explicitly checked.
- Full quick currently running; no09review/commit yet. No10work.

- First full quick1454passed/1failed127.97s: maximum-text provenance test built current authorable input via dict() without weighting. Added the explicit default to that fixture; no product fallback. Repaired full quick running (`quick-repair.log`). Other recorded accepted real/browser tests unchanged.

- Repaired full quick exit0: Core1455passed124.74s, Agent648/Auth200/Web363 passed with lint/typecheck (`quick-repair.log`). All verification complete; freezing09 for serial Standards then Spec.

- Standards review found one P2: Run provenance showed dynamic Rank weight alongside obsolete fixed Equal weight. Removed the obsolete row and added equal/rank source-render regressions. Red2failed24passed; repaired26passed1.70s and Web typecheck passed (`source-weighting-red.log`, `source-weighting-green.log`, `source-weighting-types.log`). Capturing repaired snapshot for focused Standards re-review before Spec.

- Final frozen snapshot `/private/tmp/thesistrace-issue09-review-fixed`: Standards focused re-review closed sole P2 with no new findings; Spec review no findings. Reports `standards-report.md` and `spec-report.md` in that snapshot. SHA256 verification confirmed all reviewed inputs unchanged before tracker update. All09 acceptance boxes complete; independent commit follows. No10 implementation started before this closure.
