---
status: accepted
---

# Classify Forward Label unavailability without filling it

For each signal session, instrument, and 1-, 5-, or 20-session horizon, V1
classifies an unavailable Forward Return Label as exactly one of:

```text
right_censored_by_release_end
confirmed_market_open_unavailable
unexplained_missing_or_invalid_data
```

`right_censored_by_release_end` means the required entry or exit Research
Session lies after the pinned Dataset Release's final session. For a
504-session Research Window ending with that release, and assuming otherwise
complete history, the theoretical maximum labeled signal-session counts per
instrument are:

```text
1-session:   502
5-session:   498
20-session:  483
```

These counts follow directly from requiring opens at `t+1` and `t+1+h`.
Right-censoring is expected coverage loss, not a Dataset error, and V1 never
moves or shortens the Research Window to remove it.

`confirmed_market_open_unavailable` means the required entry session is
`full_session_suspended` or already terminally delisted, or that the required
exit session is `full_session_suspended`, and therefore has no usable daily
Open for the Label formula. Valuation Carry may not substitute for that
unavailable Label coordinate. Both `open_suspended_partial` and
`after_open_suspended` retain their first traded daily Open and may supply a
Label coordinate under ADR-0089.

ADR-0101 is the one terminal exception at the exit coordinate: once a valid
entry Open exists, explicit terminal delisting on or before the required exit
supplies a synthetic value of zero and produces a valid `-100%` Label rather
than an unavailable Label. The zero is not Canonical Market Data.

`unexplained_missing_or_invalid_data` means a required open is absent or
invalid without governing suspension evidence. It is a hard Dataset
Publication or ResearchRun failure under ADR-0074, not a successful run's
ordinary missing-label observation.

This decision refines rather than replaces ADR-0026 and ADR-0074: unavailable
opens still produce no Label except for ADR-0101's explicit terminal exit
outcome, and unexplained market-data loss still fails.
