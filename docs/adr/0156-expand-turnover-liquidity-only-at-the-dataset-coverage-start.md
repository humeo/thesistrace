---
status: accepted
---

# Expand turnover liquidity only at the Dataset Coverage Start

Liquidity Rank continues to use mean CNY turnover amount with a target window
of 20 Research Sessions. During only the first nineteen sessions of the entire
Dataset Coverage, an instrument already listed at the Coverage Start uses the
expanding set of available Dataset sessions: one observation on the first
session, two on the second, and so on. From the twentieth Dataset session
onward, Liquidity Score always requires the complete trailing 20-session
window.

An instrument listed after the Dataset Coverage Start does not receive a new
expansion period. It becomes rankable only after accumulating twenty governed
turnover observations; confirmed full-session suspension contributes the
existing governed zero observation. A Data Refresh or new Data Generation
never resets the Dataset Coverage Start or the expansion phase.

This narrow bootstrap rule permits research at the beginning of a deliberately
bounded dataset without turning every newly listed stock's first-day turnover
into a mature liquidity measure. It partially supersedes ADR-0010's requirement
that every rankable instrument always have 20 post-listing sessions and
ADR-0076's unqualified trailing-20 wording. ADR-0010's trading-state and missing
observation rules and ADR-0076's deterministic ranking and identity tie-break
remain in force.
