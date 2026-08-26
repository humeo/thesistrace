# Use one full Compose topology for local Development and Test

Development and Test run the same complete Compose product topology, differing only in isolated identities, ports, credentials, and disposable versus persistent state. One topology makes networking, readiness, Worker roles, and state ownership observable at the real service boundary instead of maintaining a hybrid alternate runtime.
