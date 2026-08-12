---
status: accepted
---

# Use one bare-identifier Alpha expression

An Alpha Formula contains exactly one expression followed by end of input. It
uses bare Field Catalog names such as `close_adj`, numeric literals, unary and
binary arithmetic, parentheses, and named Alpha Builtin calls such as
`ts_mean(close_adj, 20)`. A bare name denotes a Field Reference, while a name
followed by `(` denotes a Builtin call; Field References do not use a `$` or
other prefix. All Field and Builtin names are stable lowercase `snake_case`
Alpha Identifiers in one globally unique namespace. The language has no assignment, local variable, statement,
control flow, import, member access, indexing, or user-defined function. More
program-like forms may be added only after a concrete authoring need outweighs
their grammar, scope, diagnostics, and execution complexity.
