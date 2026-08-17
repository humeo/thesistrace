# 04 — Confirm Research cancellation after child exit

**What to build:** Make Research cancellation truthful and safe. Queued work cancels
immediately, while running work remains visibly `cancelling` until its supervised
execution child has stopped, late publication is fenced, and the frozen Data
Generation Pin can be released.

**Blocked by:** 03 — Execute one Research Chunk in a supervised child

**Status:** ready-for-agent

- [ ] Cancelling a queued ResearchRun atomically reaches terminal `cancelled` without creating an Attempt or execution child.
- [ ] Cancelling a running ResearchRun atomically moves the Run and active Attempt to non-terminal `cancelling`, advances the execution fence, and signals the owning supervisor.
- [ ] The child checks cancellation before and after each Research Session and between bounded expensive operator stages.
- [ ] Cancellation abandons the current uncommitted Chunk and prevents every later Checkpoint, staged payload, or Result commit from the fenced Attempt.
- [ ] The supervisor first requests cooperative shutdown and escalates to terminating the child when the grace interval expires.
- [ ] While the owning supervisor remains healthy, child shutdown, exit confirmation, Pin release, and terminal persistence complete within one five-second total budget.
- [ ] The Run and Attempt become terminal `cancelled` only after the child is confirmed exited.
- [ ] If the supervisor, container, or host is lost, durable cancellation intent and fencing survive and replacement recovery waits until the old lease and ownership cannot remain live.
- [ ] Lost-supervisor recovery may exceed five seconds and never reports terminal cancellation or releases the Pin early.
- [ ] User cancellation never creates an infrastructure retry Attempt.
- [ ] Repeating an idempotent Cancel request replays the same outcome, conflicting request reuse is rejected, and late Cancel cannot replace an already terminal success or failure.
- [ ] Research list and detail views expose `cancelling` distinctly from `cancelled` and do not display optimistic terminal state.
- [ ] Process, API, and browser tests cover queued Cancel, cooperative running Cancel, forced termination, stale-child publication fencing, supervisor loss, restart recovery, and late terminal races.
- [ ] Tests use explicit barriers, process signals, leases, and bounded polling rather than arbitrary sleep.

## Comments

- Parent: Scalable Long Research and Daily Tracking Execution.
- Serial predecessor: Ticket 03.
