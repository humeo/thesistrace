---
status: accepted
---

# Make the DSL editor the only Alpha authoring surface

The selected Research Folder's authoring surface uses one Alpha Editor whose
text belongs to its browser-local Draft. The editor uses the read-only Alpha
Authoring Catalog for searchable Field and Builtin completion, click-to-insert
actions, typed signatures, documentation, and examples, and renders backend
Alpha Diagnostics at their source ranges. Local browser persistence preserves
incomplete or invalid editor text, while Run presents the authoritative
compilation result. ThesisTrace has no server Save or Refresh action, does not
retain a second editable visual expression tree, and does not synchronize a
builder with DSL text; the canonical Alpha Expression is compiler output and
may only be inspected as read-only ResearchRun provenance.
