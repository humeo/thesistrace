# 28 — Prove the revised V1 product chain

**What to build:** Give the operator one verified public-API and real-browser
workflow from Dataset Bootstrap through research, bounded results, incremental
Daily Tracking, correction-aware verification, and terminal stop, with the
operator runbook describing the same revised product and storage boundaries.

**Blocked by:** Bounded Research Storage 02 — Publish Canonical Dataset
Releases as partitioned Parquet; Bounded Research Storage 06 — Contract to the
one-MiB Result Bundle; Bounded Research Storage 09 — Reconcile Working Cache
deletion after DailyTrack stop; 27 — Verify Batch-Incremental Equivalence over
ordered Dataset Releases.

**Status:** ready-for-agent

- [ ] One public-API acceptance flow completes Fixture Bootstrap, Draft freeze and Run, bounded Result inspection, DailyTrack activation, incremental Advance, cache loss and bounded rebuild, historical Correction Boundary, equivalence verification, and stop with final cache absence.
- [ ] The flow proves that every successful Result Bundle is at most 1,048,576 exact bytes, retains Strategy Daily Observations, and references none of the forbidden transient object kinds.
- [ ] Desktop and narrow-screen browser flows show Factor summaries, retained Strategy charts and tables, provenance, Head, Generation, lag, blocked frontier, Correction Boundaries, latest Factor summary, and account state.
- [ ] Browser and API acceptance prove that daily Factor curves, raw order and rejection details, and raw artifact downloads are absent from the product surface.
- [ ] The V1 runbook documents Parquet Dataset Releases, the bounded Result Bundle, Working Cache recovery and backup boundaries, same-Generation historical corrections, explicit verification, and stopped-Track cleanup.
- [ ] Backend, frontend, public-API acceptance, production build, and real-browser suites pass together through the repository's complete verification command.
