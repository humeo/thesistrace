---
status: accepted
---

# Roll back release bundles with expand-contract schema changes

Hosted Platform V2 retains the immediately preceding immutable release bundle and applies database changes through expand-contract compatibility so a failed release can return to a tested component set. It provides no automatic down migration; an incompatible data change is declared restore-required because partially reversing persisted state is unsafe.
