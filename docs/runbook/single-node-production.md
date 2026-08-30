# Single-node Production runtime

ThesisTrace Production is one Docker Compose project on one host. Caddy is the
only published service on ports 80 and 443. Auth, Core, PostgreSQL, RustFS, and
the Research, Batch Research, Daily Track, and Data Operator Workers stay on the
private Compose network. This runtime makes no high-availability or zero-downtime
claim.

## External environment contract

Production configuration lives in one absolute file outside the repository.
The file must be a regular, non-symlink file owned by root with mode `0600`.
Create and edit it as root; do not copy it into the checkout:

```sh
sudo install -d -o root -m 0700 /etc/thesistrace
sudo install -o root -m 0600 /dev/null /etc/thesistrace/production.env
sudoedit /etc/thesistrace/production.env
```

The file uses one unquoted `KEY=value` per line. Replace every placeholder below
before validation:

```dotenv
THESISTRACE_ENVIRONMENT=production
THESISTRACE_PUBLIC_ORIGIN=https://<production-hostname>
THESISTRACE_RESEND_API_URL=https://api.resend.com
THESISTRACE_OWNER_DATABASE_PASSWORD=<unique-url-safe-24-to-128-characters>
THESISTRACE_CORE_DATABASE_PASSWORD=<unique-url-safe-24-to-128-characters>
THESISTRACE_AUTH_DATABASE_PASSWORD=<unique-url-safe-24-to-128-characters>
BETTER_AUTH_SECRET=<64-lowercase-hex-characters>
RESEND_API_KEY=<production-resend-api-key>
RESEND_FROM_EMAIL=<verified-sender-email-or-display-name>
THESISTRACE_TUSHARE_TOKEN=<production-tushare-token>
THESISTRACE_AUTH_IMAGE=ghcr.io/<owner>/<image>:<fixed-version>
```

The three database passwords must differ. `openssl rand -hex 24` produces one
accepted password shape; run it independently for each role. `openssl rand
-hex 32` produces the Auth secret. The public origin must use the default HTTPS
port, contain only a hostname, and cannot use localhost or a reserved
`.test`, `.example`, or `.invalid` name. The Auth image must use an explicit
non-placeholder tag or a `sha256` digest. Production accepts only the public
Resend API URL; the Test fake is rejected before Compose starts.

Validate the complete environment and resolved Compose model without starting
services:

```sh
sudo env \
  THESISTRACE_PRODUCTION_ENV_FILE=/etc/thesistrace/production.env \
  ./scripts/production-runtime validate
```

Validation emits no output on success. A failure emits one code without the
rejected value and exits non-zero.

## Start, inspect, and stop

Ensure the Production hostname resolves to the host and inbound 80/443 reach
Caddy. Then build the repository-owned Core and Web images, start the pinned
Auth image and infrastructure, run the exact-schema initializers, and wait for
service health:

```sh
sudo env \
  THESISTRACE_PRODUCTION_ENV_FILE=/etc/thesistrace/production.env \
  ./scripts/production-runtime up
```

Caddy obtains and persists its automatic HTTPS state under the Production
`caddy-data` volume. It redirects HTTP to HTTPS, adds the one-year HSTS header,
and serves the static login/unavailable UI even when Auth or Core is down.
Public `/health/*` and `/internal/*` paths return `404`; container health is
inspected through the private topology:

```sh
sudo env \
  THESISTRACE_PRODUCTION_ENV_FILE=/etc/thesistrace/production.env \
  ./scripts/production-runtime status
```

Stop and remove containers and the project network while retaining named data
volumes with:

```sh
sudo env \
  THESISTRACE_PRODUCTION_ENV_FILE=/etc/thesistrace/production.env \
  ./scripts/production-runtime down
```

All long-running single-node services use one replica and
`restart: unless-stopped`. Docker's bounded `json-file` logs are diagnostic
evidence. Caddy, Hono, and FastAPI record only allowlisted completion context;
query strings, Cookies, bodies, credentials, tokens, raw unknown emails,
Formulae, object keys, and manifests are not log fields.

## Operator assignment and Researcher access

There is no public signup. Routine administration is available in the
same-origin Operator Console only after a deployment administrator assigns the
singleton capability. There is exactly one Operator, and that account remains a
Researcher account for research work. Assignment and transfer remain private
Production commands and are never Console operations.

Run Auth Operator commands inside the private Production topology after
`production-runtime up`. This helper function keeps the canonical project,
external environment, and overlays together:

```sh
production_env=/etc/thesistrace/production.env
production_compose() (
  unset \
    THESISTRACE_ENVIRONMENT THESISTRACE_PUBLIC_ORIGIN \
    THESISTRACE_RESEND_API_URL THESISTRACE_OWNER_DATABASE_PASSWORD \
    THESISTRACE_CORE_DATABASE_PASSWORD THESISTRACE_AUTH_DATABASE_PASSWORD \
    BETTER_AUTH_SECRET RESEND_API_KEY RESEND_FROM_EMAIL \
    THESISTRACE_TUSHARE_TOKEN \
    THESISTRACE_AUTH_IMAGE
  sudo docker compose \
    --project-name thesistrace \
    --env-file "$production_env" \
    --file deploy/core/compose.yaml \
    --file deploy/core/compose.production.yaml \
    "$@"
)
```

Assign the first active Researcher, or atomically transfer the capability to a
different active Researcher. Transfer revokes every Login Session of the former
Operator; the new Operator must already have a Login Session:

```sh
production_compose run --rm --no-deps -T auth \
  node dist/operator.js assign-operator --email operator@example.com

production_compose run --rm --no-deps -T auth \
  node dist/operator.js transfer-operator --email next-operator@example.com
```

After assignment, `/operator/researchers` lists Researchers and Invitations,
issues or reissues Invitations, and revokes all Login Sessions of another
Researcher. `/operator/data` submits Market, Financial, and Industry Refreshes,
shows the current Dataset Head and readiness, and exposes safe operation status,
Cancel for queued work, and immutable Retry. Researcher deactivation is not a
Console operation. The Console cannot assign or transfer the Operator, revoke
its own Sessions, browse raw storage, run Garbage Collection, or perform a
combined Refresh.

Every Console mutation asks for the current password. Auth exchanges it for one
60-second, single-use Proof bound to that Session and exact request; Core never
receives the password. An ordinary Researcher receives an empty `404` for the
Console and every Operator API.

Issue or replace a 48-hour invitation. The command returns the Invitation ID
but never its token or email link; Resend must accept the message before the
Invitation becomes usable:

```sh
production_compose run --rm --no-deps -T auth \
  node dist/operator.js invite --email researcher@example.com

production_compose run --rm --no-deps -T auth \
  node dist/operator.js reissue --email researcher@example.com
```

Revoke every Login Session, reactivate access without creating a Session, or
correct the initial display label:

```sh
production_compose run --rm --no-deps -T auth \
  node dist/operator.js revoke-sessions --email researcher@example.com

production_compose run --rm --no-deps -T auth \
  node dist/operator.js reactivate --email researcher@example.com

production_compose run --rm --no-deps -T auth \
  node dist/operator.js correct-label --email researcher@example.com \
  --label "Research label"
```

Deactivation uses the deployment wrapper rather than a direct Auth mutation.
It validates Production configuration, resolves the Researcher through Auth,
asks Core for the active DailyTrack count, then deactivates through Auth. It
reports the count but never Stops a Track:

```sh
sudo env \
  THESISTRACE_PRODUCTION_ENV_FILE=/etc/thesistrace/production.env \
  ./scripts/deactivate-researcher --email researcher@example.com
```

Every access operation is idempotent. Deactivation revokes Sessions,
Invitations, and reset records but does not cancel admitted ResearchRuns or
Research Batches and does not stop DailyTracks. Reactivation restores only the
active flag; the Researcher must log in again.

## Auth secret rotation

The Auth schema stores a fingerprint of the one current `BETTER_AUTH_SECRET`.
To rotate it, replace the value in the external environment file and run
`production-runtime up` again. Auth startup atomically revokes every Session,
Invitation, and password-reset record before accepting the new fingerprint.
There is no old-key ring, compatibility window, or fallback secret.

## Data Operator Worker and publication status

The topology runs one always-running, single-slot Data Operator Worker. Market,
Financial, and Industry submissions from the Console or private CLI enter the
same global FIFO, and no production `--once`, per-kind Worker, or synchronous
Refresh execution path exists. HTTP returns after PostgreSQL durably records an
operation: accepted is not published. The Dataset Head advances only after the
Worker completes validation and publication; no-change and degraded Financial
success are explicit terminal outcomes.

An unavailable Worker does not make healthy Core reject a durable submission.
The receipt remains queued and the Console warns that execution cannot start.
Expired claims are reconciled on the same operation for at most three attempts;
an exhausted operation fails with `RETRY_EXHAUSTED`. Cancel applies only before
a claim. Retry copies a failed or cancelled target to a new immutable receipt.

`THESISTRACE_TUSHARE_TOKEN` is the Worker-only Tushare Secret. Compose does not
place it in Auth, Core API, Web, PostgreSQL, RustFS, browser state, responses, or
logs. A missing, placeholder, or test-shaped value makes only the Worker fail
startup; Auth, Core, Web, and durable submission remain healthy. Inspect the
Worker and queued operations with:

```sh
production_compose ps data-operator-worker
production_compose logs --no-color --tail 200 data-operator-worker
```

Logs contain bounded operation and request identifiers, not source responses,
proofs, credentials, object paths, or manifests. See the
[Data Operator runbook](data-operator.md) for private inspection and recovery
commands.

## Release qualification boundary

Before changing a Production host, run the repository release gate from the
exact revision being deployed:

```sh
mise exec -- pnpm check:release
```

The gate exercises real PostgreSQL/RustFS integration, two-Researcher browser
acceptance through Caddy, Core/Auth/Caddy Production images, internal-CA HTTPS,
security headers, failure independence, secret-log scans, and both long
Research Kinds. It does not access the public Resend service and does not prove
the health of an external host.

Each isolated run writes `.local/test-runs/<run-id>/run.txt` with the Git
revision, image phase statuses, and Compose project. `evidence/` contains image
IDs, bounded operation and request IDs, responses, service logs, and container
inspection. Browser failures retain sanitized artifacts under
`evidence/playwright-results/`, including screenshots, trace, and video; the
HTML report is under `evidence/playwright-report/`. Ordinary qualification uses
the Resend fake and versioned Tushare replay and makes no public-internet or live
Tushare request. Live source verification is a separate explicit gate.

Production backup/restore, multiple replicas, managed ingress, and a managed
secret store are outside this single-node runtime contract.
