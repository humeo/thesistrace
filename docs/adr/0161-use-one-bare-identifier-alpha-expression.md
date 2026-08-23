---
status: accepted
---

# Use one bare-identifier Alpha expression

An Alpha Formula contains exactly one expression followed by end of input. It
uses bare Field Catalog names such as `close`, numeric literals, unary and
binary arithmetic, parentheses, and named Alpha Builtin calls such as
`ts_mean(close, 20)`. A bare name denotes a Field Reference, while a name
followed by `(` denotes a Builtin call; Field References do not use a `$` or
other prefix. All Field and Builtin names are lowercase `snake_case` Alpha
Identifiers in one globally unique namespace. The language has no assignment,
local variable, statement, control flow, import, member access, indexing, or
user-defined function because those forms would add grammar, scope, diagnostics,
and execution complexity without a current authoring need.
