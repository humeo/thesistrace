# 07 — Run one Research Workflow through Temporal

**What to build:** Let a User request one idempotent ResearchRun from the Web,
observe its durable asynchronous lifecycle, and receive the complete bounded
Factor and Strategy result through a finite Temporal Workflow.

**Blocked by:** 06 — Isolate private research and share read-only Datasets; `thesistrace-bounded-research-storage/06 — Contract to the one-MiB Result Bundle`.

**Status:** ready-for-agent

- [ ] Requesting Run freezes the current valid Definition, creates one Personal Workspace-owned ResearchRun and execution-outbox row atomically, and returns without holding the HTTP request open.
- [ ] Repeating the same idempotency key returns the same frozen Definition and ResearchRun without consuming duplicate execution capacity.
- [ ] An idempotent relay starts one finite Temporal Workflow from a stable domain identity and leaves PostgreSQL as the authoritative queued, running, and terminal product state.
- [ ] A Compute Worker executes the existing research kernel and atomically publishes one complete Result Bundle no larger than `1,048,576` owned bytes.
- [ ] Web and API views expose bounded Factor summaries, Strategy summaries, retained Strategy Daily Observations, and Terminal Strategy State without exposing transient Alpha, Label, Factor-daily, order, fill, or object-storage data.
- [ ] Collections and retained Strategy time series are bounded and paginated where necessary.
- [ ] Another valid User's Run identifier produces a non-disclosing denial for detail, status, and result views.
