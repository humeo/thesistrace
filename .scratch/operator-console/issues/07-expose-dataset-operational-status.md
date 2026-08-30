# 07 — Expose unified Dataset Operational Status

**What to build:** Give the Operator one safe, dense Data surface that identifies
the Dataset Head currently used by research and makes the ordered lifecycle of
Market, Financial, and Industry Refreshes understandable without reading logs or
storage internals.

**Blocked by:** 05 — Run Financial Refresh through the durable Data Operator
Worker; 06 — Run Industry Refresh through the durable Data Operator Worker.

**Status:** complete

- [x] `/operator/data` leads with current Dataset Head identity and readiness and
  shows the most recent Data Refresh Operation for each Refresh kind.
- [x] All three kinds share one global FIFO with at most one running operation;
  cross-kind integration tests prove acceptance order and absence of concurrent
  Dataset Head writers.
- [x] Operation history is reverse chronological, stable, and server-paginated in
  pages of 50.
- [x] Visible operation state distinguishes accepted, running phase, attempt,
  last heartbeat, published, no change, degraded, failed, and cancelled using
  text rather than color alone.
- [x] A detail drawer shows safe target, idempotency key, timestamps, counts,
  outcome, and stable failure code while excluding raw upstream responses,
  secrets, manifests, object paths, and unrestricted Dataset history.
- [x] A visible page containing non-terminal work polls every five seconds,
  stops after terminal state, and refreshes immediately on focus or network
  recovery; a manual Reload action is always available.
- [x] No SSE, WebSocket, event bus, service worker, or hidden background polling
  is introduced.
- [x] The ordinary Researcher-facing Data Overview remains read-only and does not
  expose Operator controls or operation history.
- [x] API and UI tests cover safe projection, stable pagination, each lifecycle
  state, polling start/stop, focus/network recovery, manual reload, and ordinary
  Researcher `404` behavior.
- [x] A real browser test verifies the dense responsive table, detail drawer,
  keyboard navigation, accessible status meaning, and all three Refresh kinds.

## Implementation Plan

1. **Define one bounded operational read model.** Add a Core-owned Dataset
   operational-status service that reuses the existing Dataset readiness
   calculation and projects only the current `data_identity`, Head preparation
   and through-Session facts, per-family readiness, and bounded Refresh receipt
   fields. Explicitly exclude generation hashes, manifests, object paths,
   Worker ownership and lease details, fingerprints, raw source responses, and
   unrestricted Dataset history; leave the ordinary `/api/data` contract
   unchanged.
2. **Persist the lifecycle facts the Operator must understand.** Hard-cut the
   shared `data.refresh_operations` schema and receipt model to carry a safe
   running phase and explicit last heartbeat, and admit `cancelled` as a
   terminal display state without adding a cancellation mutation yet. Set the
   phase at claim and durable pipeline boundaries, renew the heartbeat only for
   the owning claim, retain those facts at terminal completion, and preserve the
   existing one-slot cross-kind FIFO and publication fencing.
3. **Provide stable bounded history.** Add a server-owned opaque cursor secret
   and keyset pagination over `(created_at, idempotency_key)` in reverse order,
   fixed at 50 receipts with one-row lookahead. Return the current Head, the
   newest operation for each of Market, Financial, and Industry, and one page of
   safe receipt rows from an Operator-authenticated
   `GET /api/operator/data/status`; reject malformed or mismatched cursors and
   keep the same path unavailable to ordinary Researchers.
4. **Lead the Data surface with operational truth.** Add a dense Dataset Head
   and readiness band, a latest-per-kind summary, and a responsive aligned
   operation table before the three submission forms. Render every lifecycle
   meaning in text, expose bounded older/newer page navigation and manual
   Reload, and open a labelled right-side native-dialog drawer containing only
   safe target, key, phase, attempt, heartbeat, timestamps, counts, outcome, and
   stable failure fields with focus containment, Escape close, and trigger focus
   restoration.
5. **Poll only while the surface is visibly active.** Use one five-second
   operational-status poller when the visible response contains non-terminal
   work, cancel its timer while the document is hidden, stop it after a terminal
   response, and refresh immediately on window focus, network recovery, manual
   Reload, or a newly accepted submission from any of the three forms. Guard
   stale requests and introduce no SSE, WebSocket, event bus, service worker, or
   hidden background polling.
6. **Prove ordering, safety, interaction, and presentation.** Add parser and
   Core HTTP contract tests for strict safe projection and Researcher denial;
   real-PostgreSQL tests for cross-kind FIFO/single writer, latest-per-kind,
   identical-timestamp keyset pages, concurrent inserts, lifecycle facts, and
   seeded cancelled display; deterministic Web tests for all textual states,
   pagination, drawer keyboard behavior, polling stop/start, visibility,
   focus/online recovery, and manual reload; and a real Caddy browser flow for
   Dataset identity/readiness, all three kinds, responsive stacked rows, and the
   accessible drawer. Run focused and full host, integration, E2E, and
   production-image gates, complete Standards and Spec review/fix/re-review,
   update this tracker, and commit Ticket 07 alone.

## Verification

- `pnpm test`: Ruff passed; 914 Python tests, 168 Auth tests, and 138 Web tests
  passed. The only warning is the existing `forkpty()` deprecation in the local
  lifecycle architecture test.
- `pnpm test:integration`, run
  `20260830t093754z-94935-1b77a5d3`: 408 primary integration/acceptance tests,
  six controlled PostgreSQL/RustFS restart tests, and 126 Auth integration tests
  passed; the isolated Compose project, network, and mutable volumes were
  removed.
- `pnpm test:e2e`, run `20260830t095732z-4568-74b39338`: all 16 real Caddy
  browser tests passed, including singleton Operator authorization, Dataset Head
  and readiness, all Refresh kinds, safe keyboard drawer, 640px stacked table,
  visible-only polling, terminal stop, recovery refresh, and Researcher `404`.
- `pnpm test:image-smoke`, Core run
  `20260830t100242z-7090-0bdfc9b7`, Auth run
  `20260830t101313z-11226-aa8e8e3b`, and Caddy image run
  `20260830t101339z-11587-526255e4`: final Backend, Auth, Web, Caddy, PostgreSQL,
  RustFS, and Worker image smoke gates passed, including controlled dependency,
  process, and volume-loss recovery.
- Standards review fixed the test-history isolation revealed by the first full
  integration run, tightened `data_identity` to the existing 64-character
  lowercase SHA-256 contract, removed a drawer glass effect forbidden by
  `DESIGN.md`, and scoped legacy browser assertions to their receipts after the
  unified status table introduced duplicate visible state text. Spec re-review
  found no remaining acceptance gap; `git diff --check` passed.
