---
status: accepted
---

# Preserve source financial versions without inventing history

ThesisTrace V1 does not build an independent financial-revision engine. Each
published Data Generation immutably retains the Tushare responses it actually
accepts and preserves source version metadata such as announcement dates,
report type, and update marker.

When Tushare exposes both original and adjusted rows, Canonical Market Data
uses those source-provided versions with the derived point-in-time availability
rules. When a later pull changes previously observed data, the new Data
Generation references new Physical Data Objects. This rule does not require
permanent retention of superseded Generations.

When Tushare does not expose a complete historical revision chain, ThesisTrace
does not infer or fabricate one. Field Catalog and research results report the
resulting revision-coverage limitation and must not claim complete
point-in-time history for those fields.
