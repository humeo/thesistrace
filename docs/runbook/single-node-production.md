# Single-node Production runtime

ThesisTrace Production is one Docker Compose project on one host. Caddy is the
only published service on ports 80 and 443. Auth, the Agent Host, Core,
PostgreSQL, RustFS, and the Research, Batch Research, Daily Track, and Data
Operator Workers stay on the private Compose network. This runtime makes no
high-availability or zero-downtime claim.

## External environment contract

Production secrets and deployment settings live in one absolute file outside the repository.
The file must be a regular, non-symlink file owned by root with mode `0600`.
Model definitions are maintained in [`apps/agent/config/model-registry.json`](../../apps/agent/config/model-registry.json).
The Production launcher loads that file on each invocation and rejects inline
`THESISTRACE_AGENT_MODEL_REGISTRY` entries in the external environment file.
Apply model edits with the Production `up` command, then reload Chat.
Create and edit the external environment file as root; do not copy it into the checkout:

```sh
sudo install -d -o root -m 0700 /etc/thesistrace
sudo install -o root -m 0600 /dev/null /etc/thesistrace/production.env
sudoedit /etc/thesistrace/production.env
```

Use the complete [configuration template](../../.env.example), including its MCP
policy and identity fields, and replace the Development values with Production
values. The file uses one unquoted, literal `KEY=value` per line; shell expansion
and `$`/`#` characters or inline comments are rejected. Replace every placeholder below
before validation:

```dotenv
THESISTRACE_ENVIRONMENT=production
THESISTRACE_PUBLIC_ORIGIN=https://<production-hostname>
THESISTRACE_RESEND_API_URL=https://api.resend.com
THESISTRACE_AGENT_OPENAI_BASE_URL=https://api.openai.com/v1
THESISTRACE_S3_ACCESS_KEY_ID=<unique-storage-access-key>
THESISTRACE_S3_SECRET_ACCESS_KEY=<unique-storage-secret-key>
THESISTRACE_OWNER_DATABASE_PASSWORD=<unique-url-safe-24-to-128-characters>
THESISTRACE_CORE_DATABASE_PASSWORD=<unique-url-safe-24-to-128-characters>
THESISTRACE_AUTH_DATABASE_PASSWORD=<unique-url-safe-24-to-128-characters>
THESISTRACE_AGENT_DATABASE_PASSWORD=<unique-url-safe-24-to-128-characters>
BETTER_AUTH_SECRET=<64-lowercase-hex-characters>
RESEND_API_KEY=<production-resend-api-key>
RESEND_FROM_EMAIL=<verified-sender-email-or-display-name>
THESISTRACE_TUSHARE_TOKEN=<production-tushare-token>
THESISTRACE_AUTH_IMAGE=ghcr.io/<owner>/<image>:<fixed-version>
THESISTRACE_AGENT_IMAGE=ghcr.io/<owner>/<image>:<fixed-version>
THESISTRACE_AGENT_BUILD_REVISION=<release-revision>
THESISTRACE_AGENT_OPENAI_API_KEY=<production-provider-api-key>
```

Object-store keys are supplied by this file too; no storage credentials are
hard-coded in the shared topology. Use distinct generated values of 16–128
URL-safe characters. The four database passwords must differ. `openssl rand -hex 24` produces one
accepted password shape; run it independently for each role. `openssl rand
-hex 32` produces the Auth secret. The public origin must use the default HTTPS
port, contain only a hostname, and cannot use localhost or a reserved
`.test`, `.example`, or `.invalid` name. Auth and Agent images must use explicit
non-placeholder tags or `sha256` digests. The Agent registry is loaded once at
startup; every enabled model names its provider adapter, provider model ID,
allowed reasoning efforts, and the environment key holding its credential.
At least one registered provider credential must be present. Production accepts
only the public Resend API URL; the Test fake is rejected before Compose starts.

Validate the complete environment and resolved Compose model without starting
services:

```sh
sudo env \
  THESISTRACE_ENV_FILE=/etc/thesistrace/production.env \
  pnpm prod validate
```

The validator emits no payload on success. A failure emits a code and field names without the
rejected value and exits non-zero.

Status, logs and down need Docker access but no environment file or provider
credentials. They use exact project labels; down keeps all named data volumes.

## Start, inspect, and stop

Ensure the Production hostname resolves to the host and inbound 80/443 reach
Caddy. Then build the repository-owned Core and Web images, start the pinned
Auth image and infrastructure, run the exact-schema initializers, and wait for
service health:

```sh
sudo env \
  THESISTRACE_ENV_FILE=/etc/thesistrace/production.env \
  pnpm prod up
```

Caddy obtains and persists its automatic HTTPS state under the Production
`caddy-data` volume. It redirects HTTP to HTTPS, adds the one-year HSTS header,
and serves the static login/unavailable UI even when Auth or Core is down.
Public `/health/*` and `/internal/*` paths return `404`; container health is
inspected through the private topology:

```sh
sudo env \
  THESISTRACE_ENV_FILE=/etc/thesistrace/production.env \
  pnpm prod status
```

Stop and remove containers and the project network while retaining named data
volumes with:

```sh
sudo env \
  THESISTRACE_ENV_FILE=/etc/thesistrace/production.env \
  pnpm prod down
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

Run private commands through `pnpm prod run` after `pnpm prod up`. It validates
and loads the same external configuration and uses the canonical project.
The host needs Node 24 and pnpm, pinned in `.mise.toml`, as well as Docker Compose.

Assign the first active Researcher, or atomically transfer the capability to a
different active Researcher. Transfer revokes every Login Session of the former
Operator; the new Operator must already have a Login Session:

```sh
sudo env THESISTRACE_ENV_FILE=/etc/thesistrace/production.env pnpm prod run auth \
  node dist/operator.js assign-operator --email operator@example.com

sudo env THESISTRACE_ENV_FILE=/etc/thesistrace/production.env pnpm prod run auth \
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
sudo env THESISTRACE_ENV_FILE=/etc/thesistrace/production.env pnpm prod run auth \
  node dist/operator.js invite --email researcher@example.com

sudo env THESISTRACE_ENV_FILE=/etc/thesistrace/production.env pnpm prod run auth \
  node dist/operator.js reissue --email researcher@example.com
```

Revoke every Login Session, reactivate access without creating a Session, or
correct the initial display label:

```sh
sudo env THESISTRACE_ENV_FILE=/etc/thesistrace/production.env pnpm prod run auth \
  node dist/operator.js revoke-sessions --email researcher@example.com

sudo env THESISTRACE_ENV_FILE=/etc/thesistrace/production.env pnpm prod run auth \
  node dist/operator.js reactivate --email researcher@example.com

sudo env THESISTRACE_ENV_FILE=/etc/thesistrace/production.env pnpm prod run auth \
  node dist/operator.js correct-label --email researcher@example.com \
  --label "Research label"
```

Deactivation uses the deployment wrapper rather than a direct Auth mutation.
It validates Production configuration, resolves the Researcher through Auth,
asks Core for the active DailyTrack count, then deactivates through Auth. It
reports the count but never Stops a Track:

```sh
sudo env \
  THESISTRACE_ENV_FILE=/etc/thesistrace/production.env \
  node tooling/dev/deactivate-researcher.mjs --email researcher@example.com
```

Every access operation is idempotent. Deactivation revokes Sessions,
Invitations, and reset records but does not cancel admitted ResearchRuns or
Research Batches and does not stop DailyTracks. Reactivation restores only the
active flag; the Researcher must log in again.

## Auth secret rotation

The Auth schema stores a fingerprint of the one current `BETTER_AUTH_SECRET`.
To rotate it, replace the value in the external environment file and run
`pnpm prod up` again. Auth startup atomically revokes every Session,
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
sudo pnpm prod status
sudo pnpm prod logs data-operator-worker
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
