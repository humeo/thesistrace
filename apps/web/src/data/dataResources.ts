import { queryOptions } from "@tanstack/react-query";
import type { AlphaCatalog } from "../alphaCatalog";
import { coreFetch } from "../auth/coreFetch";

type FinancialResearchReadiness =
  | "ready"
  | "ready_with_pending"
  | "ready_with_gaps"
  | "not_ready";

export type FieldFamilyAvailability = {
  family_id: string;
  research_category: "market" | "financial";
  source_endpoints: string[];
  supported_field_ids: string[];
  available_field_ids: string[];
  coverage_start: string | null;
  coverage_end: string | null;
  readiness: FinancialResearchReadiness | "partial";
};

export type DataOverview = {
  generation_manifest_sha256: string | null;
  available_field_ids: string[];
  field_families: FieldFamilyAvailability[];
  market_coverage: { start: string; end: string } | null;
  financial_coverage: {
    start: string;
    discovery_baseline_session: string;
    discovery_attempted_through_session: string;
    discovery_complete_through_session: string;
    historical_reconciliation_watermark: string;
    revision_coverage: string;
    seed_policy: string;
    readiness_status: Exclude<FinancialResearchReadiness, "not_ready">;
    pending_instrument_count: number;
    discovery_gap_count: number;
    earliest_unresolved_date: string | null;
    sparse_facts: boolean;
  } | null;
  industry_coverage: {
    start: string;
    observation_through_session: string;
    classification_version: "SW2021";
  } | null;
  benchmark_coverage: { start: string; end: string } | null;
  benchmark_snapshot_sha256: string | null;
  benchmark_last_published_at: string | null;
  data_through_session: string | null;
  last_market_refresh_at: string | null;
  last_financial_refresh_at: string | null;
  last_industry_refresh_at: string | null;
  industry_refresh_status: "running" | "succeeded" | "failed" | null;
  industry_refresh_failure_code: string | null;
  market_research_readiness: boolean;
  benchmark_research_readiness: boolean;
  financial_research_readiness: FinancialResearchReadiness;
  industry_research_readiness: boolean;
};

export type DataSnapshot = DataOverview & { catalog: AlphaCatalog };

export async function loadDataSnapshot(request: typeof fetch = coreFetch, signal?: AbortSignal): Promise<DataSnapshot> {
  const response = await request("/api/data", { signal });
  if (!response.ok) throw new Error("Data unavailable");
  return await response.json() as DataSnapshot;
}

export const dataSnapshotQuery = queryOptions({
  queryKey: ["workspace", "data"],
  queryFn: ({ signal }) => loadDataSnapshot(coreFetch, signal),
});
