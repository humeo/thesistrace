# Hosted V2 pre-Core-closure archive manifest

This manifest defines the recoverable Hosted V2 snapshot taken immediately
before Core-closure implementation begins.

## Identity

- Archive ref: `refs/archive/hosted-v2-pre-core-closure`
- Tracked-tree base: `f0a16066fc85a8b80fb26964a2ff265ee8627509`
- Archive form: the complete tracked tree at the base commit plus the four
  explicitly listed archive additions below

Using the complete tracked tree is intentional. Hosted V2 shares product,
configuration, dependency, API, runtime, and Web files with the earlier V1
implementation; selecting only paths whose names contain `hosted` would not
produce a recoverable system.

## Hosted material covered by the tracked-tree base

- Hosted specification, tickets, evidence, and existing research:
  `.scratch/thesistrace-hosted-platform-v2/**`
- Hosted application source: `src/thesistrace/hosted/**`
- Hosted tests: `tests/hosted/**`
- Deployment and operations assets: `deploy/hosted/**`
- Hosted scripts: `scripts/hosted/**`, `scripts/hosted-stack`,
  `scripts/hosted-*-smoke.py`, and `scripts/validate-cloudflare-edge`
- Runbooks at the archived ref: `docs/runbook/hosted-compose.md` and
  `docs/runbook/hosted-health.md`
- Hosted architecture decisions: `docs/adr/0110-*.md` through
  `docs/adr/0149-*.md`
- Hosted Web surface: `web/e2e-hosted/**`,
  `web/playwright.hosted.config.ts`, and `web/src/hostedAuth.tsx`
- Shared tracked product and build material at the base commit, including
  `CONTEXT.md`, `Makefile`, `pyproject.toml`, `uv.lock`, shared
  `src/thesistrace/**`, shared `tests/**`, and `web/**`

## Explicit archive additions

These files existed in the working tree but were not tracked by the base
commit. They are included because they document the last Hosted V2 identity,
session, and InsForge architecture decisions:

- `.scratch/thesistrace-hosted-platform-v2/research/bff-postgres-session-csrf-libraries.md`
- `docs/adr/0150-separate-insforge-identity-from-thesistrace-auth-sessions.md`
- `docs/research/2026-08-03-insforge-use-cases-and-reference-architecture.md`
- `docs/archive/hosted-v2-pre-core-closure.md`

## Deliberate exclusions

The archive does not include uncommitted Core-closure work, including
`.scratch/thesistrace-core-closure/**`, `docs/adr/0151-*.md`,
`docs/architecture/core.md`, or the working-tree edits that supersede Hosted
ADRs and rewrite `CONTEXT.md` for the Core architecture. It also excludes
ignored runtime state, caches, credentials, generated files, and Python bytecode.

## Recovery contract

Resolve the archive ref, restore it into a clean detached worktree, and verify
that every category and explicit addition above is present. The restored tree
must be independent of the active working tree and must not require any
uncommitted Core-closure file.

```sh
git show-ref --verify refs/archive/hosted-v2-pre-core-closure
git worktree add --detach <clean-directory> refs/archive/hosted-v2-pre-core-closure
git -C <clean-directory> status --short
```

The final command must print nothing. Removal of the verification worktree is
safe after the recorded archive commit and manifest have been checked.
