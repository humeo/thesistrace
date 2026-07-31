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
