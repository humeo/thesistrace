---
status: accepted
---

# Require an explicit Data-owned Alpha Field Capability

A Canonical Field does not become an Alpha input merely because it exists or
has a numeric physical type. Its Data-owned Field Definition must explicitly
grant an Alpha Field Capability after establishing stable point-in-time
meaning, instrument-by-Research-Session grain, numeric type and unit,
information availability, missingness, and a Data-owned Series reader. The
Alpha Authoring Catalog derives its Field entries from those capabilities, so
the Compiler, Research Kernel, and frontend maintain no second field allowlist
or physical-row-key mapping. Adding a Canonical Field without this capability
keeps it internal; granting the capability exposes it in the current Alpha
Language.
The Field Definition represents authorization as an optional typed
`AlphaFieldCapability`, not a Boolean or open string-keyed capability map. That
object contains only the stable Alpha Identifier and current Alpha value type;
the surrounding Field Definition remains the sole owner of point-in-time,
grain, physical type, unit, availability, and missingness facts. New research
contexts add typed capability fields only when those contexts actually exist.
