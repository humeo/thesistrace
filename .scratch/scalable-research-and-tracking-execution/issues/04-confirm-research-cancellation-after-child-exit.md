# 04 — Confirm Research cancellation after child exit

**What to build:** Make Research cancellation truthful and safe. Queued work cancels
immediately, while running work remains visibly `cancelling` until its supervised
execution child has stopped, late publication is fenced, and the frozen Data
Generation Pin can be released.

**Blocked by:** 03 — Execute one Research Chunk in a supervised child

**Status:** complete

- [x] Cancelling a queued ResearchRun atomically reaches terminal `cancelled` without creating an Attempt or execution child.
- [x] Cancelling a running ResearchRun atomically moves the Run and active Attempt to non-terminal `cancelling`, advances the execution fence, and signals the owning supervisor.
- [x] The child checks cancellation before and after each Research Session and between bounded expensive operator stages.
- [x] Cancellation abandons the current uncommitted Chunk and prevents every later Checkpoint, staged payload, or Result commit from the fenced Attempt.
- [x] The supervisor first requests cooperative shutdown and escalates to terminating the child when the grace interval expires.
- [x] While the owning supervisor remains healthy, child shutdown, exit confirmation, Pin release, and terminal persistence complete within one five-second total budget.
- [x] The Run and Attempt become terminal `cancelled` only after the child is confirmed exited.
- [x] If the supervisor, container, or host is lost, durable cancellation intent and fencing survive and replacement recovery waits until the old lease and ownership cannot remain live.
- [x] Lost-supervisor recovery may exceed five seconds and never reports terminal cancellation or releases the Pin early.
- [x] User cancellation never creates an infrastructure retry Attempt.
- [x] Repeating an idempotent Cancel request replays the same outcome, conflicting request reuse is rejected, and late Cancel cannot replace an already terminal success or failure.
- [x] Research list and detail views expose `cancelling` distinctly from `cancelled` and do not display optimistic terminal state.
- [x] Process, API, and browser tests cover queued Cancel, cooperative running Cancel, forced termination, stale-child publication fencing, supervisor loss, restart recovery, and late terminal races.
- [x] Tests use explicit barriers, process signals, leases, and bounded polling rather than arbitrary sleep.

## Comments

- Parent: Scalable Long Research and Daily Tracking Execution.
- Serial predecessor: Ticket 03.
- Verification: `pnpm test` (488 Python + 25 Web), isolated PostgreSQL/RustFS
  integration run `20260817t194848z-1005-3aa47a88` (165 + restart), final-image
  browser run `20260817t195039z-1752-7ff203da` (4/4), and Production Image Smoke
  run `20260817t195147z-2338-ebff26d1`.
- Final Spec and Standards reviews passed after closing staging authority,
  five-second cancellation, retry-wait, restart recovery, and terminal child-exit races.
