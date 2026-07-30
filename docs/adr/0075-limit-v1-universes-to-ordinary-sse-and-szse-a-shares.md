---
status: accepted
---

# Limit V1 universes to ordinary SSE and SZSE A-shares

The V1 Universe Base Pool contains only ordinary CNY-denominated A-shares on
the Shanghai and Shenzhen exchanges: the SSE Main Board, SZSE Main Board,
ChiNext, and STAR Market. B-shares, Chinese depositary receipts, Beijing Stock
Exchange securities, ETFs and other funds, bonds including convertible bonds,
preferred shares, and every other non-ordinary-equity instrument are outside
the V1 pool.

Pool membership is point-in-time. Dataset Publication resolves the accepted
source evidence into one Universe Base Pool snapshot for each `as_of_date`
before liquidity ranking begins. The Liquidity Universe consumes that daily
snapshot; it does not interpret source listing statuses, maintain listing
intervals, or own listing-lifecycle transitions.

A security that later delists remains present in historical snapshots from its
former listed period; Dataset Publication never filters history using the
security's current listing status. This prevents survivorship bias.

An ST or `*ST` designation does not remove an otherwise in-scope instrument
from the Universe Base Pool or its liquidity rank. ADR-0039 applies that
historical status only as a downstream Research Eligibility rule.
