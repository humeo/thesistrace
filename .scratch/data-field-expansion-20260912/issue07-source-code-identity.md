# Historical daily_basic code identity qualification

The first real whole-day response for 2010-01-04 contains 1,632 rows, with no duplicate codes and exactly the requested date. Two raw codes are absent from the pinned canonical identity family: 000022.SZ and 000043.SZ. See the retained `issue07-daily-basic-identity-diagnosis.json`.

Official evidence establishes these as code changes of the existing securities:

| Raw historical code | Current code | Effective date | Primary evidence |
| --- | --- | --- | --- |
| 000022.SZ | 001872.SZ | 2018-12-26 | [Issuer disclosure on CNINFO](https://static.cninfo.com.cn/finalpage/2018-12-26/1205690369.PDF) |
| 000043.SZ | 001914.SZ | 2019-12-16 | [Shenzhen Stock Exchange notice](https://www.szse.cn/disclosure/notice/general/t20191211_572534.html) |
| 300114.SZ | 302132.SZ | 2025-02-17 | [Issuer implementation announcement on SZSE](https://disc.static.szse.cn/download/disc/disk03/finalpage/2025-02-15/cedb693a-f5ee-4463-9682-ea33d406b569.PDF) |

The pinned Generation already records stable Instrument Identities `equity:001872.SZ` (listed from 1993-05-05) and `equity:001914.SZ` (listed from 1994-09-28). The 2010-01-04 canonical closing prices are 15.22 and 14.92 respectively.

Deeper inspection of the retained whole-day response establishes that TuShare returns BOTH old and current codes for that date. Prices match, but some backfilled dividend ratios differ: 000043 has dv_ratio 0.34 while 001914 has 0.3351; 000022 has null while 001872 has 3.2852. Therefore blindly mapping old codes to current ones introduces duplicate/conflicting observations. An initial date-crosswalk implementation passed synthetic tests but was rejected by the same real first-day response; it was superseded before commit.

The current contract uses the source row matching the canonical identity's own code. A verified retired-code duplicate can be excluded from normalized output only before its effective change AND when the current code is also present in the same whole-day response. Both raw rows remain in the immutable receipt, and their values are never merged. A retired row alone, other unknown codes, duplicate current codes and wrong dates still fail collection. A capped whole-day response is split based on its ORIGINAL row count, before excluding retired duplicates. This adds no schema version, migration, old reader or automatic unknown-code inference.

The resumed collection reached 2010-08-27 and correctly stopped on 300114.SZ. Its IPO-day response also includes 302132.SZ with the same financial values; retained evidence is `issue07-daily-basic-scope-2010-08-27.json`. The official 2025 change above establishes the same duplicate-code case, which was added to the explicit source table and date-boundary regression.

## Exchange scope

The 2018-10-09 whole-day response first introduces `.BJ` source codes in this run, including backfilled NEEQ history; see `issue07-daily-basic-scope-2018-10-09.json`. The existing canonical instrument normalizer admits only SSE/SZSE main, ChiNext and STAR markets. Explicit six-digit `.BJ` codes in whole-day payloads are retained as raw evidence but excluded from normalized output when outside the requested identity set. Exact-security requests do not accept unrelated codes. Their rows count toward the 6,000-row cap before filtering. This preserves the pinned research universe instead of silently broadening it.
