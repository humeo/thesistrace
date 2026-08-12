---
status: accepted
---

# Model historical industry membership as half-open intervals

Each Canonical SW2021 industry-membership record uses the effective-date
interval:

```text
[valid_from, valid_to_exclusive)
```

`valid_from` is inclusive. `valid_to_exclusive` is the first date on which the
record no longer applies and may be absent for an open-ended current record.
For a Research Session `t`, V1 resolves the historical classification whose
interval contains `t.session_date`.

For example:

```text
Bank:       [2024-01-01, 2024-07-01)
Non-bank:   [2024-07-01, ...)
```

The second path applies on 2024-07-01 without an ambiguous inclusive endpoint.

For one instrument and classification version, at most one industry path may
contain a date. Overlapping intervals are contradictory Canonical data and
fail candidate Data Generation validation. Adjacent intervals may meet at one
`valid_to_exclusive`/`valid_from` boundary.

A source-history gap remains an absent Industry Classification. V1 does not
extend the preceding interval, move the following interval backward, create an
`UNKNOWN` industry, or backfill the current classification. If a Research
Definition selects industry neutralization, ADR-0011 excludes that instrument
from the affected session's Final Alpha Cross-Section and reports
missing-industry coverage.
