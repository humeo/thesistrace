# 05 — Expand Liquidity only at Dataset Coverage Start

**What to build:** Rank instruments by governed mean CNY turnover from the
first available Dataset session, using one global bootstrap expansion that
ends permanently at Coverage session twenty.

**Blocked by:** None — can start immediately.

**Status:** complete

- [x] Liquidity Score is the mean `turnover_amount_cny` over the governed observation window, never share volume.
- [x] An instrument already listed at Dataset Coverage Start uses exactly one, two, and nineteen observations on Coverage sessions 1, 2, and 19 respectively.
- [x] From Coverage session 20 onward, every rankable instrument requires a complete trailing-20 governed window.
- [x] An instrument listed after Dataset Coverage Start receives no private expanding grace period and becomes rankable only after accumulating twenty governed observations.
- [x] Confirmed full-session suspension contributes zero turnover, partial suspension uses observed turnover, and unexplained missing turnover invalidates the window rather than becoming zero.
- [x] Rank order is mean turnover descending and `instrument_id` ascending on exact ties; every supported Top-N Universe is cut from the same deterministic ordering and remains nested.
- [x] Recomputing after a Generation or Refresh preserves the original Dataset Coverage Start and never restarts expansion.
- [x] Focused source-neutral tests cover Coverage sessions 1, 2, 19, and 20 without constructing a long ResearchRun fixture.

## Comments

- Implemented by `906b8eb feat(data): expand initial liquidity windows`; the module-boundary and governing-suspension review fixes are in `a217c58 fix(data): consume governed base pool snapshots`.
- Focused source-neutral plus Fixture/Tushare verification passed `38 passed in 118.31s`; the complete Kernel suite passed `118 passed in 279.50s`. An earlier full adapters/data milestone also passed `53 passed in 47.09s`; Ruff and diff checks passed.
- Tests use inverted share volume, Coverage sessions 1/2/19/20, a post-Coverage-start listing, a conflicting high turnover on a confirmed full-session suspension, unexplained missing turnover, and 3,001 exact ties to prove every Top-N prefix.
- Standards and Spec reviews used fixed point `a217c58`. After moving listing lifecycle back behind the governed daily Base Pool and strengthening the suspension precedence oracle, both dimensions ended with zero material findings.
