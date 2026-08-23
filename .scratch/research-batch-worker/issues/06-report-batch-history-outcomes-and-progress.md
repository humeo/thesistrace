# 06 — Report truthful Batch history, outcomes, and progress

**What to build:** Give API clients durable, cursor-paginated Research Batch
history and ordered detail with unambiguous aggregate outcomes, monotonic
whole-task progress, and clearly estimated live progress for the current task.

**Blocked by:** 05 — Execute Strategy Sweeps from one shared Alpha and Factor

**Status:** ready-for-agent

- [ ] Batch lifecycle exposes queued and running plus terminal succeeded, completed_with_failures, failed, and cancelled outcomes under one current contract.
- [ ] Natural completion is succeeded only when every child succeeds, completed_with_failures when successes and failures coexist, and failed when no child succeeds.
- [ ] Factor Batch durable progress reports completed and total complete Factor tasks.
- [ ] Strategy Sweep durable progress reports the shared Alpha-and-Factor prerequisite status plus completed and total complete Strategy tasks.
- [ ] Durable completed-task progress is monotonic and remains authoritative across Worker loss, retry, API restart, and storage reconnection.
- [ ] While work is active, detail identifies the current item_key, phase, completed and total Research Sessions when applicable, estimated percentage, elapsed time, remaining-duration estimate when evidence is sufficient, and Attempt number.
- [ ] Live percentage and remaining time are explicitly labelled as estimates rather than Results, checkpoints, or completion guarantees.
- [ ] Live progress for an incomplete task may reset after a retry, while acknowledged task counts and published outcomes never regress.
- [ ] Terminal detail records stable execution timing and the latest Attempt information without retaining a misleading active heartbeat.
- [ ] Cursor-paginated listing has deterministic ordering and returns frozen scope, Generation identity, aggregate state, timing, and compact durable progress.
- [ ] Detail returns ordered item_key-to-ResearchRun mappings, Run availability, final outcomes, Attempt information, sanitized diagnostics, and any child deletion timestamp.
- [ ] Formula and execution failures expose actionable item-aware diagnostics without secrets, credentials, internal object keys, or unsafe traceback details.
- [ ] Child Result Bundles remain available only through ordinary ResearchRun detail and are never embedded or duplicated in Batch representations.
- [ ] Missing Batch and invalid cursor behavior follow the current public API conventions, and restart preserves all durable history.
- [ ] V1 adds no Batch authoring, list, detail, progress, or control UI; the accepted backend HTTP representation is the product boundary.

## Comments

- Parent: Research Batch Worker.
- This ticket makes progress displayable without pretending incomplete work is durably complete.
