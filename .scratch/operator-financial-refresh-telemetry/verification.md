# Verification — 2026-09-04

## Historical operation, read-only diagnosis

- Operation: `financial-20260904T063104Z`.
- Requested through 2026-08-17; succeeded/degraded; complete through 2026-08-14.
- Started 06:32:37.699124Z; finished 06:33:07.532604Z (~30s, UI floors to 29s).
- Discovery returned 15 announcements across successful categories (includes the
  overlap window, not exclusively new work). Ten triggers were matched for four
  companies: 000698.SZ, 300264.SZ, 301152.SZ, 600449.SH.
- All four company attempts were accepted with Canonical changes; zero failed.
- One half-year-report discovery gap: query 2026-08-08..2026-08-17,
  unverified from 2026-08-15, `CNINFO_DISCOVERY_UNAVAILABLE`.
- Adapter classification includes timeout/connection/requests-family exceptions.
  Persisted evidence does not identify the exact transport exception or HTTP code;
  do not claim a confirmed timeout, rate limit, or upstream outage.

## Implementation and review

- Safe, bounded SQL projection of existing operation-scoped discovery evidence and
  company attempts. No raw financial payloads, checkpoint contents, URLs, ownership
  tokens, or internal manifests reach the UI.
- Historical gap evidence is independent of later mutable global-gap resolution.
- No fabricated total-company denominator. Unknown discovery/expired telemetry
  stays unknown. Company processing does not claim publication.
- Receipt polling retains last-known counts on failure and stops after terminal
  publication. Existing authorization, exact target binding, and phase ownership
  remain in place.
- No schema changes, migrations, source queries, live refresh submissions,
  Worker restarts, or edits to unrelated skills changes.

## Checks

- Red test observed before implementation: running receipt omitted company progress.
- `sh .scratch/operator-financial-refresh-telemetry/verify-postgres.sh`: **8 passed**;
  isolated PostgreSQL, independent project/network/volume/account; cleaned up.
  Evidence: `/var/folders/py/j9ws8lpn57g_syngj3b58b6h0000gn/T/tmp.CVMHW7osvA/pytest.xml`.
- Focused Operator HTTP/status tests: **24 passed** after final API adjustment.
- Operator Vitest: **57 passed**, including visible-page polling, partial counts,
  stale values, publication phase, terminal stop, strict nested decoding.
- Web typecheck, `uv run ruff check src tests`, `git diff --check`: passed.
- Expanded architecture/Data/entrypoint suite: **686 passed, 1 existing failure**.
  `test_web_shell_declares_only_the_four_product_resources` includes import names
  in its resource-route text check and rejects `handleWorkspaceNavigation`.
  Both that test and `AppShell.tsx` are unchanged from HEAD; isolated recheck
  reproduces it. Not altered by this feature and not reported as a passing gate.
- Production API/Web image builds succeeded; product bundle budget passed.
- Real authenticated Operator history details show 15 discovered, 4 processed,
  4 changed, 0 unchanged, 0 failed, and the half-year discovery gap.
- Desktop and 390px layouts inspected. At 390px, dialog client/scroll width 374px
  and telemetry client/scroll width 342px: no horizontal overflow. Viewport restored.

## Delivery boundary

Local API and Web updated. Data Worker and durable refresh state were left alone.
The CNINFO gap has not been repaired by this presentation change. No commit made.
