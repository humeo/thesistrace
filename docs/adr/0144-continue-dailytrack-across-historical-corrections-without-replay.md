---
status: superseded by ADR-0154
---

# Continue DailyTrack across historical corrections without replay

When a normal Dataset Release contains an accepted historical correction, an active DailyTrack appends an ordinary Tracking Checkpoint in the same Tracking Generation without changing previously committed results or replaying from its Tracking Origin. New results use the corrected data only when first calculated at or after that correction boundary, and reproducibility and equivalence follow the exact ordered `target_dataset_release_id` sequence bound by the immutable Checkpoint chain.
