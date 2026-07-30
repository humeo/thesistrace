---
status: accepted
---

# Run version-pinned migrations before steady services

Hosted Platform V2 applies schema and platform bootstrap changes through explicit version-pinned one-shot migration jobs before steady services start. A failed migration blocks the release so normal process startup cannot hide schema changes or expose a partially upgraded product.
