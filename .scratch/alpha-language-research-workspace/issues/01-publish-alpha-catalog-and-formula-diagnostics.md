# 01 — Publish safe Alpha Catalog and Formula Diagnostics

**What to build:** Give researchers and maintainers one safe backend language surface
that lists every authorable field and builtin and returns authoritative, source-ranged
Formula diagnostics without creating durable research state.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] A composed Alpha Authoring Catalog exposes only explicitly capable Data fields and public builtin metadata.
- [ ] Field and builtin Alpha Identifiers are stable lowercase `snake_case`, share one namespace, and collisions fail application readiness.
- [ ] Formula accepts one expression with bare field identifiers, numeric literals, parentheses, supported arithmetic, and positional builtin calls.
- [ ] Statements, assignment, attributes, indexing, collections, comprehensions, control flow, keyword/star arguments, and every other non-allowlisted syntax form are rejected.
- [ ] Static checking distinguishes Numeric Series, Number, and Window, requires a Numeric Series root, and enforces integer Window bounds from 1 through 252.
- [ ] Diagnostics return stable codes, messages, severity, and exact start/end source ranges for syntax, identifier, callability, arity, type, Window, literal, size, node, depth, and lookback failures.
- [ ] Catalog and diagnostics HTTP contracts are non-mutating; a well-shaped invalid Formula returns diagnostics without a database row, receipt, or queue item.
- [ ] Formula handling never calls Python `compile`, `eval`, or `exec`, and Python AST never crosses the Alpha Language interface.
- [ ] No Alpha Release ID, operator release, or multi-version dispatcher appears in the catalog, diagnostics, or compiler result.
- [ ] Focused compiler, catalog, HTTP-contract, and security tests pass with fixed deterministic inputs.

## Comments

- Approved as the first tracer-bullet ticket in the Alpha Formula Language and Research Workspace breakdown.
