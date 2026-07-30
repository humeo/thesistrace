---
status: accepted
---

# Keep launch secrets in host-mounted files

The first Hosted Platform V2 node does not depend on Vault, a cloud Secret
Manager, dynamic secret delivery, or automatic rotation. Operators provision
production secrets in a dedicated host directory outside the source checkout.
Files are owned by the deployment identity, use mode `0600`, and are mounted
through Compose secrets. A component that cannot read a secret from a file may
receive it through a separately protected production `env_file`; that fallback
also remains outside the repository.

Tushare credentials, InsForge signing and encryption keys, database-role
passwords, service identities, and external OTLP credentials remain separate.
Services receive only the credentials they require and do not share a database
role or impersonate an end User.

Secrets never enter Git, container images, the production Web build, Temporal
payloads or Workflow History, structured logs, metrics, or traces. Migration
and diagnostic commands must not print them. Docker and host access to mounted
secret files is an operator privilege, not a product API.

The operator maintains one separately encrypted recovery bundle containing the
current required secrets. It is updated when a secret changes and is restored
independently from the seven-day product-data backup series so a replacement
node can decrypt and authenticate the recovered InsForge state. The bundle is
current recovery material, not a history of prior secret versions.
