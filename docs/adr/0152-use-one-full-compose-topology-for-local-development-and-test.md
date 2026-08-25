---
status: accepted
---

# Use one full Compose topology for local Development and Test

Local Development and Test use the same complete Compose service graph.
Web, API, Worker, PostgreSQL, RustFS, mounted Canonical Data, and
one-shot schema initialization all belong to it; Workers run as the fixed-role
ordinary Research, Batch Research, and Tracking pools. Persistent Development and
disposable Test use different overlays, project identities, ports, credentials,
volumes, and data lifecycles without selecting different product runtimes.

Fast checks and the host test runners address only the isolated dependencies
and Web origin created for that run. Each Test project is uniquely named and
deterministically torn down with evidence captured before cleanup; Development
preserves state across stop/start, while `dev:reset` removes only Product State
and `dev:erase` is the explicit operation that also removes Canonical Data.

One service graph is chosen over a hybrid host/container topology because it
makes readiness, networking, state ownership, worker roles, and failure
diagnostics observable at the same boundary. This is a local lifecycle
contract, not Production readiness.
