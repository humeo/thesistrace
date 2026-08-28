# Multi-user Researcher authentication and ownership

**Status:** ready-for-agent

## Outcome

ThesisTrace provides invite-only email/password authentication for multiple Web
Researchers while preserving the module-first Core and its Worker execution
model. Caddy is the single public origin, Hono and Better Auth own
authentication, and FastAPI Core owns every product authorization decision.

The accepted architectural decision is
[ADR-0233](../../docs/adr/0233-separate-better-auth-identity-from-core-research-authorization.md).
The implemented contract is recorded in
[Core architecture](../../docs/architecture/core.md#identity-and-access).

## Implemented boundary

The current checkout has a Caddy Web image, a dedicated Hono and Better Auth
service, seven owner-scoped Core schemas plus an independent `auth` schema, one
same-origin browser route graph, and a pathname/search/hash React router. The
completed ownership cut is intentionally destructive for old Product State; it
preserves mounted Canonical Data and neither migrates nor adopts ownerless
resources or legacy Draft keys.

## Non-negotiable invariants

- Caddy is the only Production host listener and public authority.
- Hono and Better Auth are the only authentication and Cookie authority.
- Core verifies every product request through Auth and is the only Research
  Ownership authority.
- `core_runtime` cannot read `auth`; `auth_runtime` cannot read any Core schema.
- A Researcher directly owns private resources; there is no Workspace,
  Organization, Member, role, or RBAC layer.
- Every private-resource query includes Researcher scope. Cross-Researcher IDs
  return `404`, not `403`.
- Workers process already-admitted durable work without Auth or active-state
  checks. Researcher Deactivation never cancels or stops work implicitly.
- Auth failure is fail-closed. No cached identity, trusted identity header, JWT,
  anonymous fallback, compatibility mode, or startup migration exists.
- Every implementation ticket lands with its lowest sufficient real tests and
  remains an independently reviewable commit.

## Runtime topology

```text
Internet
  -> Caddy :80/:443
       -> /*            Vite static application
       -> /api/auth/*   Hono + Better Auth
       -> /api/*        FastAPI Core
                           -> private Auth Session verification
                           -> Research Ownership authorization

Private Compose network
  -> PostgreSQL: seven Core schemas + independent auth schema
  -> RustFS
  -> ordinary Research Worker
  -> Batch Research Worker
  -> Tracking Worker
```

Caddy route groups are ordered and mutually exclusive. Neither `/api/auth` nor
`/api` is prefix-stripped. Caddy explicitly rejects private health and internal
Auth paths instead of allowing the SPA fallback to answer them.

## Identity model

- Better Auth User UUID is reused directly as the Core Researcher ID.
- Auth is canonical for normalized email, initial display label, email-verified
  state, active state, credentials, and Login Sessions.
- Core adds a `researcher` module and `researchers` schema containing only the
  ownership anchor and Core lifecycle timestamps. It does not duplicate email,
  display label, or active state.
- Better Auth User adds one minimal `active` boolean field. Do not install the
  Admin, Organization, JWT, bearer, API-key, MFA, passkey, or audit-infrastructure
  plugins.
- Canonical email is trimmed, lowercased, globally unique, and no longer than
  254 characters.
- Better Auth's required `name` is the full canonical local-part before `@`.
  It is an initial display label only. The Operator may correct it privately;
  the first release exposes no self-service profile editing.

## Invitation-only account creation

- No `/signup` page exists. The Better Auth email sign-up endpoint remains
  guarded by a valid Researcher Invitation on every call.
- An Invitation is bound to one canonical email, expires after 48 hours, is
  single-use, and stores only the SHA-256 hash of 32 random bytes.
- A partial unique constraint allows at most one effective Invitation per
  canonical email. Reissue revokes the preceding Invitation before delivering
  the replacement. Existing User email cannot be invited.
- The private invite command creates a delivery-pending Invitation, calls the
  already-configured Resend API directly, and marks it usable only after Resend
  accepts the message. Delivery failure leaves no usable Invitation and requires
  a new issue or reissue command.
- The email URL is `<public-origin>/accept-invitation#token=<token>`. The token
  is never printed by a command or persisted in plaintext.
- The SPA extracts the fragment once, immediately removes it with
  `history.replaceState`, fetches the bound email, and displays that email
  read-only. The form asks only for password and confirmation.
- Account creation validates the token, email, expiry, revocation, and existing
  User before Better Auth creates a UUID User, verified email, scrypt credential,
  and Login Session. Password length is 12 through 128 characters.
- Invitation acceptance is idempotent under double-clicks, multiple tabs,
  retries, and a lost response. A unique User email and unique token hash prevent
  duplicates. If User creation committed while Invitation consumption was
  uncertain, the next attempt reconciles the Invitation to consumed by its
  bound email; it never replaces the existing password.

## Core Researcher bootstrap

- The browser calls authenticated `POST /api/researcher/bootstrap` immediately
  after Invitation auto-login and whenever SessionGate finds no Core Researcher.
- One Core transaction idempotently creates the Researcher plus
  `folder_default` and `folder_batch_research`.
- System Folder identity is `(researcher_id, folder_id)`, so every Researcher
  has the same two local IDs.
- Bootstrap failure blocks all product routes behind a retryable setup state.
  The next login retries. No GET mutates state and Auth never calls Core.

## Login Session contract

- Better Auth stores Sessions in PostgreSQL with `expiresIn = 7 days` and
  `updateAge = 1 day`.
- Cookie Session cache is disabled. Production Cookie attributes are Secure,
  HttpOnly, SameSite=Lax, Path=/, and host-only. Development and Test permit a
  non-Secure Cookie only for loopback HTTP.
- Hono exposes one private verification adapter that calls Better Auth
  `getSession` with the original Cookie, database lookup forced, and refresh
  disabled. Its successful response contains only Researcher ID, canonical
  email, display label, and active state.
- FastAPI makes exactly one bounded verification call per `/api/*` request.
  Invalid, expired, revoked, or inactive is `401`; timeout, transport failure,
  or malformed response is `503`.
- Hono is the only Cookie writer. FastAPI never forwards Auth `Set-Cookie`.
- The React Auth provider requests `/api/auth/get-session` on initial load,
  focus, network recovery, and every 12 hours while online and visible. This is
  the only rolling-Cookie refresh path.
- Ordinary logout revokes the current Session. Password change revokes other
  Sessions. Password reset and Researcher Deactivation revoke every Session.
- The UI exposes no Remember Me option, permanent lockout, session token,
  device-management page, or API credential.

## Password reset

- Reset request responses are indistinguishable for unknown, active, and
  deactivated emails. Deactivated emails receive no message.
- `sendResetPassword` sends asynchronously through Resend with caught and
  sanitized errors. Do not add an outbox, Redis, or provider abstraction.
- Reset links use `<public-origin>/reset-password#token=<token>`, are single-use,
  and expire after 30 minutes.
- Successful reset revokes all Sessions. Deactivation revokes outstanding reset
  records. Reactivation does not restore either.

## Research Ownership hard cut

- The target Core schema set is `researchers`, `publication`, `data`,
  `research_folders`, `research_runs`, `research_batches`, and `daily_tracks`.
- Research Folder primary identity is `(researcher_id, id)`.
- ResearchRun, Research Batch, and DailyTrack each store `researcher_id`.
  Cross-resource foreign keys include Researcher identity wherever they enforce
  Folder, Run, Batch-item, seed-Run, or Track relationships.
- Child execution tables may inherit ownership through an enforced parent key;
  they must not permit a cross-Researcher parent relationship.
- Admission, cancellation, start-tracking, retry, and stop receipts use
  `(researcher_id, request_id)` identity. The same request ID is independent for
  two Researchers.
- List, detail, mutation, Worker publication, recovery, and diagnostics paths
  preserve ownership scope. Browser-facing lookups never reveal another
  Researcher's resource existence.
- Pagination cursors encode Researcher ID and all query filters. A cursor reused
  by another Researcher or with different filters is `400`.
- RustFS remains globally content-addressed. PostgreSQL owner-scoped references
  are the only access path; object keys, manifests, and presigned URLs never
  become browser identifiers.

## Researcher Deactivation

- Operator access commands are private deployment operations: invite, reissue,
  deactivate, reactivate, revoke Sessions, and correct display label.
- Commands accept an explicit canonical email or Researcher ID, are idempotent,
  emit one structured stdout result, and send safe events to stderr.
- Deactivation atomically sets Auth User inactive, revokes Sessions, reset
  records, and effective Invitations, and records an audit event.
- A deployment-side access command combines a Core-owned active-DailyTrack
  inspection with the Auth-owned mutation while retaining separate database
  roles. It reports the count but never calls Stop automatically.
- Requests verified before the deactivation commit may finish. Verification
  starting after commit fails. Workers never check active state and continue
  queued or running Runs, Batches, and future Tracking Advances.
- Reactivation sets active state only. It creates no Session and changes no Core
  resource.

## Browser contract

- Anonymous pages: `/login`, `/accept-invitation`, `/forgot-password`, and
  `/reset-password`.
- Authenticated pages remain `/data`, `/research`, `/research-runs`, Run detail,
  `/daily-tracks`, and Track detail.
- Root chooses `/data` for a valid Session and `/login` otherwise. Protected
  navigation preserves only a validated same-origin relative `returnTo`.
- Extend the existing lightweight router to pathname, search, and hash; do not
  add React Router solely for authentication.
- One `AuthProvider` and `SessionGate` own loading, setup, anonymous, authenticated,
  and Auth-unavailable states.
- Replace page-local Core fetch behavior with shared `coreFetch`: `401` clears
  in-memory Session and stops polling before login redirect; `503` and network
  failures show retry; `403` and `404` remain product errors.
- The context bar account menu shows email and display label and offers change
  password and logout. Do not add a Settings page.
- Browser Draft keys become
  `thesistrace.research-draft.<researcherId>.<folderId>`. Never read or migrate
  `thesistrace.research-draft.<folderId>`. Logout keeps a Researcher's Drafts;
  account switching cannot reveal them.
- Auth pages follow root `DESIGN.md`, including explicit labels, focus states,
  autocomplete attributes, keyboard operation, and the existing dark dense
  workbench language. They are not marketing pages.

## Database and schema lifecycle

- Use the same PostgreSQL database with independent Core and `auth` schemas.
- Roles are `thesistrace_owner`, `core_runtime`, and `auth_runtime` with no
  cross-schema runtime privileges.
- Pin Better Auth and all Auth dependencies exactly. Generate the complete SQL
  for the selected configuration, review it, and commit a repository-owned Auth
  snapshot and fingerprint.
- Core initialize verifies the complete seven-schema Core contract.
  `auth-initialize` creates only empty Auth scope or verifies its exact
  fingerprint. Runtime services verify but never migrate.
- A plugin or Better Auth version that changes schema requires an explicit new
  hard-cut design. No upgrade, downgrade, compatibility, or fallback path is
  added.
- Development Product State reset drops both Core Product State and Auth state
  while preserving mounted Canonical Data. Test always receives isolated empty
  volumes and accounts.

## Caddy and Compose contract

- Replace `deploy/core/nginx.conf.template` and the Nginx runtime stage with
  `caddy:2-alpine`, a repository Caddyfile, Vite assets under `/srv`, and a
  persistent Production `/data` certificate volume.
- Base Compose includes Auth, Auth initializer, Caddy, Core, Workers,
  PostgreSQL, and RustFS. A Production overlay publishes only 80 and 443.
- Caddy has no readiness dependency on Auth or Core. Static Auth and retry UI
  remains available while either backend is unavailable.
- Core liveness remains dependency-free; Core readiness adds Auth to existing
  PostgreSQL, RustFS, and Dataset checks. Auth readiness includes only Auth
  database/schema/Session storage. Caddy health checks only Caddy/static state.
- `THESISTRACE_PUBLIC_ORIGIN` is exact and environment-owned. Production
  requires HTTPS, a hostname, no path or trailing slash, and no localhost.
  Auth and Core fail startup on a missing or invalid value.
- A repository-external root-owned mode-0600 Production environment file holds
  Auth secret, database passwords, and Resend key. Placeholder values fail
  startup. Hard secret rotation revokes Sessions, Invitations, and reset records.
- Caddy sets the approved CSP and security headers, no-cache for Auth/API and
  SPA fallback, immutable caching for hashed assets, a sanitized trusted client
  IP header, and query/cookie-free request logging.
- Single-node services use one replica and `restart: unless-stopped`. Planned
  maintenance downtime is allowed.

## Audit and cleanup

- Auth audit events cover Invitation issue/revoke/accept, sign-in
  success/failure, reset, password change, Session revoke, deactivate, and
  reactivate.
- Never persist passwords, Cookies, tokens, full email links, request bodies, or
  raw unknown email addresses. Unknown-email correlation uses keyed HMAC.
- Audit retention is 180 days. Terminal Invitation/reset retention is 30 days.
- The single Auth process performs daily expired-record cleanup under a
  PostgreSQL advisory lock. No Cron container or generic scheduler is added.

## Required verification

- Auth unit tests fix time, randomness, UUIDs, and Resend responses.
- Auth PostgreSQL integration tests cover exact schema, role isolation,
  Invitation replay/expiry/reissue/delivery failure, duplicate account
  submission, reset, rolling Session, revocation, and cleanup locks.
- Core PostgreSQL integration tests cover composite ownership keys, same-owner
  constraints, scoped receipts/cursors, and hard-cut initialization.
- Core HTTP tests cover `401`, `503`, exact Origin, JSON writes, own-resource
  success, and cross-Researcher `404` for Folder, Run, Batch, and Track.
- Browser E2E uses two Researchers and a local Resend HTTP fake. It covers every
  Auth flow, bootstrap retry, Draft isolation, polling stop on `401`, retry on
  `503`, and all requests through Caddy.
- Compose and Production Image Smoke assert only Caddy host bindings; 80 to 443
  redirect; 443 application flow; no public internal health; Auth/Core/schema
  startup failure; CSP compatibility for chart/editor/Auth; and secret/token
  absence from logs.
- The public internet and real Resend are forbidden from ordinary tests.
- `mise exec -- pnpm check` must reproduce the default gate locally.
  `mise exec -- pnpm check:release` must qualify final Production Images.

## Delivery order

1. [Auth service and exact schema foundation](issues/01-auth-service-and-schema-foundation.md).
2. [Caddy single-origin Compose topology](issues/02-caddy-single-origin-compose.md).
3. [Invitation, credential, Session, operator, audit, and cleanup lifecycle](issues/03-invitation-credential-and-access-lifecycle.md).
4. [Core Researcher bootstrap, authentication boundary, and Research Ownership hard cut](issues/04-core-research-ownership-hard-cut.md).
5. [Browser Auth flow, shared request client, account menu, and Draft isolation](issues/05-web-authentication-and-account-flow.md).
6. [Cross-stack security and Production Image qualification](issues/06-security-and-production-qualification.md).

Each numbered implementation issue is one acceptance and commit boundary. Do
not keep a ticket partially compatible with the preceding ownerless or Nginx
contract; where the hard cut spans modules, land the complete cut in one ticket.

## Out of scope

- Production backup and restore.
- High availability, multiple replicas, load balancing, or zero-downtime
  deployment.
- Managed Ingress, Cloudflare, Kubernetes, or a hosted control plane.
- Public signup, Web admin, Organizations, RBAC, collaboration, quotas, billing,
  or resource sharing.
- OAuth, MFA, passkeys, magic links, API keys, JWT authorization, or device UI.
- Self-service email, display-label, or account deletion.
- Redis, outbox, generic scheduler, mail-provider abstraction, Vault, or a
  multi-key compatibility ring.
- Migration or adoption of existing ownerless Product State and legacy Drafts.

## Comments

- Design confirmed by the user on 2026-08-27.
