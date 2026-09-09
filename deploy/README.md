# Production deployment

Run repository commands with the versions in `.mise.toml`. Verification selection and
entrypoints are documented in [AGENTS.md](../AGENTS.md#testing).

Production reads one authoritative, root-owned, mode-600 configuration file outside
this checkout. It does not merge the development `.env` with a production file.
Initialize a new deployment on the server as root:

```sh
install -d -m 700 /etc/thesistrace /etc/thesistrace/caddy
THESISTRACE_ENV_FILE=/etc/thesistrace/production.env pnpm config:init --production
```

Fill the public HTTPS origin, immutable release image tags/build revision, external
service credentials, verified sender and model HTTPS base URL in that file. The
initializer generates independent database, storage and signing secrets, refuses to
overwrite an existing file, and leaves deployment-specific inputs empty. Preserve
these secrets on subsequent deployments. Never commit or bake this file into images.

```sh
THESISTRACE_ENV_FILE=/etc/thesistrace/production.env pnpm prod validate
THESISTRACE_ENV_FILE=/etc/thesistrace/production.env pnpm prod up
pnpm prod status
```

The production Compose overlay fixes three ordinary Research Workers and two
Batch Research Workers for the 6-vCPU, 12-GB server. Each worker retains the
configured CPU, memory, and execution limits; development keeps one of each.

The production web container publishes ports 80 and 443 and persists Caddy's public
origin certificates in `caddy-data`. With Cloudflare DNS proxying enabled, use
Full (strict) after the origin certificate is issued. Only Cloudflare's documented
IPv4/IPv6 ranges are trusted to supply `CF-Connecting-IP`; direct requests cannot
replace their source address with that header. Update the range list from
[Cloudflare](https://www.cloudflare.com/ips/) when Cloudflare changes it.

Additional operator-owned Caddy sites can be placed in `/etc/thesistrace/caddy/*.caddy`.
This directory is mounted read-only; keep it root-owned. For this Contabo deployment,
`api.thesistrace.com` routes only model API paths to an independently deployed
CLIProxyAPI container on the `thesistrace_default` network. The gateway has no
published ports; its API key and model account files live outside the checkout.
Stop the gateway before `pnpm prod down`, because it also uses that network. Restart
it after the product network is recreated. Normal product container updates preserve
the network.

Paid model calls reserve the configured context-window input ceiling plus the
requested output allowance before dispatch. They settle against the provider's
actual token usage, including configured cache prices. No token-count endpoint is
required: gateway estimates can omit provider-added input. The configured model
capacity must bound provider usage. A small remaining daily budget can reject a
call whose eventual cost would be lower; interrupted calls without final usage
retain their reservation. This deployment keeps the GPT-5.6 Luna token prices in
`apps/agent/config/model-registry.json`; it does not treat subscription calls as free.

For an existing local research dataset, copy a consistent Canonical and benchmark
snapshot into the server's new data volumes before starting data updates. Verify the
archive checksum and mounted Dataset Head on the destination. Initialize the server's
product databases independently; research data transfer does not require copying
local accounts, sessions or user results. Never overwrite an active Dataset Head or
copy a live PostgreSQL data directory.
