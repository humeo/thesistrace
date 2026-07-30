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

## Verify

The black-box smoke uses only `THESISTRACE_HOSTED_ORIGIN`; it does not address
any private service:

```sh
make hosted-smoke
```

For the local internal Caddy certificate,
`THESISTRACE_SMOKE_INSECURE_TLS=1` is generated. Never enable that setting for
the Cloudflare production Origin.

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
