---
status: accepted
---

# Carry the last Adjusted Research Price only for suspended-holding valuation

When an Actual Holding has no market bar because its instrument is confirmed
`full_session_suspended`, V1 carries its last valid Adjusted Research Price
solely to mark that holding's Adjusted Holding Units for Strategy NAV. The
carried mark gives the position zero return on that session while preserving
its value and weight.

The runtime labels the mark `carried_for_valuation`. It does not create a
Canonical Market Data row, Raw Market Price, Alpha input, Forward Return Label,
or executable price from it. Orders remain blocked under the Open Execution
Model.

When a valid Adjusted Research Price appears after suspension, the Strategy NAV
recognizes the complete change from the last real pre-suspension mark to the new
mark. The carried values are valuation artifacts, not observed market prices.
A partial suspension with a valid daily bar never uses Valuation Carry.

ADR-0100 applies this carry only after a held position's missing daily Open has
resolved to confirmed `full_session_suspended`. Explicit terminal-delisting
evidence instead writes the position off at zero; every other unresolved
missing Open remains a data-quality failure.
