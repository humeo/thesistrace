---
status: accepted
---

# Keep one current Alpha Language with hard cuts

ThesisTrace maintains one current Alpha Language rather than named language
releases or a multi-version runtime. Run admission uses the current compiler
and catalogs to reject an invalid Formula with structured diagnostics or freeze
the canonical Alpha Expression executed by the Worker.

New capabilities may extend the language, but a rename, removal, or
result-changing semantic update is a Product State hard cut under ADR-0211.
Obsolete Formulae and Browser Drafts are rejected; the runtime contains no
alias, parser rewrite, migration, compatibility dispatcher, or fallback path.
