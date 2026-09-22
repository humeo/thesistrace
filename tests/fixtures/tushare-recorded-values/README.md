# Fixed TuShare source values

This is an offline regression corpus captured on 2026-09-22. It contains saved
supplier values, query provenance, and independently checked expectations. Tests
read these files directly, require no credentials, and reject network connections.
They never request TuShare data or update the fixture.

`manifest.json` records the immutable Dataset coordinate, request parameters,
response timestamps and SHA-256 hashes. `samples.json.gz` is deterministic gzip;
the manifest's `samples_sha256` hashes its decompressed bytes. Decimal source
values are represented as strings to retain their numeric precision. They are
selected row excerpts; the response hashes identify the original complete
responses, not the serialized excerpts.

The corpus covers historical market dates from 2010 through 2026, raw and adjusted
prices, volume/amount conversions, adjustment factors, price limits, stock
identity, daily valuation fields, the three financial statements and financial
indicators. It also contains the complete saved industry memberships and CSI 300
benchmark history for the audited Dataset. Market cases are small, standalone
calendar windows; their stock pools are scoped to the recorded instruments, not
claims about a historical full-market Top 3000 ranking.

Market and daily-basic expectations come from the documented source units using
independent Decimal arithmetic. Financial expectations apply the recorded
`update_flag`, `ann_date` and publication-date rules to the saved observations,
including nulls, superseded records and point-in-time availability. Industry and
benchmark expectations were independently compared with every saved source row.
No expected numeric value is obtained by calling the production adapter under test.

Passing this corpus proves replay behavior for these fixed observations. It does
not assert that a running Dataset contains the newest supplier revision. The full
dataset audit and its differences are retained separately under the local audit
directory; for example, the observed historical adjustment-factor precision
differences must not be hidden by updating expected values from the Dataset.

The original complete response archive is kept locally at
`.local/audits/dataset-wide-20260922/`. That larger archive covers the full stock
population; this version-controlled corpus keeps a bounded selection for fast
regression checks. Updating this corpus is an explicit, reviewed change: retain
the new source evidence, investigate differences and review expected values before
replacing any fixture. Never regenerate it from the current implementation merely
to make a failing test pass.

Test entry points are documented only in [AGENTS.md](../../../AGENTS.md#testing).

Source contracts: [daily bars](https://tushare.pro/document/2?doc_id=27),
[adjustment factors](https://tushare.pro/document/2?doc_id=28),
[daily basics](https://tushare.pro/document/2?doc_id=32),
[income](https://tushare.pro/document/2?doc_id=33),
[balance sheet](https://tushare.pro/document/2?doc_id=36),
[cash flow](https://tushare.pro/document/2?doc_id=44), and
[financial indicators](https://tushare.pro/document/2?doc_id=79).
