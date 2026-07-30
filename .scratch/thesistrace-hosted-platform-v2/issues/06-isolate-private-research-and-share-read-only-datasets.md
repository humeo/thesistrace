# 06 — Isolate private research and share read-only Datasets

**What to build:** Make Personal Workspace the enforced ownership boundary for
private research while exposing each platform-owned Dataset Release read-only
to every authenticated User through bounded product APIs.

**Blocked by:** 05 — Consume an invitation and provision one Personal Workspace; `thesistrace-bounded-research-storage/02 — Publish Canonical Dataset Releases as partitioned Parquet`.

**Status:** ready-for-agent

- [ ] The API derives the authoritative Personal Workspace from the verified User mapping and ignores or rejects every client-supplied Workspace identity.
- [ ] Every currently existing Personal Workspace-owned product table has a non-null `workspace_id` and a production PostgreSQL RLS policy.
- [ ] The non-superuser API role has no `BYPASSRLS`, sets Workspace context transactionally, and cannot broaden access by omitting or forging that context.
- [ ] Two Users can independently create, list, read, and update Research Definition Drafts without observing identifiers, counts, or content from the other Personal Workspace.
- [ ] Both Users can list and inspect the same immutable Dataset Releases and data contracts, while neither can mutate, bootstrap, or publish one.
- [ ] Hosted product responses expose no physical path, storage credential, directly usable object key, raw object download, signed URL, or public Storage route.
- [ ] A real PostgreSQL contract suite exercises cross-Workspace reads and writes for every private table and proves each service role can perform only its accepted responsibilities.
