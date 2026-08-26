# Separate Dataset Families by grain, time semantics, and asset

Canonical Fields share a Dataset Family only when asset boundary, primary-key grain, and information-availability semantics agree. Different semantics or asset contracts require separate families rather than a universal wide table, even when one calculation consumes them together.
