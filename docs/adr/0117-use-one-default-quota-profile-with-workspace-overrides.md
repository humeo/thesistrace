---
status: accepted
---

# Use one default Quota Profile with Workspace overrides

Every Personal Workspace in the first hosted release receives the same
platform-managed default Quota Profile. An operator may apply explicit
Workspace-specific overrides, but the product introduces no billing tiers,
subscriptions, payments, or automatic upgrades.

Quota changes govern new task admissions and new writes. They do not cancel
running work or delete immutable history. Assignments, overrides, and effective
limits remain auditable. Future commercial plans may select different Quota
Profiles without changing resource ownership or isolation.

The initial default and product hard maximum set `max_active_daily_tracks` to
10. A Workspace override may lower but not raise this limit. Only active
DailyTracks count; a Track still counts while its frontier Advance is blocked,
and stopped Tracks do not. Reaching the limit blocks new activation with
`QUOTA_EXCEEDED`. Lowering the limit does not stop existing Tracks, and
ResearchRuns do not consume this dimension.

The initial default also sets `max_nonterminal_user_compute_jobs` to eight.
It counts queued or running user-requested Compute work, including
ResearchRuns and explicit equivalence verification. System-generated normal
Tracking Advances do not consume this dimension. Terminal history and
idempotent redelivery do not count. Reaching the limit blocks new admission
with `QUOTA_EXCEEDED` and identifies the exceeded dimension.

The first hosted release sets no daily ResearchRun count or Compute-credit
limit. It records Workspace-attributed task counts, execution duration, peak
memory, and output bytes for capacity evidence, but those measurements do not
reject admission. Public registration, billing, or later capacity pressure may
reopen this decision.

The initial default sets `max_private_storage_bytes` to 10 GiB. It counts the
stored compressed bytes of Workspace-owned immutable objects, including Result
Bundles and Tracking Checkpoints. Platform-owned Dataset Releases, platform
logs, PostgreSQL overhead, and Resource Tombstones do not consume this
dimension. A result that cannot commit within the remaining quota fails
atomically and removes its temporary objects; deletion releases quota when
physical cleanup succeeds.

These are the only Quota Profile dimensions in the first hosted release. Daily
Run count, CPU duration, peak memory, request rate, per-result size, and Compute
credits are not additional User quotas. The platform may still reject work
through global resource limits, disk-pressure protection, API rate limiting, or
object-write atomicity without treating those controls as Quota Profile
dimensions. ADR-0143 defines those public-edge and API rate-limit
responsibilities.
