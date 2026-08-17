---
status: accepted
---

# Checkpoint each complete Tushare market session

Live bootstrap records its calendar and instrument foundation before market
collection, then records each Research Session only after `daily`,
`adj_factor`, `suspend_d`, and `stk_limit` all succeed. The session payload is
canonical JSON stored as immutable SHA-256-addressed content; the bounded,
atomically replaced checkpoint manifest maps session dates to content hashes
and byte counts. A retry for the exact request window and source contract reads
those payloads and does not call Tushare again for completed dates.

There is one current checkpoint format bound to the current source contract,
which accepts one- or two-digit hours in intraday suspension ranges and the
`09:30-09:30` full-session suspension sentinel. A confirmed full-session
suspension remains active across subsequent sessions without daily bars and
ends when daily trading resumes; isolated absence still fails closed. Missing
checkpoints start a new collection. Existing but invalid, corrupt,
wrong-window, or wrong-contract checkpoints fail closed. The replaced
foundation-only format is deleted rather than migrated or supported in
parallel. Successful Dataset Head publication clears both the manifest and
addressed session content; failed collection retains them.
