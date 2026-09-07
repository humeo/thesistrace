# 01 — compression

Status: complete

Implement item 01 of ../spec.md and its relevant acceptance requirements.

## Acceptance

- [x] Implement current contracts without compatibility or migration.
- [x] Run relevant behavior and real-dependency verification.
- [x] Resolve Standards and Spec review findings.
- [x] Commit this issue independently.

## Evidence

Committed as `dd62055`.

- Codec red: missing public encoding functions (ImportError), then 16 passing codec
  tests, including descriptor rejection. Ruff passed for the issue's changed files.
- Standards review: no findings. Spec review: no implementation defect; requested
  descriptor tests added, real lifecycle verification in progress.
- Isolated RustFS physical probe (50 synthetic positions): JSON 5355 content bytes /
  12288 allocated bytes; gzip 265 content bytes / 8192 allocated bytes. Probe used
  a separate bucket on this task's test stack and deleted it afterwards. This is
  fixture evidence, not the original account or production capacity.
- Full isolated integration command: ./scripts/test-runtime integration,
  output /tmp/daily-track-integration-01.log.
- The initial integration sweep has passed all 217 integration cases (including
  the new compressed publication persistence/release case) and reached acceptance
  execution. Stopped this initial suite intentionally before switching the in-flight
  source contract to v3 (exit 143); its test resources were cleaned. This was not
  a complete suite pass. Later focused publication/recovery/overlap/window checks
  passed; final full-suite evidence is recorded in issue03.
