---
status: accepted
---

# Keep Canonical Market Data field definitions immutable

Every Canonical Market Data field has a stable `field_id` and an immutable
definition covering its type, unit, primary-key grain, and
information-availability semantics.

Adding a field creates a new Dataset Schema version and a later Dataset Release
may provide values for it. Correcting erroneous values does not change the
field or schema; the next new-session Dataset Release references corrected
Physical Data Objects under ADR-0088. Changing a field's meaning, unit, grain,
or availability semantics requires a new `field_id` rather than reinterpreting
the old field.

Older Dataset Releases retain their original schema and objects. A frozen
Research Definition references stable fields and validation rejects a selected
release that does not provide every required field.

ADR-0071 defines the initial `equity.eod_price` field names, types, units, and
source mappings. Upstream fields added after that contract do not silently
change it.
