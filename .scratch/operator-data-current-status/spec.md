# Operator current data status

Status: complete

Show the current published Market, CSI 300 Benchmark, Financial, and Industry
coverage and freshness on Operator / Data, before the refresh forms. Reuse the
existing operational-status snapshot; do not add a second overview request,
derive published state from operation receipts, or change refresh behavior.

Use compact aligned rows, explicit UTC timestamps, distinct financial attempted
and complete discovery boundaries, pending/gap counts, and explicit unavailable
values. Preserve current date pickers and unrelated working-tree changes.

Verification: response contract and decoder tests, rendering tests for distinct
coverage/empty/degraded states, existing real-dependency status integration, web
typecheck, and browser inspection. No live data refresh is part of acceptance.

Delivery: implementation and tests are committed in `6a85ded`; the implementation
issue records the passed checks and browser acceptance.
