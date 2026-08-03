---
status: superseded by ADR-0151
---

# Freeze the current Research Draft when Run is requested

The V1 editor keeps a mutable Research Definition Draft while the operator is
authoring a research. There is no separate user-visible Freeze action. When the
operator requests Run, the system atomically:

1. structurally and semantically validates the current Draft;
2. resolves `latest` to one concrete Dataset Release;
3. resolves and records every stable Field Catalog binding;
4. creates an immutable frozen Research Definition version; and
5. creates a ResearchRun that references exactly that frozen version.

If validation or binding fails, no ResearchRun is created and the Draft remains
editable. A frozen version never changes. Continuing to edit after a Run starts
creates or updates a new Draft revision and cannot alter the old Run's inputs.

This is version freezing for reproducibility, not compilation. The frozen
Research Definition remains the same structured format consumed directly by
ResearchRun; V1 creates no DSL, AST, compiled plan, or other executable domain
artifact.

Starting Daily Tracking is a later explicit action allowed only from a
successful ResearchRun under ADR-0103. It does not unfreeze the Definition or
make a mutable Draft follow `latest`.
