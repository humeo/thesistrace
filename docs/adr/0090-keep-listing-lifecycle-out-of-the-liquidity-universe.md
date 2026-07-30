---
status: accepted
---

# Keep listing lifecycle out of the Liquidity Universe

Dataset Publication produces one point-in-time Universe Base Pool snapshot for
each Research Session. It is responsible for mapping accepted Tushare
instrument evidence into the ordinary-A-share scope fixed by ADR-0075.

The Liquidity Universe receives that completed daily Base Pool snapshot and
only applies its trailing-20-session liquidity score, deterministic ordering,
and Top-N cutoff. It does not interpret Tushare listing statuses, store
listing-lifecycle intervals, or decide when a listing, suspension from listing,
restoration, or delisting becomes effective.

A newly listed instrument may appear in the Base Pool before it is rankable;
ADR-0076 requires the complete liquidity observation history. A normal
full-session trading suspension does not remove an otherwise in-scope
instrument from the Base Pool. How Dataset Publication internally represents
listing evidence is an adapter and storage concern, not part of the Universe
contract or Research Definition.

ADR-0097 fixes the Tushare evidence used by that adapter and requires
Publication to fail rather than guess when the daily membership cannot be
established.
