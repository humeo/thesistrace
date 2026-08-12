---
status: accepted
---

# Make each Alpha Builtin one self-contained definition

Each Alpha Builtin is implemented as one code-owned Builtin Definition in the
Research Kernel. The definition binds its globally unique Alpha Identifier to
its typed signature, authoring documentation and examples, argument
validation, effective-lookback and complexity rules, missing-value and numeric
semantics, and evaluator. Adding a Builtin adds one definition, registers it
once in the append-only Alpha Builtin Catalog, and supplies its contract and
numeric tests. The compiler and Worker dispatch through that catalog, while
the authoring API exposes only a serializable projection for the frontend.
ThesisTrace does not maintain parallel compiler or evaluator switches,
frontend-owned function metadata, configuration-defined functions, or runtime
plugins.
