# 16 — Run research and publish the Result Bundle

**What to build:** Execute a frozen Research Definition over exactly 756
Research Sessions and atomically expose one complete Factor Evaluation,
Strategy Backtest, and authoritative immutable Result Bundle.

**Blocked by:** 06 — Publish incremental, catch-up, and correction Releases; 07 — Edit, validate, and freeze Research Definitions; 11 — Calculate complete Factor Evaluation; 15 — Calculate complete Strategy metrics.

**Status:** resolved

- [x] A valid Run request atomically creates a frozen Definition and one queued ResearchRun pinned to one concrete Release.
- [x] The calculation consumes exactly 252 warm-up and 504 reported Research Sessions.
- [x] One Alpha Matrix feeds both complete Factor and Strategy outputs without duplicate transformation.
- [x] The Result Manifest binds Definition and content hash, Release, research semantics, Numeric Execution Contract, calculation kernel, runtime build, objects, and checksums.
- [x] ResearchRun becomes succeeded only after every required immutable object and the final manifest are committed.
- [x] Failure exposes no successful partial Result Bundle.
- [x] API and UI result views separate Factor and Strategy conclusions while showing shared provenance.
- [x] Reopening or rerunning never mutates an existing Run, frozen Definition, Bundle, or report.

## Comments

- Added the batch calculation seam, exact 756-session input slice, shared Alpha
  Matrix, complete immutable object index, Result Manifest, and fenced success
  publication.
- API and Web result views derive separate Factor and Strategy conclusions from
  the same immutable Result Bundle and display shared provenance.
- Historical note: ADR-0147 and the Bounded Research Storage Spec supersede the
  original complete-object boundary. The Alpha Matrix and stock-level Labels
  remain shared runtime inputs but are not Result Bundle objects; the minimal
  successful bundle has a hard one-MiB total-byte budget.
