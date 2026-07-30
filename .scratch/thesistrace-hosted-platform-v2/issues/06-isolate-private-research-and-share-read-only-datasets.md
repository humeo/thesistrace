# 06 — Isolate private research and share read-only Datasets

**What to build:** Make Personal Workspace the enforced ownership boundary for
private research while exposing each platform-owned Dataset Release read-only
to every authenticated User through bounded product APIs.

**Blocked by:** 05 — Consume an invitation and provision one Personal Workspace; `thesistrace-bounded-research-storage/02 — Publish Canonical Dataset Releases as partitioned Parquet`.

**Status:** complete

- [x] The API derives the authoritative Personal Workspace from the verified User mapping and ignores or rejects every client-supplied Workspace identity.
- [x] Every currently existing Personal Workspace-owned product table has a non-null `workspace_id` and a production PostgreSQL RLS policy.
- [x] The non-superuser API role has no `BYPASSRLS`, sets Workspace context transactionally, and cannot broaden access by omitting or forging that context.
- [x] Two Users can independently create, list, read, and update Research Definition Drafts without observing identifiers, counts, or content from the other Personal Workspace.
- [x] Both Users can list and inspect the same immutable Dataset Releases and data contracts, while neither can mutate, bootstrap, or publish one.
- [x] Hosted product responses expose no physical path, storage credential, directly usable object key, raw object download, signed URL, or public Storage route.
- [x] A real PostgreSQL contract suite exercises cross-Workspace reads and writes for every private table and proves each service role can perform only its accepted responsibilities.

**Acceptance evidence:** The production migrations create twelve non-null
Personal Workspace-owned tables with `ENABLE/FORCE ROW LEVEL SECURITY`, a
transaction-scoped identity-to-Workspace context, and non-superuser,
non-`BYPASSRLS` API, Compute, and Data roles. The real PostgreSQL contract suite
passed both scenarios: every private table denied cross-Workspace reads and
writes, omitted and forged client context failed closed, and Dataset mutation
was denied to the API role. The complete Compose stack then started healthy in
Hosted PostgreSQL mode. Through the public HTTPS Origin, two real InsForge
Users provisioned distinct Personal Workspaces, independently created and
listed Drafts, received non-disclosing cross-Workspace 404s, read the same
bounded Dataset Release and data contract, and received 404s for Dataset
publication and raw object routes. Fresh API, Data Worker, and Compute Worker
logs contained no role or RLS errors.
