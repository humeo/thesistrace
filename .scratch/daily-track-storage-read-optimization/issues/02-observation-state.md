# 02 — observation-state

Status: done

Implement item 02 of ../spec.md and its relevant acceptance requirements.

## Acceptance

- [x] Implement current contracts without compatibility or migration.
- [x] Run relevant behavior and real-dependency verification.
- [x] Resolve Standards and Spec review findings.
- [x] Commit this issue independently.

## Evidence

- 25 kernel tests passed, including independent full-history drawdown recomputation over 1001 sessions and corrected boundary peaks/losses.
- Isolated PG/RustFS focused run: 55 passed; two test helpers still decoded gzip as plain JSON. Updated the helpers to Publication decoding. Follow-up selected recovery, overlap correction, 504-session detail, and compressed persistence: 4 passed (93.54s). The runner's subsequent unrelated restart phase selected no cases; full unfiltered verification follows issue03.
- Standards and Spec reviewers both confirmed the publication-boundary invariant fix; no remaining findings. KernelStateCheckpoint rejects mismatch before preparing publication; activation checks Origin NAV and zero drawdown.
- Schema hard cut to v3; no dev data changed. Final complete suite evidence will be recorded with issue03.
