# Separate confirmed suspension from unknown market-data loss

Canonical Trading State distinguishes valid partial-session trading from confirmed full-session suspension, and only the latter permits suspension-specific execution, valuation, benchmark, and liquidity treatment. A missing or contradictory bar without governing evidence fails Data validation rather than becoming suspension, zero turnover, or a blocked order.
