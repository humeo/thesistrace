# 16 — Enforce private storage and disk admission

**What to build:** Admit or reject payload-growing work from authoritative
compressed-byte accounting and node disk pressure so accepted publication is
atomic, prior truth remains readable, and control operations remain available
under pressure.

**Blocked by:** 09 — Enforce the Personal Workspace Quota Profile; 12 — Advance DailyTrack through finite Workflows; `thesistrace-bounded-research-storage/06 — Contract to the one-MiB Result Bundle`.

**Status:** resolved

- [x] PostgreSQL object indexes account for exact compressed bytes owned or referenced by each Personal Workspace without charging platform-owned Dataset Releases.
- [x] New private payload growth is rejected with the storage-quota dimension before exceeding the effective `10 GiB` limit, and an idempotent retry does not reserve bytes twice.
- [x] The configured 200-GB persistent SSD emits warning at 70%, rejects new private payload-growing work at 80%, and rejects all payload growth including Dataset Publication at 90%.
- [x] Reads, cancellation, deletion, cleanup, and the bounded control writes they require remain available at every disk-pressure level.
- [x] Result Bundle, Tracking Checkpoint, and Dataset Release publication repeat authoritative quota and disk checks immediately before one atomic manifest commit.
- [x] A failed final check publishes no partial resource, removes temporary unreferenced objects, and leaves the previously authoritative result or Dataset Release available.
- [x] Quota and disk-pressure acceptance verifies exact stored bytes through production indexes and distinguishes these failures from rate limiting, research validation, and Worker resource exhaustion.

## Resolution

- Added exact content/named-manifest indexes and SECURITY DEFINER commit
  functions in migration `0015_storage_admission.sql`. Private accounting is
  unique per Personal Workspace and platform Dataset Release references remain
  separate.
- Added projected disk admission to the private ObjectStore with the configured
  200-GB capacity, configurable 70/80/90 default thresholds, role-aware HTTP
  507 diagnostics, and a final check under the publication lock. Read,
  recovery, discard, guard, cancellation, and cleanup paths remain outside
  growth admission.
- Result Bundle, activation/advance Tracking Checkpoint, and Dataset Release
  success transitions now index their exact storage objects in the same
  PostgreSQL transaction as the authoritative state change. Rejection leaves
  the prior truth and staged-publication recovery removes unreferenced files.
- Verification: full Python lint, Web typecheck/build, 217 Python tests passed
  with 14 environment-dependent skips. A real isolated
  PostgreSQL 15 database applied all 15 migrations and proved `7 -> 7` byte
  idempotency, platform `5`-byte exclusion, `10`-byte quota rejection, and no
  rejected reference residue; the test database was removed afterward.
