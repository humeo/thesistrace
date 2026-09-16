# Historical release schema fixture

`publication-maintenance-release.zip` contains the eight Core schema SQL files,
in contract order, from Git commit `fc94e3aa270b3c9a2c809de63b8d0b755aa2995c`.
Its computed Core fingerprint is `6f04fe84573259465442c092856b69714ed339c2093d51dcf67ba4b68aaa359f`.
Archive SHA-256: `76498ac400bbccbf1a0b406d78ea5bcf6e2a9080eb694c9fe7caa94a10c2994f`.

This immutable test input supplies the matching release environment for existing
historical migration regression tests. Current application initialization and
production migration code do not load this archive. The regression tests retain
real PostgreSQL data-preservation, idempotency, structure-drift and rollback checks;
they must not substitute today's schema for a historical release or alter a
migration's pinned source/target fingerprints to make a test pass.

`financial-indicator-target.zip` contains the eight Core schemas in contract order
from `39e4b88cd4f6f595472a225c51b06a9436c0d030`, the indicator migration's target release.
Core fingerprint: `624c319e2f0a11425c5a5219d8125a10234c6885ae66531df57cd384e589a693`.
Archive SHA-256: `84fd2ee2cc38c23c81558d190cff52c27d561f951a8f8eb6ca4d7d7ce7fac547`.

`payload-retention-target.zip` contains the eight Core schemas in contract order
from `48b287bce13560ba9c09a5e2a95907304c1dd7af`, the retention migration's target release.
Core fingerprint: `1bb894bbece0ade8cb122d4054be492fb26ef56d1d9e85237a002f195e386a4f`.
Archive SHA-256: `ca06951985720b1446775ef114aefd91ca56e0b7532beead8983d2757af5556e`.

These target fixtures are injected only into historical migration tests. Tests
verify the actual archived SQL against each migration's pinned target fingerprint;
production guards and schema definitions remain unchanged.
