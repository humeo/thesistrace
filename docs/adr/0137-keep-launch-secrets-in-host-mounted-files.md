---
status: superseded by ADR-0151
---

# Keep launch secrets in host-mounted files

The first Hosted Platform V2 node keeps least-privilege service secrets in protected host-mounted files outside the repository rather than introducing a remote secret manager. Secrets remain separated by service and excluded from product artifacts and telemetry, with a separately encrypted current recovery bundle so restored data remains usable.
