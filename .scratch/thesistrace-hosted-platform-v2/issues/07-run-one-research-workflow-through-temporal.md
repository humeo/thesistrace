# 07 — Run one Research Workflow through Temporal

**What to build:** Let a User request one idempotent ResearchRun from the Web,
observe its durable asynchronous lifecycle, and receive the complete bounded
Factor and Strategy result through a finite Temporal Workflow.

**Blocked by:** 06 — Isolate private research and share read-only Datasets; `thesistrace-bounded-research-storage/06 — Contract to the one-MiB Result Bundle`.

**Status:** complete

- [x] Requesting Run freezes the current valid Definition, creates one Personal Workspace-owned ResearchRun and execution-outbox row atomically, and returns without holding the HTTP request open.
- [x] Repeating the same idempotency key returns the same frozen Definition and ResearchRun without consuming duplicate execution capacity.
- [x] An idempotent relay starts one finite Temporal Workflow from a stable domain identity and leaves PostgreSQL as the authoritative queued, running, and terminal product state.
- [x] A Compute Worker executes the existing research kernel and atomically publishes one complete Result Bundle no larger than `1,048,576` owned bytes.
- [x] Web and API views expose bounded Factor summaries, Strategy summaries, retained Strategy Daily Observations, and Terminal Strategy State without exposing transient Alpha, Label, Factor-daily, order, fill, or object-storage data.
- [x] Collections and retained Strategy time series are bounded and paginated where necessary.
- [x] Another valid User's Run identifier produces a non-disclosing denial for detail, status, and result views.

**Acceptance evidence:** The production PostgreSQL migration creates a
Personal Workspace-owned, RLS-protected execution Outbox and exposes only two
least-privilege relay functions. A real PostgreSQL contract run passed both
two-User isolation scenarios and covered all thirteen private tables. Through
the public HTTPS Origin, a Run request returned in `0.515` seconds, an
idempotent replay returned the same frozen Definition and Run, and the visible
state advanced `queued -> running -> succeeded`. The Outbox contained exactly
one dispatched row and Temporal contained exactly one completed
`ResearchWorkflow` at `research-run/{run_id}` with an eleven-event history.
The Compute Activity published a `49,177`-byte Result Bundle against the
`1,048,576`-byte limit. A second authenticated User received 404 for both Run
detail and result, while the owning User received paginated Daily Observations
and terminal positions with no manifest object index, object digest, order,
fill, Alpha, Label, or Factor-daily payload. The complete Python suite passed
`99` tests with `6` environment-gated skips; both narrow and desktop
Playwright chains passed.
