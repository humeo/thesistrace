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

- Run `uv run pytest -q tests/integration tests/acceptance` and inspect the
  exact Result Bundle size and product projection.
- Run `bun run --cwd web typecheck` and `bun run --cwd web test:e2e`; open the
  succeeded Run and confirm only Factor plus its own Strategy/Benchmark result
  is shown.

## Comments
