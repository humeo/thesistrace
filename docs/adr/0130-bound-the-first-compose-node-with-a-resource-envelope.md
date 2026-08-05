---
status: superseded by ADR-0151
scope: archived - outside the active Core
---

# Bound the first Compose node with a resource envelope

The first Hosted Platform V2 deployment treats its 6-core, 12-GiB Compose node as a hard resource envelope with explicit container limits and a protected host reserve. Representative maximum workloads must fit that envelope before admission so invited Users do not become the capacity test.
