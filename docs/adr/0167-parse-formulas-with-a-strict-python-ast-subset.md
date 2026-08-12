---
status: accepted
---

# Parse Formulae with a strict Python AST subset

The backend Alpha Compiler checks the Formula source-length budget before
calling Python's standard-library `ast.parse` in expression mode. An exhaustive
translator accepts only numeric literals, bare names, the supported unary and
binary arithmetic nodes, parentheses as represented by the parser, and calls
whose target is one bare Alpha Builtin Identifier and whose arguments satisfy
its Builtin Definition. Every other node and form, including attributes,
subscripts, collections, comprehensions, keywords, comparisons, conditionals,
lambdas, assignments, and dynamically shaped calls, produces an Alpha
Diagnostic. Accepted nodes are immediately translated into ThesisTrace's own
canonical Alpha Expression. Python AST remains transient parser output and is
never passed to `compile`, `eval`, or `exec`, executed, or persisted as the
Alpha execution truth. The allowlist and a rejection corpus prevent future
Python grammar additions from silently extending the Alpha Language.
