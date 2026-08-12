# 01 — Publish safe Alpha Catalog and Formula Diagnostics

**What to build:** Give researchers and maintainers one safe backend language surface
that lists every authorable field and builtin and returns authoritative, source-ranged
Formula diagnostics without creating durable research state.

**Blocked by:** None — can start immediately

**Status:** complete

- [x] A composed Alpha Authoring Catalog exposes only explicitly capable Data fields and public builtin metadata.
- [x] Field and builtin Alpha Identifiers are stable lowercase `snake_case`, share one namespace, and collisions fail application readiness.
- [x] Formula accepts one expression with bare field identifiers, numeric literals, parentheses, supported arithmetic, and positional builtin calls.
- [x] Statements, assignment, attributes, indexing, collections, comprehensions, control flow, keyword/star arguments, and every other non-allowlisted syntax form are rejected.
- [x] Static checking distinguishes Numeric Series, Number, and Window, requires a Numeric Series root, and enforces integer Window bounds from 1 through 252.
- [x] Diagnostics return stable codes, messages, severity, and exact start/end source ranges for syntax, identifier, callability, arity, type, Window, literal, size, node, depth, and lookback failures.
- [x] Catalog and diagnostics HTTP contracts are non-mutating; a well-shaped invalid Formula returns diagnostics without a database row, receipt, or queue item.
- [x] Formula handling never calls Python `compile`, `eval`, or `exec`, and Python AST never crosses the Alpha Language interface.
- [x] No Alpha Release ID, operator release, or multi-version dispatcher appears in the catalog, diagnostics, or compiler result.
- [x] Focused compiler, catalog, HTTP-contract, and security tests pass with fixed deterministic inputs.

## Comments

- Approved as the first tracer-bullet ticket in the Alpha Formula Language and Research Workspace breakdown.
- Implemented the Data-owned Alpha Field Capability and Series reader, the Research Kernel-owned self-contained Builtin Catalog, the strict backend Formula compiler, typed source-ranged diagnostics, and non-mutating Catalog/Diagnostics HTTP contracts.
- Verification: `uv run ruff check .`; focused compiler/catalog/HTTP/security/module tests; full Python suite `370 passed, 109 skipped`; `bun run typecheck`; Web shell suite `9 passed`.
- Review: final frozen staged SHA-256 `4ff369737a29b0a00079e2943e4a93fb060bdf4c186789e53b44a887aff56339` received both Spec pass and Standards pass after all findings were repaired and re-reviewed.
- Delivery: this tracker transition and implementation are finalized together in the Ticket 01 commit.
