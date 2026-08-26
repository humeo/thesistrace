# Paginate the ordinary balance sheet inside one logical shard

The ordinary balance-sheet adapter fulfills one complete-history endpoint-by-instrument shard through deterministic fixed-size pagination, stable schema, preserved order, and fail-closed termination checks. Provider pages never become publication checkpoints or a runtime-selectable date-shard fallback.
