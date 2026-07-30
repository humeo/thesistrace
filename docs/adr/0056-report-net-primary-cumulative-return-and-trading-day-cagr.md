---
status: accepted
---

# Report Net-primary cumulative return and trading-day CAGR

V1 reports Cumulative Return and Annualized Return separately for Gross NAV and
Net NAV. The Net values are the primary metrics presented as `Cumulative
Return` and `Annualized Return`; the Gross values remain explicitly labeled
cost-attribution metrics rather than a third ambiguous return result.

For either NAV series:

```text
Cumulative Return = ending NAV / starting NAV - 1

Annualized Return =
    (ending NAV / starting NAV) ^ (252 / return_interval_count) - 1
```

`return_interval_count` is the number of consecutive post-trade open-to-open
Strategy return intervals in the reported Research Window. Annualized Return is
therefore a compound annual growth rate on a 252-market-session convention, not
an arithmetic daily mean multiplied by 252.

The starting NAV is the common CNY 10,000,000 all-cash baseline at the first
Research Window open. It precedes initial deployment, so the ending-to-starting
ratio includes every reported Transaction Cost.
