# Recompute failed Tracking Advances from the authoritative Head

Tracking Head is the sole recovery truth: every Attempt recomputes the Advance's frozen oldest-session target from that unchanged Checkpoint under one pinned current Data Generation. Transient retries are bounded and fair, while deterministic failures block until explicit Retry or Stop; no private cross-Attempt state may rewrite published history or alter the accepted target.
