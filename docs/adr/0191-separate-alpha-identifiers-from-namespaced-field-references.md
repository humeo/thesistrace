---
status: accepted
---

# Separate Alpha identifiers from namespaced Field References

Alpha Formulae use the current lowercase `snake_case` Alpha Identifiers, while
compiled Alpha Expressions and Data Generations use stable namespaced
`field_id` references. Financial references use
`financial.<statement>.<meaning>.<projection>` rather than reusing their Formula
identifiers, matching the existing separation between market Formula names and
Canonical market references. This keeps authoring concise without making a
user-facing name double as an internal cross-family identity.
