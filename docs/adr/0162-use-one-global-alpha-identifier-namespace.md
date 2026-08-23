---
status: accepted
---

# Use one global Alpha Identifier namespace

Every Alpha-authorable Field and Alpha Builtin exposes one lowercase
`snake_case` Alpha Identifier. The two catalogs share one globally unique
namespace: a Field and Builtin cannot have the same name even though a parser
could distinguish a call by its parentheses, and capitalization cannot create
a second identity. Composing the Alpha Authoring Catalog validates this
invariant before the application becomes ready. An identifier has one meaning
in the current Alpha Language; changing that contract is an explicit hard cut,
not a compatibility alias.
