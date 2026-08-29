# Operator Console

**Status:** ready-for-agent

## Problem Statement

The person operating a ThesisTrace deployment cannot currently manage routine
Researcher access or Data Refresh work from the product. Researcher and
Invitation inspection, invitation issuance, Session revocation, and data
operations depend on deployment-private commands. The product also lacks one
safe operational view that distinguishes a submitted Data Refresh from work that
is running, published, unchanged, degraded, failed, or cancelled.

This makes ordinary administration unnecessarily dependent on shell access and
makes it difficult for the Operator to answer basic questions: who can use the
deployment, which Invitation is effective, whether a Refresh is merely queued,
which Dataset Head is current, and whether a completed operation published a new
Data Generation.

## Solution

ThesisTrace adds a same-origin `/operator` Console for the single Researcher
holding the indivisible Operator Capability. It manages Researcher
access and Invitations, starts each Data Refresh explicitly, and exposes enough
Dataset Operational Status to distinguish submission, processing, publication,
degraded success, and failure without exposing raw storage.

Every mutation requires the Operator's current password and a short-lived,
single-use Operator Proof bound to the exact Login Session, action, and request.
Ordinary Researchers receive `404` for every Operator route and API and see no
Operator navigation. The Console and private CLI share the same application
services, including one durable Data Operator Worker for all three Refresh kinds.

## User Stories

1. As the Operator, I want to use my existing Researcher account, so that I do
   not need a separate administrator identity.
2. As the Operator, I want an Operator navigation item at the bottom of the
   application sidebar, so that routine operational work is discoverable without
   displacing the research resources.
3. As an ordinary Researcher, I want the normal product navigation to remain
   unchanged, so that administrative concepts do not enter my research workflow.
4. As an ordinary Researcher, I want direct requests to Operator pages and APIs
   to return `404`, so that the deployment does not reveal an inaccessible
   administration surface.
5. As the Operator, I want to list Researchers, so that I can understand who has
   access to the deployment.
6. As the Operator, I want each Researcher row to show display label, canonical
   email, Researcher ID, active state, creation time, latest successful login,
   and current Login Session count, so that I can assess access without querying
   the database.
7. As the Operator, I want to search Researchers by canonical email or display
   label, so that I can find one account quickly.
8. As the Operator, I want Researcher results paginated on the server in pages of
   50, so that the Console remains usable as the deployment grows.
9. As the Operator, I want to see the effective Invitation associated with a
   Researcher, so that I can tell which invitation link is valid.
10. As the Operator, I want to see terminal Invitations retained by the existing
    30-day window, so that I can understand recent invitation outcomes.
11. As the Operator, I want to list Invitations independently of Researchers, so
    that pending access can be reviewed before an account exists.
12. As the Operator, I want to issue an Invitation using the existing invitation
    rules, so that a new Researcher can join without deployment shell access.
13. As the Operator, I want to reissue an Invitation, so that an expired or lost
    link can be replaced.
14. As the Operator, I want reissue confirmation to state that the old link will
    become invalid, so that I understand the security effect before proceeding.
15. As the Operator, I want validation failures to leave the current effective
    Invitation unchanged, so that a rejected request cannot break access.
16. As the Operator, I want to revoke all Login Sessions belonging to another
    Researcher, so that I can respond to a lost or compromised device.
17. As the Operator, I want the confirmation to show the target Researcher and
    current Session count, so that I can verify the scope of revocation.
18. As the Operator, I want the Console to reject attempts to revoke my own Login
    Sessions, so that I cannot accidentally remove the only active administrator.
19. As the Operator, I want every mutation to ask for my current password, so
    that an unattended authenticated browser cannot silently change access or
    data state.
20. As the Operator, I want each confirmation dialog to summarize the action,
    target, effect, and exact parameters, so that I can catch mistakes before
    submitting my password.
21. As the Operator, I want an invalid, expired, mismatched, or replayed Operator
    Proof to have no side effect, so that proof failure is fail-closed.
22. As the Operator, I want my password to exist only for the confirmation
    request and never be persisted by the browser, so that the Console does not
    create a reusable credential copy.
23. As a deployment administrator, I want to assign the first Operator Capability
    to an existing active Researcher through a private command, so that public
    product APIs cannot create their own administrator.
24. As a deployment administrator, I want to transfer the Operator Capability
    atomically through a private command, so that the deployment always has
    exactly one Operator.
25. As the new Operator, I want transfer to revoke every Login Session of the
    former Operator, so that the old browser state loses administrative authority
    immediately.
26. As the Operator, I want the Data surface to lead with the current Dataset Head
    and readiness, so that I can see what research will consume now.
27. As the Operator, I want to see the most recent Data Refresh Operation for each
    Refresh kind, so that Market, Financial, and Industry freshness are distinct.
28. As the Operator, I want reverse-chronological operation history with 50-row
    server pagination, so that I can inspect recent activity without loading an
    unbounded log.
29. As the Operator, I want a safe operation-detail drawer, so that I can inspect
    target, phase, counts, failure code, and timestamps without seeing raw
    upstream or storage internals.
30. As the Operator, I want Market Refresh to accept the same explicit,
    timezone-aware `as-of` input as the CLI, so that Web and CLI submissions mean
    the same thing.
31. As the Operator, I want Financial Refresh to accept the same explicit
    observation-through Research Session as the CLI, so that the server does not
    silently choose a different boundary.
32. As the Operator, I want Industry Refresh to accept the same explicit
    observation-through Research Session as the CLI, so that its collection
    boundary remains visible and reproducible.
33. As the Operator, I want Web and CLI Refresh inputs to use the same backend
    validation, so that one interface cannot submit work rejected by the other.
34. As the Operator, I want each Refresh form to suggest a kind-and-time-based
    idempotency key, so that ordinary submissions are safe by default.
35. As the Operator, I want to edit the suggested idempotency key and see the
    exact accepted key later, so that I can deliberately coordinate or inspect
    submissions across Web and CLI.
36. As the Operator, I want submission to return after a Data Refresh Operation
    is durably accepted, so that a long collection or publication does not hold
    an HTTP request open.
37. As the Operator, I want a persisted submission to remain accepted when the
    Data Operator Worker is unavailable, so that temporary Worker downtime does
    not lose requested work.
38. As the Operator, I want an explicit Worker-unavailable warning beside queued
    work, so that acceptance is not mistaken for active processing.
39. As the Operator, I want persistence failure to reject submission, so that the
    Console never reports work as accepted when no durable operation exists.
40. As the Operator, I want all Refresh kinds to share one FIFO, so that Dataset
    Head-writing operations run in an understandable order.
41. As the Operator, I want at most one Data Refresh Operation running at a time,
    so that upstream capacity and publication state cannot race.
42. As the Operator, I want to cancel an accepted operation before it is claimed,
    so that an obsolete queued request need not run.
43. As the Operator, I want running work to be non-cancellable, so that the
    Console does not imply a safe interruption boundary that the pipeline lacks.
44. As the Operator, I want Retry to copy the failed or cancelled operation's
    target into a new operation with a new idempotency key, so that the original
    receipt remains immutable.
45. As the Operator, I want operation copy to distinguish accepted, running,
    published, no change, degraded, failed, and cancelled states, so that I can
    interpret outcomes without reading logs.
46. As the Operator, I want a running operation to show its phase, attempt, and
    last heartbeat, so that I can distinguish progress from a lost claim.
47. As the Operator, I want Financial pending instruments or discovery gaps to
    appear as degraded success, so that usable publication is not mislabeled as
    either complete success or failure.
48. As the Operator, I want infrastructure loss to recover on the same operation
    and reconcile prior publication, so that a Worker crash does not create a
    duplicate Data Generation.
49. As the Operator, I want recovery to stop after three attempts with an explicit
    `RETRY_EXHAUSTED` failure, so that permanently failing work does not loop
    forever.
50. As the Operator, I want a visible non-terminal operation page to refresh every
    five seconds, so that progress updates without a manual reload.
51. As the Operator, I want polling to stop when visible work is terminal and to
    refresh immediately after focus or network recovery, so that the Console is
    current without producing hidden background traffic.
52. As the Operator, I want a manual Reload action, so that I can explicitly
    reconcile the view at any time.
53. As the Operator, I want terminal Data Refresh receipts retained for 180 days,
    so that recent operational history remains inspectable.
54. As a data maintainer, I want operation receipts not to retain Data Generations
    or override Garbage Collection roots, so that operational history does not
    become a hidden data-retention policy.
55. As a CLI Operator, I want private commands and the Console to call the same
    services, so that there is one authorization, validation, idempotency, and
    operation lifecycle contract.
56. As a deployment administrator, I want the Tushare Secret available only to
    the Data Operator Worker, so that Auth, Core API, Web, PostgreSQL, and browser
    state cannot expose it.
57. As a deployment administrator, I want a missing or placeholder Tushare Secret
    to fail Worker startup, so that Refresh execution cannot begin with an invalid
    upstream credential.
58. As the Operator, I want the Console to follow the existing dense, dark product
    workbench and responsive application shell, so that administration feels like
    part of ThesisTrace rather than a generic dashboard.
59. As a keyboard or assistive-technology user, I want tables, drawers, dialogs,
    navigation, focus containment, Escape behavior, focus restoration, status
    text, and touch targets to be accessible, so that every Operator workflow is
    usable without pointer-only or color-only cues.

## Implementation Decisions

- Exactly one account acts both as a Researcher and the Operator. There is no
  separate administrator identity, second Operator, Organization, generic
  role, or RBAC system. Establishment or transfer of the Operator Capability is
  available only through a deployment-private command. Initial assignment
  targets an existing active Researcher; transfer atomically replaces the
  assignment and revokes every Login Session of the former Operator.
- The Console lives at `/operator` on the existing public origin. Ordinary
  Researchers receive `404`, see no Operator navigation, and cannot infer the
  Console from an authorization response.
- Every Operator mutation requires confirmation with the current password. Auth
  produces a 60-second, single-use proof bound to the Login Session, operation,
  and request content; Core and Data Operator never receive the password.
- Auth owns the singleton Operator Assignment, proof issuance and consumption,
  Researcher and Login Session projection, and Invitation lifecycle. Core owns
  Dataset Operational Status and Data Refresh Operations. Neither runtime role
  reads the other's schema, the Better Auth Admin plugin remains absent, and no
  third administrator backend is introduced.
- Researcher management includes listing Researchers and Invitations, issuing
  or reissuing an Invitation, and revoking all of another Researcher's Login
  Sessions. The Console cannot revoke the current Operator's own Sessions.
- Researcher deactivation, reactivation, deletion, impersonation, email
  modification, and administrator-set credentials are excluded.
- The Researcher list shows display label, canonical email, Researcher ID,
  current active state, creation time, latest successful login time, current
  Login Session count, effective Invitation, and terminal Invitations retained
  during the existing 30-day window. It supports email or display-label search
  and 50-row server pagination but no export or client metadata.
- Market Refresh, Financial Refresh, and Industry Refresh remain three explicit
  actions. Each accepts the same explicit target input as its private CLI:
  Market accepts `as-of`, while Financial and Industry accept an
  observation-through Research Session. The Console does not offer an ambiguous
  combined Refresh or silently replace input with a server-selected date.
- The Console and private CLI submit every Refresh through the same durable
  operation services. One always-running, single-slot Data Operator Worker
  serially executes all three kinds; HTTP returns after `accepted`, never waits
  for collection or publication, and no automatic schedule is introduced.
- All three kinds share one FIFO. At most one operation runs, later submissions
  remain accepted in order, and neither Console nor CLI can prioritize, reorder,
  or run Refreshes concurrently.
- An accepted operation may be cancelled before a Worker claim. Running work
  cannot be cancelled; failed and cancelled receipts stay immutable; Retry
  copies the prior target into a new operation with a new idempotency key.
- Every claim has a 15-minute lease and 30-second heartbeat. Expired
  infrastructure claims are reconciled and reclaimed on the same operation up
  to three attempts, then fail as `RETRY_EXHAUSTED`. Business validation failure
  is terminal; Financial pending or discovery gaps remain explicit degraded
  success rather than a retry.
- `THESISTRACE_TUSHARE_TOKEN` exists only in the Data Operator Worker deployment
  environment. Missing or placeholder credentials fail Worker startup and are
  reported as Worker unavailable; Auth, Core API, Web, PostgreSQL, and browser
  state never receive the token.
- A temporarily unavailable Worker does not block submission. A successfully
  persisted operation remains `accepted` and the Console shows an explicit
  Worker-unavailable warning; failure to persist never returns accepted.
- Each form suggests an operation-kind-and-time-based idempotency key but lets
  the Operator edit it. The accepted response and operation status keep the
  exact key visible for later Console or CLI inspection.
- Dataset Operational Status includes the current Dataset Head and readiness,
  recent operation target and phase, safe success or failure counts, and safe
  failure codes. It excludes raw tables, object paths, manifests, and an
  unrestricted Dataset history browser.
- The status page leads with the current Dataset Head and the most recent
  operation of each kind, then exposes reverse-chronological 50-row server
  pagination. Non-terminal receipts remain until terminal; terminal receipts
  remain for 180 days. Receipts do not retain Data Generations or override
  existing GC roots.
- While a visible page contains non-terminal work, it polls every five seconds;
  it stops after terminal state and refreshes immediately on focus or network
  recovery. Manual Reload remains available. No SSE, WebSocket, event bus, or
  hidden background polling is added.
- Operation state copy distinguishes accepted, running phase, attempt and last
  heartbeat, published, no change, Financial degraded success, failed, and
  cancelled. Safe detail opens in a drawer and excludes raw upstream responses,
  secrets, manifests, and object paths.
- The Console adds no unified Operator audit model or activity page. Existing
  Auth security events, Invitation lifecycle records, and Data Refresh operation
  receipts remain the authoritative records for their own domains.
- The Operator surface is split into `/operator/researchers` and
  `/operator/data`. The ordinary Data Overview stays read-only; an `Operator`
  navigation entry appears at the bottom of the sidebar only for the Operator.
- Every mutation opens one accessible confirmation dialog with action, target,
  effect, and relevant parameters before requesting the current password.
  Reissue states that the old link becomes invalid; Session revocation shows the
  current Session count; Refresh, Cancel, and Retry show their exact targets and
  keys. Invalid password, expired proof, and replayed proof have no side effect;
  the browser never persists the password.
- The Console uses the existing application shell and repository design system:
  dense aligned rows, restrained surfaces and hairlines, visible status text,
  responsive navigation, and accessible dialogs and drawers. It does not adopt
  a separate generic-admin visual system.
- Refresh execution is a hard cut to the durable operation contract. The
  implementation keeps no compatibility, migration, fallback, or dual-execution
  path for obsolete one-shot Refresh behavior.
- Dataset Bootstrap, Garbage Collection, Replay, Financial capability probe,
  complete Financial collection, and source diagnostics remain private CLI-only
  operations.

## Testing Decisions

- Tests assert externally visible behavior and domain invariants rather than
  private functions, call counts, component structure, or implementation order.
  Each invariant is tested at the lowest sufficiently real existing seam.
- Auth unit and isolated PostgreSQL integration tests cover singleton assignment,
  atomic transfer, former-Operator Session revocation, exact proof binding,
  expiry, single consumption, concurrent consumption, replay, Invitation
  issue/reissue atomicity, rejected self-revocation, and ordinary-Researcher
  `404`.
- The bounded Auth-to-Core proof verification contract is tested across the HTTP
  boundary, including operation and request binding, expiry, unavailable Auth,
  duplicate delivery, and fail-closed behavior with no mutation side effect.
- Core and Data integration tests cover one FIFO, accepted-only cancellation,
  immutable Retry, idempotent submission, single claim, three-attempt lease
  recovery, publication reconciliation, degraded Financial outcomes,
  Worker-unavailable submission, safe status projection, and 180-day receipt
  cleanup without Generation retention. These tests use real isolated
  PostgreSQL and deterministic source replay.
- Browser E2E runs through Caddy with one Operator and one ordinary Researcher,
  real PostgreSQL and RustFS, Resend fake, and versioned Tushare replay. It covers
  navigation isolation, Researcher and Invitation views, issue/reissue, Session
  revocation, all three Refresh forms, editable idempotency keys, queued warning,
  polling, cancellation, Retry, and Dataset status.
- Browser E2E also covers keyboard-only operation, dialog focus containment,
  Escape and focus restoration, accessible names, non-color status meaning,
  reduced motion, responsive navigation, and preservation of critical fields on
  narrow screens.
- Production Image Smoke verifies the final Auth, Core, Data Operator Worker,
  Web, Caddy, PostgreSQL, and RustFS images and proves the Tushare Secret exists
  only in the Worker. It also verifies startup, health, proof consumption,
  submission-to-Worker processing, publication, and browser visibility.
- Existing Auth/PostgreSQL Invitation and Login Session integration coverage is
  the prior art for identity behavior. Existing Data Refresh service, lease, and
  Dataset Head publication coverage is the prior art for operation recovery and
  publication invariants.
- Ordinary tests never access the public internet. Time, UUIDs, idempotency keys,
  source responses, and operation transitions are deterministic; asynchronous
  assertions use bounded condition polling rather than arbitrary sleeps.
- Live Tushare verification remains a separate explicit gate and does not block
  the deterministic release gate.

## Out of Scope

- More than one Operator, multiple roles, generic RBAC, Organizations, teams, or
  an administrator identity separate from a Researcher.
- Establishing or transferring the Operator Capability from the Console.
- Researcher deactivation, reactivation, deletion, impersonation, email editing,
  administrator-set passwords, or revocation of the current Operator's own Login
  Sessions.
- Exporting Researcher data, showing IP addresses or User-Agent strings, or
  exposing complete authentication/security history.
- A unified Operator audit model, audit log, or activity page.
- A combined “Update all” action, automatic scheduling, priority, reordering,
  concurrent Refreshes, per-kind Workers, or long-running Refresh HTTP requests.
- Cancelling running work, reopening terminal operations, or mutating an existing
  receipt during Retry.
- SSE, WebSockets, an event bus, service-worker refresh, or background polling
  when the Operator page is not visible.
- Raw table browsing, unrestricted Dataset history, upstream response bodies,
  secrets, manifests, or object-storage paths in the Console.
- Dataset Bootstrap, Garbage Collection, Replay, Financial capability probing,
  complete Financial collection, and source diagnostics; these remain private
  CLI-only operations.
- Changing the ordinary Researcher-facing Data Overview from a read-only surface.
- Public-internet-dependent tests or routine live-Tushare release tests.
- Compatibility adapters, transitional dual execution, migrations, or fallback
  behavior for superseded one-shot Refresh paths.

## Further Notes

- The current Market Refresh flow is a private two-step CLI process: submission
  is followed by a separately invoked one-shot worker command. Financial and
  Industry Refreshes currently execute synchronously in one-shot CLI processes.
  This specification replaces all three execution shapes with the single durable
  Data Operator Worker described above.
- Submission, processing, publication, and Dataset Head advancement remain
  distinct facts. UI copy and tests must never use `accepted` as a synonym for
  `published`.
- ADR-0239 records the singleton capability-gated Operator Console. ADR-0240
  records the single durable Data Operator Worker. ADR-0241 records the Auth/Core
  authority split.
- The design tree has no unresolved frontier. The agreed testing seams are Auth
  unit and real-PostgreSQL integration, Core/Data integration, real browser E2E
  through Caddy, and final Production Image Smoke.

## Comments

- 2026-08-29: The user accepted all first-round recommended boundaries during a
  `grill-with-docs` session.
- 2026-08-29: The user limited the product to exactly one Operator, kept CLI-like
  explicit Refresh targets, removed Researcher deactivation and unified Operator
  audit from scope, and requested the current Refresh execution facts before
  choosing the future execution model.
- 2026-08-29: The user accepted private initial assignment and atomic transfer,
  a single durable Data Operator Worker shared by Web and CLI, other-Researcher
  Session revocation only, editable suggested idempotency keys, and separate
  Researcher and Data Operator routes.
- 2026-08-29: The user accepted one FIFO, accepted-only cancellation, immutable
  Retry, the existing 15-minute lease and 30-second heartbeat extended across
  all Refreshes with three attempts, Worker-only Tushare credentials, and
  180-day paginated terminal operation receipts.
- 2026-08-29: The user accepted split Auth/Core Operator authority, queued
  submission while the Worker is unavailable, visible five-second polling,
  accessible password confirmation, CLI-only exceptional data operations, and
  deterministic full-stack browser and image qualification with external fakes.
- 2026-08-29: `to-spec` published the confirmed design with the
  `ready-for-agent` triage state and the agreed test seams.
