---
status: accepted
---

# Use one global Alpha Identifier namespace

Every Alpha-authorable Field and Alpha Builtin exposes one stable lowercase
`snake_case` Alpha Identifier. The two catalogs share one globally unique
namespace: a Field and Builtin cannot have the same name even though a parser
could distinguish a call by its parentheses, and capitalization cannot create
a second identity. Composing the Alpha Authoring Catalog validates this
invariant before the application becomes ready. Once published, an identifier
retains its meaning under the append-only Alpha Language; a behaviorally
different capability receives a different name.
