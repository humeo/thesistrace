# 01 — compression

Status: ready-for-agent

Implement item 01 of ../spec.md and its relevant acceptance requirements.

## Acceptance

- [ ] Implement current contracts without compatibility or migration.
- [ ] Run relevant behavior and real-dependency verification.
- [ ] Resolve Standards and Spec review findings.
- [ ] Commit this issue independently.

## Evidence

Pending.

- Codec red: missing public encoding functions (ImportError), then 16 passing codec
  tests, including descriptor rejection. Ruff passed for the issue's changed files.
- Standards review: no findings. Spec review: no implementation defect; requested
  descriptor tests added, real lifecycle verification in progress.
- Isolated RustFS physical probe (50 synthetic positions): JSON 5355 content bytes /
  12288 allocated bytes; gzip 265 content bytes / 8192 allocated bytes. Probe used
  a separate bucket on this task's test stack and deleted it afterwards. This is
  fixture evidence, not the original account or production capacity.
- Full isolated integration command: ./scripts/test-runtime integration,
  output /tmp/daily-track-integration-01.log (running).
- The initial integration sweep has passed all 217 integration cases (including
  the new compressed publication persistence/release case) and reached acceptance
  execution. Full acceptance and restart gates continue separately below.
