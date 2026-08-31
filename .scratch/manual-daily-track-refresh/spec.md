# Explicit DailyTrack Refresh

**Status:** ready-for-agent

## Objective

Make every Tracking Advance an explicit Researcher action. A Dataset Head move
must never queue or execute Daily Tracking by itself.

## Contract

- Starting a DailyTrack publishes its Activation Checkpoint and leaves the
  active Track idle.
- `Refresh DailyTrack` is the only ordinary command that queues a new Tracking
  Advance. It is non-destructive and idempotent by `request_id`.
- Refresh is accepted only for an active, lagging, idle DailyTrack. An
  up-to-date, already queued/running, blocked, stopping, or stopped Track returns
  a state conflict. A blocked Track continues to use its explicit Retry command.
- The Tracking Worker keeps the existing durable execution, fixed target,
  Generation pinning, bounded infrastructure retry, Checkpoint publication,
  fencing, Stop, and recovery behavior after a Refresh has queued work.
- Head movement during or after one accepted Refresh does not queue another
  Advance. Each later Advance requires another explicit Refresh.
- HTTP and MCP expose the same Refresh command. MCP uses `tracking:execute`.
- The DailyTrack page distinguishes `Refresh to latest data` from `Reload
  status`. It polls only while an explicitly requested operation is active or a
  Stop is being confirmed.
- There is no automatic-advance compatibility path, migration, fallback, or
  alternate scheduler contract.

## Acceptance

- Moving Dataset Head while a Track is active does not make
  `DailyTrackService.process_next()` claim work.
- One accepted Refresh produces exactly one bounded Tracking Advance and one
  immutable Tracking Checkpoint.
- Replaying the same request returns the stored outcome; conflicting reuse is
  rejected.
- Concurrent Refresh requests cannot create duplicate Advances.
- A successful Advance leaves the Track idle even if Dataset Head moves again.
- HTTP, MCP, authorization, error mapping, UI, keyboard behavior, and focused
  Production Image behavior are covered at their lowest sufficient layers.

## Comments

- The Researcher decision is to trade continuous automatic tracking for a
  simpler, explicit update action. Worker polling remains an implementation of
  accepted durable work, not a trigger for new work.
