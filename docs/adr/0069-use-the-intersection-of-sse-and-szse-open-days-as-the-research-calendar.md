---
status: accepted
---

# Use the intersection of SSE and SZSE open days as the Research Calendar

V1 defines a Research Session as a date on which both the Shanghai Stock
Exchange and Shenzhen Stock Exchange are open according to their Tushare
exchange calendars. The Research Calendar is the ordered intersection of those
open dates and is not configurable in a Browser Draft.

Every session-counted V1 rule uses this one calendar, including Research Period,
Calculation Warm-up, Effective Alpha Lookback, Liquidity Observation
Window, Forward Return Label horizons, Rebalance Interval, and 252-session
annualization.

A date on which only one exchange is open is not a cross-market Research
Session. V1 does not combine fresh observations from one exchange with stale
observations from the other to construct a daily cross-section.
