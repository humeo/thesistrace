# 16 — Run research and publish the Result Bundle

**What to build:** Execute a frozen Research Definition over exactly 756
Research Sessions and atomically expose one complete Factor Evaluation,
Strategy Backtest, and authoritative immutable Result Bundle.

**Blocked by:** 06 — Publish incremental, catch-up, and correction Releases; 07 — Edit, validate, and freeze Research Definitions; 11 — Calculate complete Factor Evaluation; 15 — Calculate complete Strategy metrics.

**Status:** ready-for-agent

- [ ] A valid Run request atomically creates a frozen Definition and one queued ResearchRun pinned to one concrete Release.
- [ ] The calculation consumes exactly 252 warm-up and 504 reported Research Sessions.
- [ ] One Alpha Matrix feeds both complete Factor and Strategy outputs without duplicate transformation.
- [ ] The Result Manifest binds Definition and content hash, Release, research semantics, Numeric Execution Contract, calculation kernel, runtime build, objects, and checksums.
- [ ] ResearchRun becomes succeeded only after every required immutable object and the final manifest are committed.
- [ ] Failure exposes no successful partial Result Bundle.
- [ ] API and UI result views separate Factor and Strategy conclusions while showing shared provenance.
- [ ] Reopening or rerunning never mutates an existing Run, frozen Definition, Bundle, or report.
