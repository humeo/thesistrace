# Local main integration — 2026-09-14

## Scope

User requested local merge to main; no push or deployment.

- Research parent: `0c3681d0ee24c28808d18d85a4694267fcb1ee8c`.
- Main parent: `1abaa965634d83dd66d66b0a277af803fb6804da`.
- Merge base: `2daf193e9bcd00ab18e8d5e1bf5e67dbcf557d8d`.
- Resolve 32 content conflicts in the isolated research worktree. Preserve main's 226-field catalog, per-family admission and TTM window contracts, together with research common inputs, conditional expressions, selection/exposure/weighting and separate evaluation/backtest/tracking.

## Integration corrections

- Pass both common inputs and TTM windows to all expression engines. TTM metadata belongs to numeric flow arithmetic, not comparison/Boolean conditions. Conditional expressions preserve the selected flow branch's window; a selected constant is not an invalid TTM window.
- Keep field-family admission with unioned signal/exposure/weighting lookback; industry common inputs require warm-up coverage.
- Refresh current admission fixtures, shared catalog and MCP contract digest. Empty industry fixture uses its declared schema.
- Clear Copy button feedback timeout on unmount; a regression reproduced the unhandled teardown error before the fix.
- Scope stock-field browser assertions to stock datasets, excluding the newly introduced common-input table.
- Await restored Chat resource metrics before testing transcript scrolling; sample the scroll position after pointer placement.
- The long Folder Draft workflow hit its aggregate 120s deadline about 12s after Track admission (worker entered calculation, no failure event). Budget 240s for the complete multi-Run/data-publication flow while preserving its 90s Track wait and assertions.

## Validation evidence

All paths below are local merge evidence under `/private/tmp/`.

- Initial targeted Core run: 14 failures / 126 passes, exposing obsolete fixture fields and contract digest; corrected targeted suite: 34 passes.
- Quick Python suite: 1730 passes / 2 failures (catalog and TTM fixtures). Corrected related suite: 110 passes with one additional empty-industry fixture failure; corrected TTM fixture: 1 pass.
- Conditional TTM regression: red before correction; all 59 related row/matrix/columnar and data tests pass after correction (`research-merge-conditional-ttm-green.log`).
- Full Ruff passes. Remaining quick stages pass: Agent 651, Auth 200, Web 372; typechecks and Agent preflight pass (`research-merge-quick-rest.log`). The original aggregate quick invocation failed; these are repaired-stage results, not a claim that it exited successfully.
- Browser components: 50 passes / 2 failures caused by broad field selectors; both corrected field tests pass (`research-merge-browser-fields.log`).
- Standards review: two TTM conditional findings fixed and closed on re-review. Spec review: no remaining merge regression.
- Original real integration exposed two TTM batch requests using the removed scheduling field and omitting required initial cash. Update to the current explicit contract; the dedicated TTM HTTP/batch/Track rerun passed 2 cases (56.96s).
- Parallel E2E rerun hit MCP discovery's 5s timeout and a separate 90s Turn timeout. At the time, host load averages were 28.88/30.72/25.71; Docker had 8 CPUs and 8GiB. Preserve these failures, stop two extra runners normally, and complete final gates serially. The interrupted TTM runner completed its 2 ordinary tests but did not complete restart phases; the interrupted research E2E is not a pass.
- Original selected real integration finished with 105 passes / 3 failures in 1762.52s: the 2 fixed TTM request cases and MCP DailyTrack admission hitting an Auth quota HTTP read timeout (`QuotaPolicyUnavailable`). No product-timeout change was made for this resource-contention failure; rerun that case and the dedicated recovery phases serially.
- Serial integration rerun `20260914t104019z-6232-6f5eec74` exited 0: MCP DailyTrack passed, followed by all 6 dedicated database/RustFS restart and recovery cases; cleanup and canary scan passed (`research-merge-integration-serial.log`). This closes the selected integration failures; it is not the entire integration suite.
- Final serial E2E ordinary group `20260914t104529z-7885-2094cda7`: both Chat Batch modes passed (1.1m), including restored metrics, real wheel scrolling, menu visibility and deletion preserving child Results.
- Serial Folder Draft/Research/Track/deletion/diagnostic-retention flow passed (1.5m), run `20260914t105032z-10617-3461cbfc`.
- Complete-field E2E exposed the same broad table selector (1 expected stock row plus 4 common-input rows). All remaining matching selectors were scoped to stock datasets. Final targeted rerun `20260914t105400z-12422-de2a0993` passed (1.1m), completing the 4 selected E2E flows across repaired-stage reruns (`research-merge-e2e-fields-final.log`).

## Original main work

Before any main mutation, 1881 dirty/untracked files were copied and SHA-256 recorded under `/private/tmp/research-main-preserve-20260914`. Preserve unrelated untracked files and local CONTEXT/ADR index additions. Draft tracker files superseded by completed incoming tracker files remain in that backup. No development stack reset.
