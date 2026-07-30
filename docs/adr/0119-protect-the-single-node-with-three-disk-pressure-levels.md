---
status: accepted
---

# Protect the single node with three disk-pressure levels

The first hosted deployment measures pressure against its configured 200 GB
persistent SSD capacity. Its three thresholds are deployment configuration,
with initial values of 70%, 80%, and 90%; they are not domain or API constants.

At 70% used capacity (140 GB initially), the platform emits an operator warning
but changes no admissions.

At 80% used capacity (160 GB initially), the platform stops admitting new
Workspace work that would produce private stored objects. Reads, deletion,
physical cleanup, and other storage-reducing operations remain available.
Dataset Publication may continue only within its independently reserved capacity
and after its own preflight capacity check.

At 90% used capacity (180 GB initially), the platform rejects all new
payload-growing work, including Dataset Publication, with a stable
`DISK_PRESSURE` failure. Reads, cancellation, deletion, cleanup, garbage
collection, and the control writes required by those operations remain
available.

Crossing a threshold does not terminate work that is already running. Every
result publication performs a final capacity check before committing its
manifest and objects. If that check fails, publication is atomic from the
consumer's perspective and its temporary objects are removed.
