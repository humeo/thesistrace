# 21 — Show the bounded ResearchRun Result

**What to build:** Present Factor and Strategy/Benchmark conclusions inside the
succeeded ResearchRun detail without creating a fifth product resource.

**Blocked by:** 20.

**Status:** complete

**Implementation:** complete

- [x] ResearchRun detail includes the required 1-, 5-, and 20-session Factor
  summaries and coverage counts.
- [x] It includes Strategy summary, retained Strategy observations, the
  selected-Universe Benchmark, and provenance for that Run.
- [x] The complete Result Bundle remains within 1,048,576 exact owned bytes.
- [x] Alpha Values, stock-level Labels, daily Factor observations, raw orders,
  fills, and excluded Top-Bottom or quantile series are not retained.
- [x] No object key, manifest, continuation state, raw execution data, Attempt,
  Result URL, download, or cross-Run comparison is exposed.
- [x] The page has observable loading, refresh, success, and sanitized error
  states and survives process restart.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written:

```sh
set -eu
./scripts/core-test-runtime reset
./scripts/core-test-runtime run uv run pytest -q \
  tests/kernel \
  tests/integration \
  tests/acceptance/test_core_research_run_result.py
./scripts/core-test-runtime reset
./scripts/core-test-runtime run bun run --cwd web test:core
./scripts/core-test-runtime down
```

The backend test must execute a real Run, inspect its exact owned Result bytes,
and verify that the succeeded ResearchRun detail returns only the bounded
product projection: 1-, 5-, and 20-session Factor summaries with coverage,
Strategy summary, 504 retained Strategy/Benchmark observations, and provenance.
It must also prove that private or excluded evidence is absent and that loading
survives a runtime restart with sanitized errors. The browser must open the same
succeeded ResearchRun, observe loading and refresh, render only its Factor plus
Strategy/Benchmark conclusions and provenance, and expose no Result resource,
URL, download, cross-Run comparison, manifest, object, continuation, Attempt,
or raw execution details.

## Comments

- Succeeded `GET /api/research-runs/{id}` now reads the committed, verified
  Publication through the ResearchRun module and embeds one strict Result value
  in the detail. Queued, running, failed, and cancelled detail omit that value;
  no `/result` route, fifth resource, URL, or download was added.
- The public Factor projection includes only the required 1-, 5-, and
  20-session summaries and coverage counts. Daily IC/Rank IC, Five-Quantile,
  and Top-Bottom series remain transient; the bounded summary scalars remain as
  required Factor conclusions, including legal nulls for insufficient or
  constant samples.
- The public Strategy projection contains its summary, exactly 504 canonical
  Daily Observations, and the selected-Universe equal-weight Benchmark. It
  excludes Terminal Strategy State, positions, raw orders/fills, publication
  mechanics, Attempts, and continuation state. Provenance retains the Run,
  pinned Release, immutable-input digest, calculation contracts, and semantic
  versions without exposing a manifest or physical object identity.
- The Web uses the same ResearchRun detail request and existing queued/running
  polling, then renders Factor conclusions, Strategy metrics, a memoized 504
  session Strategy/Benchmark NAV chart, and provenance. Reload loading, manual
  refresh, success, and generic error states are observable; no comparison or
  download surface exists.
- The final ticket backend command passed `83 passed, 1 warning` in `177.82s`
  against real PostgreSQL and RustFS. It verifies restart reopening, exact
  Result ownership at or below `1,048,576` bytes, absence of excluded/private
  evidence, no independent Result route, sanitized read failure, and complete
  nullable Factor summaries from a constant Alpha.
- The final Core browser command passed `7 passed` in `32.4s`, including the
  complete Run-to-Result flow plus reload loading, refresh, sanitized error,
  Factor summaries, and the Strategy/Benchmark view.
- Independent review initially found that FastAPI's recursive
  `response_model_exclude_none` removed legal nullable Factor fields and could
  make the React formatter receive `undefined`. Commit `5e4196b` replaced it
  with field-level exclusion of only a top-level absent `result` and added a
  constant-Alpha acceptance. Final review passed `Standards: PASS` and
  `Spec: PASS` with no findings.
- The final repository `make check` invocation exited `0`: Ruff passed, Python
  passed `521 passed, 63 skipped, 2 warnings` in `622.15s`, Web typecheck and
  production build passed, and narrow/desktop Playwright passed in `36.0s` and
  `34.9s`.
