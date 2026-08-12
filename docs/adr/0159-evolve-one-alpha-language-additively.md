---
status: accepted
---

# Evolve one Alpha Language additively

ThesisTrace maintains one current Alpha Language rather than named language
releases or a multi-version runtime. Run admission uses the current compiler
and catalogs to reject an invalid Formula with structured diagnostics or to
produce the canonical Alpha Expression executed by the Worker. Existing
syntax, stable Field References, Builtin identities and semantics, numeric and
missing-value behavior, and compiled expression forms never change meaning;
new capabilities are additive, and a behaviorally different field or Builtin
receives a new stable identity. This lets the current compiler and executor
continue to accept earlier Formulae and Expressions without a Release ID,
compatibility dispatcher, fallback, or migration path.
