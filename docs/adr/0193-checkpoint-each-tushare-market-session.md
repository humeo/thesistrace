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

There is one checkpoint format bound to the current source contract. A
confirmed full-session suspension remains active across subsequent sessions
without daily bars and ends when daily trading resumes; isolated absence still
fails closed. Missing checkpoints start a new collection. Existing but invalid,
corrupt, wrong-window, wrong-contract, or non-current-format checkpoints fail
closed and are never migrated or supported in parallel. Successful Dataset Head
publication clears both the manifest and addressed session content; failed
collection retains them.
