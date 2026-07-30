---
status: accepted
---

# Limit V1 Alpha authoring to bounded numeric expressions

V1 embeds one Alpha Expression as a field of the Research Definition. It is a
declarative numeric formula composed only from Canonical Market Data Field
References, numeric literals, parentheses, arithmetic, and a closed set of
built-in functions.

An Alpha Expression cannot contain Python, SQL, arbitrary code, or
user-defined functions. Validation parses the formula, resolves its Field
References, and rejects unsupported syntax before the Research Definition is
frozen. ResearchRun evaluates the formula directly from the same frozen
definition; validation does not create an independently versioned AST,
compiled plan, or other runtime domain artifact.

ADR-0028 fixes the V1 built-in function set. Lookback and missing-value
semantics remain separate V1 decisions. ADR-0072 fixes the complete V1 Field
Reference allowlist.
