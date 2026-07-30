# 10 — Publish Datasets on the independent Data Worker

**What to build:** Execute each scheduled or Operator-requested Dataset
Publication as one durable finite Workflow on the dedicated Data Worker, then
make its immutable result available read-only without competing for User
Compute capacity.

**Blocked by:** 03 — Enforce the Hosted Tushare authorization gate; 06 — Isolate private research and share read-only Datasets; `thesistrace-bounded-research-storage/02 — Publish Canonical Dataset Releases as partitioned Parquet`.

**Status:** complete

- [x] A Temporal Schedule or authorized versioned Operator CLI command requests Dataset Publication through durable platform state and a stable Workflow identity.
- [x] Only the one-slot Data Worker polls the Dataset Publication Task Queue, and two overlapping triggers cannot execute concurrent publication.
- [x] Live Tushare work cannot start without the recorded hosted-use authorization declaration, while deterministic fixture publication remains available with the gate closed.
- [x] A successful Workflow validates and atomically commits one immutable Dataset Release before recording durable Tracking trigger work; it does not wait for Personal Workspace Tracking Advances.
- [x] A failed, cancelled, or redelivered publication leaves the previous Dataset Release authoritative and publishes no partial manifest or candidate object set.
- [x] Dataset Publication follows the shared resource-exhaustion policy: the first exhausted Activity may retry once, a second ends with stable `RESOURCE_EXHAUSTED`, and neither execution can publish a partial Dataset Release.
- [x] User APIs expose the resulting Dataset Release read-only, and no authenticated User route can invoke, mutate, or delete platform Dataset Publication.
- [x] Dataset Publication consumes the independent Data slot and does not reduce the four-slot Compute capacity.

**Acceptance evidence:** Operator and bounded typed Schedule requests now commit
idempotent platform Publication state plus an execution Outbox entry, and the
relay starts the stable `dataset-publication/<id>` Workflow on the dedicated
`thesistrace-data` queue. The one-slot Data Worker alone polls that queue and a
database-wide slot fence prevents overlapping publication. Scheduled writes
use one parameter-bounded `SECURITY DEFINER` function; the Data role cannot
directly mutate the platform Outbox. Live requests and execution both enforce
the recorded hosted Tushare authorization, while fixture publication remains
available with the gate closed. Candidate objects are staged, then one
transaction commits the immutable Release, authoritative pointer, Publication
terminal state, and pending Tracking trigger. PostgreSQL row locking plus a
synchronous cancellation check inside the commit fence linearizes cancellation
against success. Failed candidates remove newly promoted manifests and
reference-safe candidate payloads without changing prior Releases or the
ResearchRun shared-CAS behavior. Activity bootstrap and execution both stop
resource exhaustion after at most two deliveries with stable
`RESOURCE_EXHAUSTED`.

Fresh PostgreSQL migrations applied successfully. Real Data-role acceptance
proved atomic Release/trigger publication and denied direct Outbox mutation; a
two-connection success-versus-cancel race ended `cancelled` with no Release.
A source-mounted one-slot Data Worker then completed a real Temporal fixture
Workflow with exactly one Release, one Attempt, and one Tracking trigger. The
focused suite passed `48` tests with one environment-gated skip, and the full
Python suite passed `133` tests with `8` environment-gated skips. Independent
Standards and Spec reviews both passed after the cancellation, candidate
cleanup, schedule-input, least-privilege, and PostgreSQL race corrections.
