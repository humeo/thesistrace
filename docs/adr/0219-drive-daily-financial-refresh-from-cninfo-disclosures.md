# Drive daily financial refresh from disclosure evidence

Superseded by [ADR-0249](0249-discover-financial-reports-from-structured-disclosure-periods.md).

After financial bootstrap, CNINFO disclosure evidence identifies affected instruments while Tushare supplies all Canonical financial values. Refresh preserves successful updates with explicit pending instruments or discovery gaps, accepting visible incomplete discovery instead of either withholding usable data or claiming exhaustive source reconciliation. Unannounced financial corrections require explicit reconciliation because announcement evidence cannot establish that they occurred.
