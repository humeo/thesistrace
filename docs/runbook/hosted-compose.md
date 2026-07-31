# Hosted Compose operations

The first hosted deployment is one version-pinned Docker Compose release. It
has one public container, `edge`, and exposes the Web application, the
versioned ThesisTrace API, and the required InsForge Auth routes through the
same Origin. PostgreSQL, InsForge Storage, Temporal, Workers, Prometheus,
Grafana, and OpenTelemetry remain on private Compose networks.

## Start

Docker, Docker Compose, Git, and OpenSSL are required. From the repository root:

```sh
make hosted-up
```

That one command checks out the pinned InsForge v2.2.9 source commit, creates a
mode-600 local environment file with generated secrets on first use, builds
the static Web and application images, applies the InsForge, Temporal, and
ThesisTrace migrations, and starts the steady services only after the release
gate succeeds.

The pinned InsForge Deno runtime caches its package dependencies while the
image is built. Its steady container therefore starts on the private control
network without runtime package downloads.

The generated state is under `.hosted/` and is ignored by Git. Production
operators must replace `THESISTRACE_SITE_ADDRESS=https://localhost` in
`.hosted/hosted.env` with the Cloudflare-proxied hostname before launch.

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

Set `THESISTRACE_INJECT_MIGRATION_FAILURE=1` in `.hosted/hosted.env` to exercise
the failure path. `thesistrace-migrations` exits non-zero, `release-gate` never
completes, and Compose cannot start the API, Caddy, or Workers. Remove the
setting and rerun `make hosted-up`; already-applied migration checksums are
verified and safe migrations resume idempotently.
