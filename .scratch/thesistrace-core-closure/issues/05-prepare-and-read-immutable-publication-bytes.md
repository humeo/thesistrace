# 05 — Prepare and verify immutable Publication bytes

**What to build:** Establish canonical serialization, checksums, and immutable
content-addressed uploads through a standard S3 client against pinned RustFS.

**Blocked by:** 03.

**Status:** ready-for-agent

- [ ] Preparing a supported bundle canonically serializes every payload and
  calculates deterministic checksums before upload.
- [ ] The prepared publication binds caller-supplied kind, immutable payloads,
  and provenance into one deterministic manifest input.
- [ ] Bytes are stored under content-addressed keys that are never overwritten.
- [ ] Re-preparing identical content is safe and does not create divergent
  physical truth.
- [ ] Verification detects missing, truncated, substituted, or checksum-invalid
  objects.
- [ ] The application uses an existing standard S3 client; it implements no
  object-store server, storage token protocol, or HTTP filesystem proxy.
- [ ] Physical keys remain private to Publication.

**How to verify:**

- Run `uv run pytest -q tests/integration` against pinned RustFS and confirm
  deterministic upload plus verified reads of the prepared bytes.
- Corrupt or remove one test object and confirm verification rejects it without
  returning payload data to a product caller.

## Comments
