---
status: accepted
---

# Use one minimal Instrument Identity across asset families

Every Dataset Family references a minimal shared Instrument Identity containing
an `instrument_id`, asset type, exchange, symbol, lifecycle, and Tushare code.
The common contract carries identity only; price fields and asset-specific
contract terms remain in their respective Dataset Families.

`instrument_id` is the deterministic, readable `{asset_type}:{ts_code}`, such
as `equity:600000.SH`. ThesisTrace retains the source `ts_code` separately but
does not generate a random UUID or maintain a surrogate-ID mapping table.

The current product creates identities only for Shanghai and Shenzhen A-shares.
Unsupported futures, options, and convertible bonds are not pre-modeled inside
the equity contract; any such asset family must own its contract metadata and
lifecycle events while referencing the same minimal identity boundary.

Tushare is the sole source namespace. The identity model therefore does not
include a general provider registry or multi-provider mapping framework.
