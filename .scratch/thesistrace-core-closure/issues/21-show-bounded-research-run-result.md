# 21 — Show the bounded ResearchRun Result

**What to build:** Present Factor and Strategy/Benchmark conclusions inside the
succeeded ResearchRun detail without creating a fifth product resource.

**Blocked by:** 20.

**Status:** ready-for-agent

- [ ] ResearchRun detail includes the required 1-, 5-, and 20-session Factor
  summaries and coverage counts.
- [ ] It includes Strategy summary, retained Strategy observations, the
  selected-Universe Benchmark, and provenance for that Run.
- [ ] The complete Result Bundle remains within 1,048,576 exact owned bytes.
- [ ] Alpha Values, stock-level Labels, daily Factor observations, raw orders,
  fills, and excluded Top-Bottom or quantile series are not retained.
- [ ] No object key, manifest, continuation state, raw execution data, Attempt,
  Result URL, download, or cross-Run comparison is exposed.
- [ ] The page has observable loading, refresh, success, and sanitized error
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
