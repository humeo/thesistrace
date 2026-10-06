import catalog from "./data-field-catalog.json" with { type: "json" };
import type { DataSnapshot } from "../../src/data/dataResources";

export const workbenchData = {
  catalog: catalog as DataSnapshot["catalog"], generation_manifest_sha256: null, available_field_ids: [], field_families: [],
  market_coverage: { start: "2010-01-04", end: "2026-08-13" },
  financial_coverage: null, industry_coverage: null, benchmark_coverage: null,
  benchmark_snapshot_sha256: null, benchmark_last_published_at: null,
  data_through_session: "2026-08-13", last_market_refresh_at: null,
  last_financial_refresh_at: null, last_industry_refresh_at: null,
  industry_refresh_status: null, industry_refresh_failure_code: null,
  market_research_readiness: true, benchmark_research_readiness: false,
  financial_research_readiness: "not_ready", industry_research_readiness: false,
} satisfies DataSnapshot;
