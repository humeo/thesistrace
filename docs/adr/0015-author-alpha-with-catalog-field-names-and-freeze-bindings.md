---
status: superseded by ADR-0151
---

# Author Alpha with catalog field names and freeze bindings

Research authors reference the six Alpha-authorable Canonical Market Data
fields fixed by ADR-0072 through their short Field Catalog names. The complete
Field Catalog also contains fields used by execution, validation, or provenance
that are not Alpha-authorable. The editor exposes definitions, units, coverage,
availability in the selected Dataset Release, and completion support for the
permitted subset. Authors do not need to type fully qualified internal field
IDs.

When ADR-0098 validates and freezes the current Research Definition Draft on a
Run request, it records the stable `field_id` resolved for every referenced
catalog name. A reference outside the allowlist, unavailable in the release,
or ambiguous fails validation. The bindings remain part of the same Research
Definition consumed directly by ResearchRun; they are not a separate compiled
plan.
