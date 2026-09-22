# Preserve annual flow and latest-reported stock field meanings

The existing revenue, net_profit and operating_cash_flow fields select the latest visible full-year facts, while assets, liabilities and equity select the latest visible reported balance sheet. New statement-derived TTM fields use distinct identities and the reconstruction contract in [ADR-0243](0243-give-statement-derived-ttm-flows-distinct-field-identities.md), preserving accepted annual meanings rather than implicitly converting them when the catalog grows.
