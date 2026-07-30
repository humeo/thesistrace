# 04 — Publish Calendar, Universe, Industry, and Field Catalog

**What to build:** Publish and let the operator inspect the Research Calendar,
point-in-time ordinary-A-share Base Pool, four Liquidity Universes, historical
SW2021 membership, ST designation, and stable Field Catalog.

**Blocked by:** 03 — Publish Canonical EOD Price, adjustment, and Trading State.

**Status:** resolved

- [x] Research Sessions are the ordered intersection of SSE and SZSE open days.
- [x] Base Pool membership uses point-in-time source evidence and excludes every out-of-scope instrument type without survivorship bias.
- [x] Top 300, 1000, 2000, and 3000 rank trailing-20-session mean turnover with Instrument Identity tie-breaking.
- [x] Full-session suspension contributes zero turnover and newly listed instruments remain unranked until they have all 20 positions.
- [x] SW2021 L1, L2, and L3 membership resolves through non-overlapping half-open intervals; gaps remain missing.
- [x] The Field Catalog exposes stable identifiers, definitions, units, coverage, Release availability, and the six Alpha-authorable names.
- [x] API and UI inspection never require authors to understand Tushare field names.

## Comments

- Published the SSE/SZSE intersection calendar, point-in-time ordinary-share
  Base Pool, four turnover-ranked Universes, SW2021 intervals, ST evidence, and
  stable Field Catalog.
- Added a canonical `data-contract` API and Web inspection panel for the six
  authorable fields without requiring vendor field knowledge.
