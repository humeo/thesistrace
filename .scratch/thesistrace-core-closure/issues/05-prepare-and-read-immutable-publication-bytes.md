# 05 — Prepare and verify immutable Publication bytes

**What to build:** Establish canonical serialization, checksums, and immutable
content-addressed uploads through a standard S3 client against pinned RustFS.

**Blocked by:** 03.

**Status:** ready-for-agent

**Implementation:** complete

- [x] Preparing a supported bundle canonically serializes every payload and
  calculates deterministic checksums before upload.
- [x] The prepared publication binds caller-supplied kind, immutable payloads,
  and provenance into one deterministic manifest input.
- [x] Bytes are stored under content-addressed keys that are never overwritten.
- [x] Re-preparing identical content is safe and does not create divergent
  physical truth.
- [x] Verification detects missing, truncated, substituted, or checksum-invalid
  objects.
- [x] The application uses an existing standard S3 client; it implements no
  object-store server, storage token protocol, or HTTP filesystem proxy.
- [x] Physical keys remain private to Publication.

**How to verify:**

From the repository root, run the complete ticket verification exactly as
written. It resets the dedicated PostgreSQL/RustFS test state, runs the
architecture and integration contracts against those real services, and
always stops them afterward.

```sh
set -eu
cleanup() { ./scripts/core-test-runtime down; }
trap cleanup EXIT

./scripts/core-test-runtime reset
./scripts/core-test-runtime run \
  uv run pytest -q tests/architecture tests/integration
```

The integration suite must prove deterministic upload and verified reads, then
remove, truncate, and substitute test objects and confirm verification rejects
each complete bundle. It must also prove a conflicting object at an existing
content address is rejected without being overwritten.

## Comments

- TDD red: the integration contract initially fails to import the canonical
  `thesistrace.publication` module; no prepare/verify API exists yet.
- TDD green: the focused real-RustFS contract passed `5 passed`. It exercises
  canonical JSON, canonical Parquet row ordering and writer metadata,
  deterministic manifests, idempotent content reuse, all three object-damage
  modes, and immutable-address conflicts.
- Publication derives physical S3 keys only inside its module. Prepared and
  verified product values expose logical payload names, checksums, media type,
  serialization contract, kind, and provenance, but never a bucket or key.
- Upload uses the standard Boto3 S3 client with `If-None-Match: *`; an existing
  address is read and verified, never overwritten by application code.
- The exact clean-state command above passed `15 passed` in `0.59s`; cleanup
  stopped both containers and removed only the dedicated test state.
