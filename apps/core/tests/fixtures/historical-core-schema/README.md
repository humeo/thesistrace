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
