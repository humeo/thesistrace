# Separate confirmed suspension from unknown market-data loss

Canonical Trading State distinguishes valid trading, confirmed full-session suspension, and unavailable market evidence, so only confirmed suspension permits suspension-specific valuation and liquidity treatment. Unexplained missing data remains explicitly unavailable and contradictory coverage fails validation, preventing either condition from silently becoming a suspension or an executable price.
