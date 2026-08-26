# Use per-instrument Tushare financial collection

Complete-history bootstrap uses resumable ordinary Tushare endpoint-by-instrument collection and fails closed rather than switching to VIP or alternate request shapes. Daily Financial Refresh reuses the same atomic three-statement value source only for instruments selected by CNINFO discovery, accepting slower collection for deterministic provenance and one deployable permission contract.
