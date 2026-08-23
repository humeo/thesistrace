---
status: accepted
---

# Separate Alpha field and builtin ownership

The Data module owns the Field Catalog, including each Canonical field's stable
identity, meaning, type, unit, availability semantics, and Alpha-authorable
status. The Research Kernel owns the Alpha Builtin Catalog, including each
named function's signature, lookback rule, missing-value and numeric semantics,
and evaluator. The Alpha Language layer combines those two sources into one
read-only Alpha Authoring Catalog consumed by the compiler and authoring UI;
it does not copy or redefine their semantics, and its composition fails when a
Field and Builtin expose the same Alpha Identifier. Fields and builtins enter
the current Alpha Language only through their owning modules, never through a
central mutable registry, frontend
configuration, or runtime plugin.
