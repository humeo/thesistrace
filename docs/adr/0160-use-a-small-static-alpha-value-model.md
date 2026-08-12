---
status: accepted
---

# Use a small static Alpha value model

The Alpha compiler assigns every expression node one of three value types:
`Numeric Series`, `Number`, or `Window`. An Alpha-authorable Canonical Field
Reference produces a Numeric Series keyed by instrument and Research Session;
a numeric literal produces a Number; and a Builtin window argument accepts an
integer literal from 1 through 252 as a Window. Arithmetic between a Numeric
Series and a Number broadcasts the Number explicitly, while each Builtin
declares its complete argument and result types. Run admission rejects every
Formula whose types do not match or whose root does not produce a Numeric
Series. Boolean, categorical, date, table, and differently grained values are
excluded until a concrete Alpha requirement justifies adding a new type to the
single append-only language.
