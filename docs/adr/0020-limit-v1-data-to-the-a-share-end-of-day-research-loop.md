---
status: accepted
---

# Limit V1 data to the A-share end-of-day research loop

V1 implements only the Dataset Families required for the confirmed Shanghai
and Shenzhen A-share end-of-day research loop:

- instrument reference and market calendar;
- the complete eleven-field Tushare daily source contract mapped to normalized
  raw OHLC, reference close, price change, return ratio, actual-share volume,
  CNY turnover amount, plus separately sourced adjustment factors, derived
  Adjusted Research Prices, and trading status;
- daily Top 300, 1000, 2000, and 3000 Liquidity Universe membership;
- historical SW2021 industry classification used by optional industry
  neutralization.

Financial data, futures, options, and convertible bonds are not ingested,
published, exposed through Field Catalog, or executable in V1. Their Dataset
Family and point-in-time boundaries remain documented so a later version can
add them without changing the V1 equity contracts.
