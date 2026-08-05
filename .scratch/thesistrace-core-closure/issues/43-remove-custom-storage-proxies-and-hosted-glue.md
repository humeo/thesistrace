# 43 — Remove custom storage proxies and Hosted glue

**What to build:** Delete the remaining self-built object-store, network proxy,
and Hosted glue after every Hosted and old-Web caller is gone.

**Blocked by:** 42.

**Status:** ready-for-agent

- [ ] The custom object-store HTTP service, storage-token protocol, remote
  filesystem proxy, and Hosted-only Tushare egress proxy are removed.
- [ ] Hosted runtime-mode configuration, shared startup glue, remaining Hosted
  entrypoints, dependencies, scripts, Make targets, and tests are removed when
  no caller remains.
- [ ] Core Publication still uses only the standard S3 client against the
  configured endpoint.
- [ ] Canonical Tushare remains a direct DataSource adapter and creates no
  product mode.
- [ ] No Core response exposes a replacement storage or proxy protocol.
- [ ] The Hosted archive and historical ADR/research material remain intact.

**How to verify:**

```sh
set -eu

for removed_path in \
  src/thesistrace/hosted \
  tests/hosted
do
  test ! -e "$removed_path"
done

python - <<'PY'
import tomllib
from pathlib import Path

project = tomllib.loads(Path("pyproject.toml").read_text())
assert project["project"]["scripts"] == {
    "thesistrace-core-api": "thesistrace.entrypoints.http:main",
    "thesistrace-core-worker": "thesistrace.entrypoints.worker:main",
    "thesistrace-api": "thesistrace.entrypoints.http:main",
    "thesistrace-worker": "thesistrace.entrypoints.worker:main",
}
dependencies = project["project"]["dependencies"]
assert any(item.startswith("boto3") for item in dependencies)
assert any(item.startswith("httpx") for item in dependencies)
PY

if rg -n \
  --glob '!docs/adr/*.md' \
  --glob '!docs/research/*.md' \
  --glob '!docs/archive/*.md' \
  --glob '!web/node_modules/**' \
  --glob '!web/dist/**' \
  'thesistrace\.hosted|RemoteObjectStore|OBJECT_STORE_(ROOT|TOKENS)|TUSHARE_EGRESS|THESISTRACE_(RUNTIME_MODE|DATABASE_ROLE|OBJECT_STORE)|runtime_mode|database_role|object_store_(url|token)' \
  pyproject.toml uv.lock Makefile src scripts tests web
then
  echo 'Custom proxy or Hosted glue remains in the active tree' >&2
  exit 1
fi

uv run pytest -q tests/architecture tests/adapters

trap './scripts/core-test-runtime down' EXIT
./scripts/core-test-runtime reset
./scripts/core-test-runtime run \
  uv run pytest -q tests/integration
```

## Comments
