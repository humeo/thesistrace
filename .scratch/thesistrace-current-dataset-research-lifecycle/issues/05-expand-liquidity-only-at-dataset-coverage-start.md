# 05 — Expand Liquidity only at Dataset Coverage Start

**What to build:** Rank instruments by governed mean CNY turnover from the
first available Dataset session, using one global bootstrap expansion that
ends permanently at Coverage session twenty.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Liquidity Score is the mean `turnover_amount_cny` over the governed observation window, never share volume.
- [ ] An instrument already listed at Dataset Coverage Start uses exactly one, two, and nineteen observations on Coverage sessions 1, 2, and 19 respectively.
- [ ] From Coverage session 20 onward, every rankable instrument requires a complete trailing-20 governed window.
- [ ] An instrument listed after Dataset Coverage Start receives no private expanding grace period and becomes rankable only after accumulating twenty governed observations.
- [ ] Confirmed full-session suspension contributes zero turnover, partial suspension uses observed turnover, and unexplained missing turnover invalidates the window rather than becoming zero.
- [ ] Rank order is mean turnover descending and `instrument_id` ascending on exact ties; every supported Top-N Universe is cut from the same deterministic ordering and remains nested.
- [ ] Recomputing after a Generation or Refresh preserves the original Dataset Coverage Start and never restarts expansion.
- [ ] Focused source-neutral tests cover Coverage sessions 1, 2, 19, and 20 without constructing a long ResearchRun fixture.
