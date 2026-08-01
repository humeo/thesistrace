# Hosted Compose operations

The first hosted deployment is one version-pinned Docker Compose release. It
has one public container, `edge`, and exposes the Web application, the
versioned ThesisTrace API, and the required InsForge Auth routes through the
same Origin. PostgreSQL, InsForge Storage, Temporal, Workers, Prometheus,
Grafana, and OpenTelemetry remain on private Compose networks.

This reference deployment is deliberately one node. It provides coordinated
backup and restore, but it does not provide high availability, automatic
failover, zero-downtime recovery, or an alert-delivery service.

## Start

Docker, Docker Compose, Git, OpenSSL, and `uv` are required. Prepare the pinned
Python environment, then start from the repository root:

```sh
uv sync --frozen
make hosted-up
```

That one command checks out the pinned InsForge v2.2.9 source commit, creates a
mode-600 non-secret environment file and separate mode-600 role-secret files,
builds an immutable content-checked Release Bundle under `.hosted/releases`,
builds the static Web and application images, applies the InsForge, Temporal,
and ThesisTrace migrations, and starts the steady services only after the
release gate succeeds.

The pinned InsForge Deno runtime caches its package dependencies while the
image is built. Its steady container therefore starts on the private control
network without runtime package downloads.

The generated state is under `.hosted/` and is ignored by Git. Production
operators must place it outside the repository and replace
`THESISTRACE_SITE_ADDRESS=https://localhost` in `hosted.env` with the
Cloudflare-proxied hostname before launch:

```sh
export THESISTRACE_HOST_STATE_DIR=/var/lib/thesistrace-hosted
export THESISTRACE_RECOVERY_PASSPHRASE_FILE=/root/thesistrace-recovery-passphrase
make hosted-up
```

The recovery passphrase path must be on separately protected Operator storage;
it must not be inside the repository, the Hosted state directory, an image, or
the off-node backup that contains the encrypted recovery bundle.

## Immutable release and forward deployment

`deploy/hosted/release.json` defines the compatible Web, Caddy, API, Worker,
InsForge, Temporal, product-migration, and configuration components. The
launcher hashes every declared source path and installs one read-only bundle at
`releases/bundles/<bundle-id>/bundle.json`. Custom images first use the
source-content identity as a temporary Docker build tag. After the build, the
final Bundle ID binds both that source identity and every exact local Docker
`sha256` image ID, and each image receives that final Bundle ID tag;
`image-lock.json` records the same immutable association.
Consequently, identical sources that produce different image bytes cannot
produce the same Bundle ID. Each bundle also contains its own read-only Compose,
Caddy, Temporal, telemetry, and dashboard configuration snapshot. A retry
verifies the lock and refuses to rebuild or replace an already locked image.
`current.json` and `previous.json`
retain the active and immediately preceding identities; `candidate.json` names
a staged bundle only until its migrations and release gate succeed. A failed
deployment never changes `current.json`.

Use `hosted-up` only for a clean installation or an ordinary restart of the
same release. Deploy a new release with:

```sh
make hosted-deploy
make hosted-smoke
```

`hosted-deploy` uses the currently active bundle to close heavy-work admission,
pause Temporal Schedules and the outbox relay, and wait up to 15 minutes for
production Activities to drain. It then stops all Workers, installs and builds
the new bundle as the candidate. It executes only the version-pinned InsForge,
Temporal persistence, Temporal Visibility, and ThesisTrace migration jobs while
the prior public containers remain present, then requires the release gate to
succeed. Only after that gate does it recreate every steady configuration
consumer from the candidate snapshot, promote the candidate to `current.json`,
and create the new Workers stopped.
Workers begin polling only after schedules and admission are restored.
Migrations are append-only expand-contract changes; application startup never
applies them implicitly.

If the forward operation fails, the maintenance gate stays closed and Workers
stay stopped. Do not bypass the gate or edit migration history. Correct the
release and retry `make hosted-deploy`, or restore the immediately preceding
compatible bundle with `make hosted-rollback`.

For an explicit maintenance window without a release:

```sh
make hosted-maintenance-enter
# perform the bounded operator action
make hosted-maintenance-exit
```

The enter command reports whether the Activity drain completed. At the
15-minute limit, Worker shutdown leaves interrupted Activities nonterminal for
Temporal redelivery; maintenance never relabels them cancelled, failed, or
resource-exhausted. The database admission gate rejects every new Dataset
Publication request, including Operator requests, while the API gate rejects
new User heavy work, including DailyTrack equivalence requests, and the relay
leaves already queued outbox work undispatched.

`make hosted-rollback` activates only `previous.json`, verifies the retained
image IDs, and recreates databases, Temporal, InsForge, product services, edge,
and observability containers from that bundle's retained configuration snapshot
without running a reverse or forward migration. Named data volumes remain
attached. The command verifies service health before reopening admission. If
the compatibility epoch differs, it exits with restore-required and leaves
maintenance enabled. Use the coordinated restore procedure instead of forcing
that rollback.

## Service secrets and recovery material

The launcher stores PostgreSQL, API, relay, Data Worker, Compute Worker, Health,
ObjectStore, InsForge, Grafana, and Tushare credentials as separate host files
under `$THESISTRACE_HOST_STATE_DIR/secrets`. The directory is mode 700 and each
file is mode 600. Compose mounts only the role-specific files required by each
service. `hosted.env`, Compose configuration, image layers, Release Bundles,
and container configuration contain file paths, never clear secret values.

Every preparation refreshes the encrypted
`recovery/current.recovery` bundle using AES-GCM and the separately held
passphrase. The encrypted bundle is recovery input, not an application secret
mount. Never log its plaintext, include the passphrase beside it, or commit
either artifact. Secret rotation is a coordinated release operation; do not
edit one generated role file while dependent services are running.

### Verification and recovery email

Public registration requires real email verification and password recovery.
Configure InsForge SMTP only through the private control network. Keep the
provider password in a separate mode-600 file outside the repository and
Hosted state. The non-secret configuration file has this exact shape:

```json
{
  "enabled": true,
  "host": "smtp.example.com",
  "port": 587,
  "username": "mailer@example.com",
  "senderEmail": "research@example.com",
  "senderName": "ThesisTrace",
  "minIntervalSeconds": 60
}
```

Apply it without exposing either the InsForge administrator password or SMTP
password in the command line, process environment, image, or output:

```sh
chmod 600 /root/thesistrace-smtp.json /root/thesistrace-smtp-password
make hosted-smtp-configure \
  CONFIG=/root/thesistrace-smtp.json \
  PASSWORD_FILE=/root/thesistrace-smtp-password \
  ACTOR=operator-name
```

InsForge verifies the public SMTP host and credentials before persisting the
encrypted password. The helper prints only the confirmed host, port, sender,
enabled state, and password-presence flag, and appends a sanitized management
audit event for the named Operator. The private test-only OTP seeding
used by release acceptance is unavailable unless
`THESISTRACE_ACCEPTANCE_MODE=1`; it is not an operational substitute for SMTP.

## Coordinated off-node backup and restore

Hosted V2 uses a cold, coordinated recovery set rather than independent live
copies. The launcher enters maintenance, drains Activities, closes the public
Origin, and stops every writer before reading the product PostgreSQL volume,
the Temporal persistence and Visibility volume, immutable objects, InsForge
Storage, the exact Release Bundle state, and the already encrypted secret
recovery bundle. The resulting streaming AES-GCM artifact is published with a
`complete` manifest only after its checksum is durable. This deliberately
accepts a short maintenance window; zero-downtime backup is outside V2.

Mount separately administered off-node storage at an absolute path outside the
repository and `$THESISTRACE_HOST_STATE_DIR`. Keep the backup encryption
passphrase outside both the Hosted node state and backup target. Initialize the
mount once, then create a manual recovery set:

```sh
export THESISTRACE_HOST_STATE_DIR=/var/lib/thesistrace-hosted
export THESISTRACE_BACKUP_PASSPHRASE_FILE=/root/thesistrace-backup-passphrase
export THESISTRACE_RECOVERY_PASSPHRASE_FILE=/root/thesistrace-recovery-passphrase
make hosted-backup-target-init TARGET=/mnt/off-node/thesistrace
make hosted-backup
```

The initialization marker is an explicit mount contract, not proof that a
local directory is remote. The Operator must verify the mounted filesystem and
its independent failure domain. A missing marker, a path under the repository
or Hosted state, a missing physical database, mismatched Release Bundle, or
missing encrypted secret recovery file prevents a successful manifest. The
System Health `backup` check reports the latest attempt and the age of the last
success without changing API readiness. Every scheduled or manual attempt first
expires complete recovery sets older than seven days, including when the new
attempt later fails. Failed or partial temporary files are never advertised as
recoverable. Target initialization, backup attempts, and restore attempts first
create a sanitized host-side audit-outbox record before changing state. An
interrupted operation therefore remains a rejected `OPERATION_INTERRUPTED`
record even when PostgreSQL is unavailable. Completion atomically updates the
same event to its final succeeded or rejected outcome; the operator surface
retries the idempotent database append and removes the outbox file only after
PostgreSQL accepts it. File contents and directory entries are `fsync`ed before
the mutation starts. Target initialization, backup, and restore share one
non-blocking host lock, so the timer and a manual recovery command cannot stop,
read, or replace the same volumes concurrently. A competing command is rejected
as `RECOVERY_OPERATION_BUSY` and leaves its own durable audit-outbox event.

Install the supplied systemd timer on a host whose checkout is
`/opt/thesistrace`, or substitute the actual absolute checkout path in the
service first:

```sh
sudo install -m 0644 deploy/hosted/systemd/thesistrace-backup.service \
  /etc/systemd/system/thesistrace-backup.service
sudo install -m 0644 deploy/hosted/systemd/thesistrace-backup.timer \
  /etc/systemd/system/thesistrace-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now thesistrace-backup.timer
```

The persistent timer runs exactly at 00:00, 06:00, 12:00, and 18:00 so the
maximum scheduled interval is six hours. Inspect
`systemctl status thesistrace-backup.timer`, the latest off-node complete
manifest, and System Health at least once per calendar day.

Restore only the latest complete recovery set unless the incident record
justifies an older set:

```sh
make hosted-restore BACKUP_ID=backup_YYYYMMDDTHHMMSSZ_xxxxxxxxxxxx
```

Restore is destructive to the four authoritative named volumes and clears the
disposable Working Cache. It keeps `edge` stopped, authenticates and checksums
the encrypted set, requires its authenticated backup identity, creation time,
Release Bundle, and optional Workflow probe to match the external manifest,
records that exact authenticated selection, and rejects a selection whose
backup time exceeds the six-hour incident RPO before erasing live volumes. It
restores the separately encrypted role secrets, selects the
recovered Release Bundle, and refuses to continue if its exact locked images
are unavailable. It starts PostgreSQL, Temporal, private Storage, and API
internally; API startup reconciles all pending Resource Tombstones. The restore
gate then requires no Tombstone-owned or unreferenced index rows, no resurrected
private resource, complete Personal Workspace RLS, a valid latest Dataset
Release pointer, and exact size and SHA-256 for every indexed object. Bytes that
exist only in an unexpired backup have no live metadata reference and remain
unreachable. Workers start while maintenance remains active. Internal API
health and the dedicated recovery view must both become `available`; `degraded`
is not sufficient. The recovery view requires the launch-critical System,
Data, and Quantitative checks, while deliberately excluding the still-closed
public Origin, external Tushare and trace export, and historical publication
checks that are not properties of the restored runtime. It also excludes the
new node's local backup-status history: the separate restore gate has already
verified the exact authenticated Recovery Set and its RPO. The public Origin
opens only after those gates and must then pass smoke.

The launch recovery exercise must additionally prove that Temporal persistence
is usable rather than merely present. Start one open probe Workflow, bind its ID
into the recovery-set manifest, and restore that exact recovery set:

```sh
PROBE_ID="recovery-probe-$(date -u +%Y%m%dT%H%M%SZ)"
make hosted-recovery-probe-start PROBE_ID="$PROBE_ID"
THESISTRACE_RECOVERY_PROBE_ID="$PROBE_ID" make hosted-backup
make hosted-restore BACKUP_ID=backup_YYYYMMDDTHHMMSSZ_xxxxxxxxxxxx
```

During restore, the probe ID is read only from the authenticated Recovery Set
selection. The release-bundled, operator-only recovery-probe service
requires the recovered Workflow to still be running, signals it, and waits for
`continued_after_restore`. It has no host source mount, secrets, or access
beyond the internal execution network. Failure keeps the Origin closed and
prevents successful recovery evidence.

For every launch recovery exercise, retain evidence with the selected backup
time, incident detection time, restore start/end time, restored Dataset
Release, object count, recovered Workflow ID, and public-Origin smoke result.
Acceptance is a latest complete backup no older than six hours, daily detection
no later than 24 hours, completed recovery within eight hours, successful
Workflow continuation, and successful public smoke. Backup existence alone is
not recovery evidence.

## Cloudflare and origin edge

Production uses one proxied Cloudflare DNS record. Before the first public
launch, the Operator must complete all of the following as one change:

1. Install a valid public or Cloudflare Origin CA certificate for the proxied
   hostname as `.hosted/origin-tls/cert.pem` and its key as
   `.hosted/origin-tls/key.pem`. Remove the local-only
   `THESISTRACE_ORIGIN_TLS=internal` override so Compose uses those two files.
2. Replace the local-only
   `THESISTRACE_EDGE_TRUSTED_PROXIES=private_ranges` override with the exact
   Cloudflare IPv4 and IPv6 ranges declared by
   `deploy/hosted/cloudflare-proxy-ranges.txt`. The launcher refuses a public
   hostname unless the configured set is exactly equal to that allowlist;
   partial and overbroad sets are rejected. Compare the canonical file with
   `https://www.cloudflare.com/ips-v4/` and
   `https://www.cloudflare.com/ips-v6/` immediately before every edge release.
3. Set the Cloudflare zone SSL/TLS mode to **Full (strict)**. A Flexible or
   non-strict mode is not an accepted deployment.
4. Apply `deploy/hosted/cloudflare-origin-firewall.nft` on the origin host only
   after verifying it preserves the host's separate SSH/management policy. The
   dedicated table accepts ports 80 and 443 from the recorded Cloudflare ranges
   and drops every other Web source on both the host `input` path and Docker's
   DNAT `forward` path; it does not change non-Web ports. Docker-published ports
   are forwarded before ordinary host-input filtering, so both hooks are
   required. Validate and exercise this rule on the Linux origin host; Docker
   Desktop is not equivalent evidence for the host firewall.
5. Create Cloudflare WAF rate-limiting rules from
   `deploy/hosted/cloudflare-waf-rate-limits.json`. The paths are intentionally
   limited by client IP at Cloudflare because registration, login, verification,
   and recovery occur before ThesisTrace has an authenticated User.

Caddy independently rejects an immediate peer outside the same Cloudflare
ranges, enables right-to-left strict proxy parsing, accepts client identity only
from `CF-Connecting-IP`, and removes that header before proxying internally.
This is defense in depth; it does not replace the host firewall. The production
Web build and `/api/v1/*` are served through Caddy, while only the explicitly
listed InsForge Auth routes are proxied. There is no edge route for InsForge
Storage, object manifests, signed URLs, administration, PostgreSQL, Temporal,
Workers, Prometheus, Grafana, or OpenTelemetry.

The API separately enforces a 60-second authenticated window. Defaults are 120
requests per verified User, 240 per Personal Workspace, and 30 state-changing
requests per User and Workspace. A rejection is `429 REQUEST_RATE_LIMITED` with
`Retry-After`; it is not `QUOTA_EXCEEDED` or `DISK_PRESSURE`.

After launch, verify the public hostname returns a Cloudflare `CF-Ray` response
header and the product smoke passes. From a host outside Cloudflare, a direct
`curl --resolve <hostname>:443:<origin-ip> https://<hostname>/` must fail at the
firewall or return Caddy `403`. The following public paths must return `404` and
must never disclose an object key, SHA-256 manifest identity, filesystem path,
bucket operation, or signed URL:

```text
/api/storage/*
/api/v1/objects/*
/api/auth/admin/*
```

The launcher deliberately writes `internal` and `private_ranges` overrides for
the localhost development stack. Those values are not production defaults and
must never be carried to a public hostname.

## Source authorization declaration

Possessing a Tushare token does not open hosted live Dataset Publication.
After independently confirming that the deployment has the required upstream
rights, the trusted Operator records the fixed policy declaration through the
versioned CLI running inside the private application network:

```sh
make hosted-operator ARGS="source-authorization record \
  --actor operator-1 \
  --scope hosted-shared-dataset-releases"
make hosted-operator ARGS="source-authorization inspect"
```

The declaration and its sanitized audit event contain the actor, time, fixed
scope, and generated audit identity. They contain no Tushare token or other
credential. Recording the declaration enables ThesisTrace's policy gate only;
the command does not validate, negotiate, or interpret upstream legal rights.

## Invitation, publication, and quota operations

Normal invitation issuance remains closed until the current Release Bundle has
both a passing Capacity Qualification and a passing final Launch
Qualification. A qualification for an older Release Bundle never opens a new
release. After launch, issue, inspect, and revoke an invitation through the
private Operator boundary:

```sh
make hosted-operator ARGS="invitation issue \
  --actor operator-1 \
  --email researcher@example.com \
  --expires-at 2026-08-08T00:00:00Z"
make hosted-operator ARGS="invitation inspect --invitation-id invite_xxx"
make hosted-operator ARGS="invitation revoke \
  --actor operator-1 --invitation-id invite_xxx"
```

Use one unique idempotency key for each intended Dataset Publication. The
bootstrap imports the latest three-year research window through Tushare; the
increment publishes the requested post-close date. Both are queued on the
independent Data Worker and preserve the previous authoritative Release until
the new Release commits completely:

```sh
make hosted-operator ARGS="dataset-publication request \
  --actor operator-1 --kind live_bootstrap --as-of 2026-08-01 \
  --idempotency-key live-bootstrap-20260801"
make hosted-operator ARGS="dataset-publication request \
  --actor operator-1 --kind live_increment --as-of 2026-08-04 \
  --idempotency-key live-increment-20260804"
```

Confirm completion in Data Health and through the bounded Dataset Release
product view. Do not retry with a new idempotency key while the original
request is nonterminal.

Inspect the default or effective Workspace quota before changing it. An
override changes only the provided dimensions and is recorded in the
management audit ledger:

```sh
make hosted-operator ARGS="quota inspect --workspace-id workspace_xxx"
make hosted-operator ARGS="quota override \
  --actor operator-1 --workspace-id workspace_xxx \
  --max-active-daily-tracks 10 \
  --max-nonterminal-user-compute-jobs 2 \
  --max-private-storage-bytes 1073741824"
```

## Final release qualification

Every Release Bundle is closed to new invitations until its own evidence is
recorded. First run the maximum-load qualification on a separate, otherwise
identical qualification stack so it does not contaminate the clean Public
Origin acceptance stack:

```sh
.venv/bin/python scripts/hosted/capacity_qualification.py \
  --compose-file deploy/hosted/compose.yaml \
  --project thesistrace-hosted-qualification \
  --release-bundle-id "$RELEASE_BUNDLE_ID" \
  --output "$CAPACITY_EVIDENCE"
make hosted-operator ARGS="capacity-qualification record \
  --actor release-operator \
  --release-bundle-id $RELEASE_BUNDLE_ID \
  --evidence $CAPACITY_EVIDENCE"
```

Complete the coordinated backup and full restore exercise for the same exact
Release Bundle as described above. Its latest generated
`recovery-exercises/*.json` is the recovery evidence. The final Public-Origin
stack must start with no Users, Personal Workspaces, invitations, Launch
Qualifications, Dataset Releases, Research Definitions, ResearchRuns, or
DailyTracks. It may contain the source declaration and the current Release's
Capacity Qualification. Initialize its off-node backup target before running
acceptance because the black-box flow takes a coordinated backup and requires
all three Health planes to become available.

`THESISTRACE_TEST_DATABASE_URL` must point to a separate disposable PostgreSQL
database prepared for tests. It must never point to the Public-Origin or
production database. From a clean Git checkout, run:

```sh
export THESISTRACE_TEST_DATABASE_URL='postgresql://.../thesistrace_acceptance_test'
make hosted-release-acceptance \
  RELEASE_BUNDLE_ID="$RELEASE_BUNDLE_ID" \
  CAPACITY_EVIDENCE="$CAPACITY_EVIDENCE" \
  RECOVERY_EVIDENCE="$RECOVERY_EVIDENCE" \
  OUTPUT="$LAUNCH_EVIDENCE"
```

The command runs the Public-Origin identity and product chain, PostgreSQL RLS
for every Workspace table and production role, real Temporal dispatch,
resource-exhaustion and interruption matrices, storage and direct-Origin
security, full backend/frontend/browser suites, and all three Health planes.
The interruption matrix sends concurrent idempotent API requests across an
API outage, kills a claimed Compute Activity and a running Data publication,
and requires second Attempts without duplicate results. It then enters
maintenance, sends `SIGKILL` to every Compose service to model loss of the
controlled single node, starts from persistent host state, and proves that the
maintenance fence, result truth, Dataset Releases, and object index survive
before the Operator exits maintenance.

It records the immutable Launch Qualification only if every check passes, then
proves normal invitation issuance opens. A failed or stale evidence artifact
leaves launch closed. The release runner signs the complete evidence with the
root-only `launch_qualification_key`; the general Operator CLI exposes inspect
but no record command. Never insert or edit a qualification manually. The
single SSH Operator remains the deployment trust root: Docker or PostgreSQL
superuser access can subvert any in-process gate and is outside the Hosted V2
adversary boundary.

## Verify

The black-box smoke uses only `THESISTRACE_HOSTED_ORIGIN`; it does not address
any private service:

```sh
make hosted-smoke
```

For the local internal Caddy certificate,
`THESISTRACE_SMOKE_INSECURE_TLS=1` is generated. Never enable that setting for
the Cloudflare production Origin.

The Compute dispatch acceptance uses the private Temporal Service and the
production Task Queue/poller contract:

```sh
make hosted-dispatch-probe
```

The probe submits controlled P1 and P3 backlogs twice. It requires the same
ThesisTrace-controlled dispatch decisions on both runs: for each controlled
slot-availability batch, it compares the exact slot-tier allocation. Temporal
documents fairness as a
roughly proportional mechanism with small deviations, so exact cross-Workspace
interleaving is intentionally not treated as a deterministic decision. Each
run independently checks the Workspace dispatch counts against the tighter
equal-weight bound and enforces the FIFO sequence contract. The probe also
requires no more than four simultaneous Compute
Activities, one independent Data Activity alongside those four, P3 progress
under sustained mixed backlog, equal-weight Workspace fairness with FIFO
inside each tier, no preemption, and four-slot borrowing when either tier is
empty. One Compute container serially polls the lightweight Workflow queue so
the relay's durable FIFO order is preserved before Activities enter their P1
or P3 queue; all four containers independently poll one heavy Activity slot.
Hosted Temporal uses one read/write partition for these queues because Temporal
fairness and FIFO are defined per Task Queue partition.

## Storage admission and disk pressure

`object-store` measures projected usage against
`THESISTRACE_PERSISTENT_DISK_BYTES`, which defaults to the configured
200-GB persistent SSD (`200000000000` bytes). The thresholds are configured by
`THESISTRACE_DISK_WARNING_PERCENT`,
`THESISTRACE_PRIVATE_WRITE_REJECTION_PERCENT`, and
`THESISTRACE_ALL_WRITE_REJECTION_PERCENT`, defaulting to 70%, 80%, and 90%.
The warning threshold logs `persistent disk warning threshold reached`; the
private rejection threshold blocks new Personal Workspace payload growth while
the Data Worker may still publish a Dataset Release; the all-write threshold
blocks all payload growth, including Dataset Publication. A rejected
ObjectStore request returns HTTP 507 with
`reason_code=DISK_PRESSURE` and the applicable percentage limit.

PostgreSQL indexes the exact compressed bytes of immutable content objects and
named manifests referenced by each Personal Workspace. The same object is
charged once per Personal Workspace even when several private resources refer
to it. Platform-owned Dataset Release references are indexed separately and
never consume `max_private_storage_bytes`. A private publication that would
exceed the effective quota fails with `reason_code=QUOTA_EXCEEDED`,
`dimension=max_private_storage_bytes`, and the byte limit.

Result Bundle, Tracking Checkpoint, and Dataset Release publication stage their
objects first, repeat disk and quota admission immediately before the database
success transition, and commit references with the authoritative manifest
state in one PostgreSQL transaction. On rejection, recovery removes the
unreferenced stage while the previous Result, Tracking Head, or Dataset Release
remains readable. Reads, cancellation, stage recovery, deletion, and cleanup
do not pass through payload-growth admission and remain available at every
pressure level.

## Stop and restart

```sh
make hosted-down
make hosted-up
```

`hosted-down` intentionally omits `--volumes`. Product PostgreSQL,
Temporal PostgreSQL, InsForge Storage, the immutable-object store, Caddy,
Prometheus, and Grafana use named volumes and survive this stop/start cycle.
Only an explicit, separately reviewed `docker compose down --volumes` removes
them.

## Migration failure

Inject a failure only on a recovery exercise:

```sh
THESISTRACE_INJECT_MIGRATION_FAILURE=1 make hosted-deploy
```

`thesistrace-migrations` exits non-zero and `release-gate` never completes. A
clean installation remains closed. During a forward deployment, the prior
public service remains authoritative while heavy-work admission and Workers
remain paused. Remove the injected environment value and retry the deployment,
or run the compatible rollback. Already-applied migration checksums are
verified and safe migrations resume idempotently.
