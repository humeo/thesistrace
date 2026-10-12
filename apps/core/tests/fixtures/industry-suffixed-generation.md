# Suffixed industry release fixture

`industry-suffixed-generation-a2e4e2c.zip` was produced with the public mounted
Generation and Head APIs from release commit
`a2e4e2c6a95c66afab7ebae644b449113ee3a3af`. It contains only synthetic data:
the minimal one-stock, one-session fixture with primary SW2021 codes
`801780.SI`, `801783.SI`, `851911.SI`, matching the supplier suffix that the
release incorrectly retained.

- Archive SHA-256: `c8975590e400afd844c0a1ad8841370b2f22f66d1f6f09d1cf1a802ec187e750`
- Original Generation: `bf1195c5ae2e48b41a0d7ff5b0213c83cee9d08cbbd716ff75538c7cf1a7bf74`

The industry refresh integration regression uses this immutable input to verify
failure leaves Head unchanged, publication replaces only the industry family,
repeating the operation is idempotent, six-digit industry queries find members,
and historical Generation data remains unchanged and readable. Current runtime
code neither loads this fixture nor normalizes stored historical data on read.
