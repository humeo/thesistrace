# Make module-first Core the only active runtime

ThesisTrace is one modular monolith whose domain modules own lifecycle state and whose pure Research Kernel owns calculation, with PostgreSQL as Product State authority, mounted Canonical Data, RustFS publication, and one Web/API boundary. It deliberately rejects alternate local or hosted runtimes, generic event infrastructure, and replaceable storage ports in exchange for atomic locality and one fully tested system.
