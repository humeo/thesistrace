# 13 — Apply A-share order rules and Transaction Costs

**What to build:** Convert Strategy targets into legal A-share logical orders,
Child Orders, fills, rejections, cash changes, and costs at the synthetic
next-open execution coordinate.

**Blocked by:** 03 — Publish Canonical EOD Price, adjustment, and Trading State; 12 — Run the basic Top-N Strategy Account.

**Status:** ready-for-agent

- [ ] Main Board and ChiNext quantities use 100-share increments; STAR buys and partial sells follow their 200-share minimum and one-share increment.
- [ ] Complete liquidation may sell an odd-lot remainder and orders below their legal minimum are not created.
- [ ] Board-specific single-order caps split logical orders into legal Child Orders.
- [ ] Full-session suspension, upper-limit buys, and lower-limit sells block one logical order and cancel it without retry or substitution.
- [ ] Every eligible Child Order fills completely at the valid Raw Market Price Open with no slippage, participation, or partial-fill model.
- [ ] Commission minimum, transfer fee, and sell stamp duty apply per Child Order using Raw Notional and unquantized Decimal arithmetic.
- [ ] Buy affordability is recalculated after each prior fill and cost and never makes Net Cash negative.
- [ ] Market Rejections and non-order diagnostics retain separate reason-coded event details.
