---
status: accepted
---

# Separate Alpha identifiers from namespaced Field References

Alpha Formulae keep stable lowercase `snake_case` Alpha Identifiers, while
compiled Alpha Expressions and Data Generations use namespaced stable
`field_id` references. The initial financial references use
`financial.<statement>.<meaning>.<projection>` rather than reusing their Formula
identifiers, matching the existing separation between market Formula names and
Canonical market references. This keeps authoring concise without making a
user-facing name double as an internal cross-family identity.
