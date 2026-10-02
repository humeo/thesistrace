import { Page, PageHeader, PageContent } from "../components/layout/Page";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Alert, AlertDescription } from "../components/ui/alert";
import { InfoHelp } from "../components/product/InfoHelp";
import { ArrowClockwise, ChartLineUp, Database, FileText, Stack } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";

import type { AlphaCatalog } from "../alphaCatalog";
import { coreFetch } from "../auth/coreFetch";
import { useTranslation } from "../i18n";
import { catalogLabel } from "../i18n/catalog";
import { DataDirectory } from "./DataDirectory";
export { ResearchFieldCatalog } from "./DataDirectory";

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

type DataPageResources = {
  overview: DataOverview;
  catalog: AlphaCatalog;
};

export type DataPageLoad =
  | { resources: DataPageResources; error: null }
  | { resources: null; error: "unavailable" };

export async function loadDataPage(
  request: typeof fetch = coreFetch,
): Promise<DataPageLoad> {
  try {
    const response = await request("/api/data");
    if (!response.ok) {
      throw new Error("Data unavailable");
    }
    const { catalog, ...overview } = await response.json() as DataSnapshot;
    return { resources: { overview, catalog }, error: null };
  } catch {
    return { resources: null, error: "unavailable" };
  }
}

export function DataOverviewView({
  catalog,
  overview,
  onRefresh,
  refreshing = false,
  error,
}: {
  catalog: AlphaCatalog;
  overview: DataOverview;
  onRefresh: () => void;
  refreshing?: boolean;
  error?: "unavailable" | null;
}) {
  const { t } = useTranslation("data");
  const financial = overview.financial_coverage;
  const marketFamilies = overview.field_families.filter((family) => family.research_category === "market");
  const financialFamilies = overview.field_families.filter((family) => family.research_category === "financial");
  const industryState = overview.industry_research_readiness ? "ready"
    : overview.industry_coverage ? "partial" : "not_ready";
  const rows = [
    { id: "market" as const, icon: <ChartLineUp aria-hidden="true" />, description: t("marketDescription"), detail: null, coverage: overview.market_coverage,
      state: categoryReadiness(marketFamilies), families: marketFamilies },
    { id: "financial" as const, icon: <FileText aria-hidden="true" />, description: t("financialDescription"),
      detail: null,
      coverage: financial ? { start: financial.start, end: financial.discovery_complete_through_session } : null,
      state: categoryReadiness(financialFamilies), families: financialFamilies },
    { id: "industry" as const, icon: <Stack aria-hidden="true" />, description: t("industryDescription"),
      detail: overview.industry_coverage?.classification_version ?? null,
      coverage: overview.industry_coverage ? { start: overview.industry_coverage.start,
        end: overview.industry_coverage.observation_through_session } : null,
      state: industryState, families: [] },
    { id: "benchmark" as const, icon: <Database aria-hidden="true" />, description: catalogLabel("benchmarks", "csi300-price-index-open"),
      detail: catalogLabel("benchmarks", "csi300-price-index-open"),
      coverage: overview.benchmark_coverage,
      state: overview.benchmark_research_readiness ? "ready" : "not_ready", families: [] },
  ];
  return <Page className="console-workspace" aria-label={t("title")}><PageContent className="flex flex-col gap-7">
    <PageHeader variant="console" className="mb-0" title={t("title")} description={t("introduction")} actions={<Button variant="outline" onClick={onRefresh} disabled={refreshing}><ArrowClockwise aria-hidden="true" data-icon="inline-start" />{t("reload")}</Button>} />
    {error && <Alert variant="destructive"><AlertDescription>{t(error)}</AlertDescription></Alert>}
    <section aria-label={t("coverage")} className="data-coverage-grid grid gap-3">
      {rows.map(row => <div key={row.id} className="flex min-h-20 min-w-0 items-center gap-3 rounded-xl border border-border bg-card p-4">
        <span className="data-coverage-icon" aria-hidden="true">{row.icon}</span><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <div className="flex items-center gap-1">
            <h2 className="m-0 text-sm font-semibold">{t(`${row.id}Title`)}</h2>
            <InfoHelp label={t(`${row.id}Title`)} buttonLabel={`${t(`${row.id}Title`)} · ${t("coverageHint")}`}>
              {[row.description, row.detail, t("availabilityVaries")].filter(Boolean).join(" ")}
            </InfoHelp>
          </div>
          <Badge variant={row.state === "ready" ? "success" : "outline"}>{t(row.state === "ready" ? "available" : row.state === "not_ready" ? "notAvailable" : "limitedCoverage")}</Badge>
        </div>
        <div className="mt-1 text-sm text-muted-foreground tabular-nums">{row.coverage ? `${row.coverage.start} — ${row.coverage.end}` : t("noCoverage")}</div>
        {row.state !== "ready" && row.families.length > 0 && <p className="mb-0 mt-2 text-xs text-muted-foreground">
          {row.families.filter(family => family.readiness !== "ready").map(family =>
            t("familyAvailability", { available: family.available_field_ids.length, total: family.supported_field_ids.length }) + (family.coverage_end ? t("through", { date: family.coverage_end }) : "")).join("; ")}.{" "}
          {row.id === "financial" && financial && <>{t("financialPending", { pending: financial.pending_instrument_count, gaps: financial.discovery_gap_count })}{" "}{financial.earliest_unresolved_date && t("earliestGap", { date: financial.earliest_unresolved_date })}{" "}{t("incompleteValues")}</>}
        </p>}</div>
      </div>)}
    </section>
    <DataDirectory catalog={catalog} />
  </PageContent></Page>;
}

function categoryReadiness(families: FieldFamilyAvailability[]): FieldFamilyAvailability["readiness"] {
  if (!families.some((family) => family.available_field_ids.length > 0)) return "not_ready";
  if (families.some((family) => family.readiness === "partial" || family.readiness === "not_ready")) return "partial";
  if (families.some((family) => family.readiness === "ready_with_gaps")) return "ready_with_gaps";
  if (families.some((family) => family.readiness === "ready_with_pending")) return "ready_with_pending";
  return "ready";
}

export function DataPage() {
  const { t } = useTranslation("data");
  const [resources, setResources] = useState<DataPageResources | null>(null);
  const [error, setError] = useState<"unavailable" | null>(null);

  const [refreshing, setRefreshing] = useState(false);
  const refreshingRef = useRef(false);
  const refresh = useCallback(async () => {
    if (refreshingRef.current) return;
    refreshingRef.current = true;
    setRefreshing(true);
    const result = await loadDataPage();
    if (result.resources !== null) setResources(result.resources);
    setError(result.error);
    refreshingRef.current = false;
    setRefreshing(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (!resources) return <Page className="console-workspace" aria-label={t("title")}><PageContent>
    <PageHeader variant="console" title={t("title")} />
    {error ? <Alert variant="destructive"><AlertDescription>{t(error)}<Button variant="outline" disabled={refreshing} onClick={() => void refresh()}>{t("retry")}</Button></AlertDescription></Alert> : <p role="status">{t("loading")}</p>}
  </PageContent></Page>;
  return <DataOverviewView catalog={resources.catalog} overview={resources.overview} error={error} refreshing={refreshing} onRefresh={() => void refresh()} />;
}
