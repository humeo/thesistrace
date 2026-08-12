---
status: accepted
---

# Keep Canonical Market Data field definitions immutable

Every Canonical Market Data field has a stable `field_id` and an immutable
definition covering its type, unit, primary-key grain, and
information-availability semantics.

Adding a field creates a new Dataset Schema version and a later Data Generation
may provide values for it. Correcting erroneous values does not change the
field or schema; a refreshed Data Generation references corrected Physical Data
Objects. Changing a field's meaning, unit, grain,
or availability semantics requires a new `field_id` rather than reinterpreting
the old field.

A ResearchRun's immutable input binds stable fields, and Run admission rejects
the current Dataset Head when it does not provide every required field. Data
Generation retention remains governed by active Head and execution pins rather
than by field-definition history.

ADR-0071 defines the initial `equity.eod_price` field names, types, units, and
source mappings. Upstream fields added after that contract do not silently
change it.
