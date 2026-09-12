import { ArrowClockwise } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";

import type { AlphaCatalog, AlphaCatalogField } from "../alphaCatalog";
import { coreFetch } from "../auth/coreFetch";
import { STRATEGY_BENCHMARK_DISPLAY_NAME } from "../benchmark";

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
  | { resources: null; error: string };

const RESEARCH_CATEGORIES = [
  {
    category: "market",
    id: "market-data-fields",
    title: "Market data fields",
  },
  {
    category: "financial",
    id: "financial-data-fields",
    title: "Financial data fields",
  },
] as const;

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
    return { resources: null, error: "Data unavailable" };
  }
}

export function DataOverviewView({
  catalog,
  overview,
  onRefresh,
}: {
  catalog: AlphaCatalog;
  overview: DataOverview;
  onRefresh: () => void;
}) {
  const marketCoverage = overview.market_coverage;
  const benchmarkCoverage = overview.benchmark_coverage;
  const financialCoverage = overview.financial_coverage;
  const industryCoverage = overview.industry_coverage;
  const industryState = overview.industry_refresh_status === "failed"
    ? "Last refresh failed"
    : overview.industry_research_readiness
      ? "Industry ready"
      : industryCoverage === null
        ? "Industry not ready"
        : "Industry stale";
  const marketFamilies = overview.field_families.filter((family) => family.research_category === "market");
  const financialFamilies = overview.field_families.filter((family) => family.research_category === "financial");
  const marketState = categoryReadiness(marketFamilies);
  const financialState = {
    ready: "Finance ready",
    ready_with_pending: "Finance ready with pending instruments",
    ready_with_gaps: "Finance ready with discovery gaps",
    not_ready: "Finance not ready",
    partial: "Finance partially ready",
  }[categoryReadiness(financialFamilies)];
  return (
    <section aria-label="Data" className="page-section data-page">
      <header className="page-hero">
        <div>
          <h1>Data overview</h1>
        </div>
        <div className="hero-actions">
          <button className="button button-quiet" onClick={onRefresh} type="button">
            <ArrowClockwise aria-hidden="true" size={17} weight="regular" />
            Reload
          </button>
        </div>
      </header>
      <div className="signal-strip" aria-label="Market data readiness">
        <span className="signal-strip-label"><span className={marketState === "ready"
          ? "health-dot" : "health-dot health-dot-warning"} /> Market data</span>
        <strong>{marketState === "ready" ? "Market ready"
          : marketState === "not_ready" ? "Market not ready" : "Market partially ready"}</strong>
      </div>
      <FamilyAvailabilityRows families={marketFamilies} />
      <dl className="data-overview-stats" aria-label="Market data coverage">
        <div>
          <dt>Market coverage start</dt>
          <dd>{marketCoverage?.start ?? "Not available"}</dd>
        </div>
        <div>
          <dt>Market coverage end</dt>
          <dd>{marketCoverage?.end ?? "Not available"}</dd>
        </div>
        <div>
          <dt>Data through</dt>
          <dd>{overview.data_through_session ?? "Not available"}</dd>
        </div>
        <div>
          <dt>Last market refresh</dt>
          <dd>{overview.last_market_refresh_at ?? "Not available"}</dd>
        </div>
      </dl>
      <div className="signal-strip" aria-label="Strategy Benchmark readiness">
        <span className="signal-strip-label">
          <span
            aria-hidden="true"
            className={overview.benchmark_research_readiness
              ? "health-dot"
              : "health-dot health-dot-warning"}
          /> Strategy Benchmark
        </span>
        <strong>
          {overview.benchmark_research_readiness
            ? `${STRATEGY_BENCHMARK_DISPLAY_NAME} ready`
            : `${STRATEGY_BENCHMARK_DISPLAY_NAME} not ready`}
        </strong>
      </div>
      <dl className="data-overview-stats" aria-label="Strategy Benchmark snapshot">
        <div>
          <dt>Benchmark coverage start</dt>
          <dd>{benchmarkCoverage?.start ?? "Not available"}</dd>
        </div>
        <div>
          <dt>Benchmark coverage end</dt>
          <dd>{benchmarkCoverage?.end ?? "Not available"}</dd>
        </div>
        <div>
          <dt>Snapshot SHA-256</dt>
          <dd>{overview.benchmark_snapshot_sha256 === null
            ? "Not available"
            : <code>{overview.benchmark_snapshot_sha256}</code>}</dd>
        </div>
        <div>
          <dt>Last benchmark publication</dt>
          <dd>{overview.benchmark_last_published_at ?? "Not available"}</dd>
        </div>
      </dl>
      <div className="signal-strip" aria-label="Financial data readiness">
        <span className="signal-strip-label"><span className={categoryReadiness(financialFamilies) === "ready"
          ? "health-dot" : "health-dot health-dot-warning"} /> Financial data</span>
        <strong>{financialState}</strong>
      </div>
      <FamilyAvailabilityRows families={financialFamilies} />
      <dl className="data-overview-stats" aria-label="Financial data coverage">
        <div>
          <dt>Financial coverage start</dt>
          <dd>{financialCoverage?.start ?? "Not available"}</dd>
        </div>
        <div>
          <dt>Discovery baseline</dt>
          <dd>{financialCoverage?.discovery_baseline_session ?? "Not available"}</dd>
        </div>
        <div>
          <dt>Attempted through</dt>
          <dd>{financialCoverage?.discovery_attempted_through_session ?? "Not available"}</dd>
        </div>
        <div>
          <dt>Complete through</dt>
          <dd>{financialCoverage?.discovery_complete_through_session ?? "Not available"}</dd>
        </div>
        <div>
          <dt>Last financial refresh</dt>
          <dd>{overview.last_financial_refresh_at ?? "Not available"}</dd>
        </div>
        <div>
          <dt>Pending instruments</dt>
          <dd>{financialCoverage?.pending_instrument_count ?? "Not available"}</dd>
        </div>
        <div>
          <dt>Discovery gaps</dt>
          <dd>{financialCoverage?.discovery_gap_count ?? "Not available"}</dd>
        </div>
        <div>
          <dt>Earliest unresolved</dt>
          <dd>{financialCoverage?.earliest_unresolved_date ?? "Not available"}</dd>
        </div>
      </dl>
      <div className="signal-strip" aria-label="Industry data readiness">
        <span className="signal-strip-label"><span className="health-dot" /> Industry data</span>
        <strong>{industryState}</strong>
      </div>
      <dl className="data-overview-stats" aria-label="Industry data coverage">
        <div>
          <dt>Industry coverage start</dt>
          <dd>{industryCoverage?.start ?? "Not available"}</dd>
        </div>
        <div>
          <dt>Observed through</dt>
          <dd>{industryCoverage?.observation_through_session ?? "Not available"}</dd>
        </div>
        <div>
          <dt>Classification</dt>
          <dd>{industryCoverage?.classification_version ?? "Not available"}</dd>
        </div>
        <div>
          <dt>Last industry refresh</dt>
          <dd>{overview.last_industry_refresh_at ?? "Not available"}</dd>
        </div>
      </dl>
      {overview.industry_refresh_failure_code === null ? null : (
        <p className="data-coverage-note">
          Latest Industry Refresh failure: <code>{overview.industry_refresh_failure_code}</code>
        </p>
      )}
      <ResearchFieldCatalog catalog={catalog} />
    </section>
  );
}

function categoryReadiness(families: FieldFamilyAvailability[]): FieldFamilyAvailability["readiness"] {
  if (!families.some((family) => family.available_field_ids.length > 0)) return "not_ready";
  if (families.some((family) => family.readiness === "partial" || family.readiness === "not_ready")) return "partial";
  if (families.some((family) => family.readiness === "ready_with_gaps")) return "ready_with_gaps";
  if (families.some((family) => family.readiness === "ready_with_pending")) return "ready_with_pending";
  return "ready";
}

function FamilyAvailabilityRows({ families }: { families: FieldFamilyAvailability[] }) {
  return <ul className="data-family-availability">
    {families.map((family) => <li key={family.family_id}>
      <span>{family.source_endpoints.join(", ")}</span>
      <span>{family.available_field_ids.length} / {family.supported_field_ids.length} fields</span>
      <span>{family.coverage_start ?? "No coverage"} — {family.coverage_end ?? "No coverage"}</span>
      <span>{humanizeContract(family.readiness)}</span>
    </li>)}
  </ul>;
}

function ResearchFieldCatalog({ catalog }: { catalog: AlphaCatalog }) {
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState({
    research_purpose: "",
    source_endpoint: "",
    report_period_selection: "",
  });
  const query = search.trim().toLocaleLowerCase();
  const visible = catalog.fields.filter((field) => (
    [field.identifier, field.display_name, field.description].some(
      (value) => value.toLocaleLowerCase().includes(query),
    ) && Object.entries(filters).every(([key, value]) => (
      value === "" || field[key as keyof typeof filters] === value
    ))
  ));
  const filterDefinitions = [
    { key: "research_purpose", label: "Research purpose" },
    { key: "source_endpoint", label: "Field source" },
    { key: "report_period_selection", label: "Field period" },
  ] as const;
  return (
    <section aria-labelledby="research-fields-title" className="data-field-catalog">
      <header>
        <h2 id="research-fields-title">Research fields</h2>
        <span>{catalog.fields.length} available</span>
      </header>
      <div className="data-field-filters">
        <label>
          <span>Search fields</span>
          <input aria-label="Search fields" onChange={(event) => setSearch(event.target.value)}
            placeholder="中文 / DSL name" type="search" value={search} />
        </label>
        {filterDefinitions.map(({ key, label }) => (
          <label key={key}>
            <span>{label}</span>
            <select aria-label={label} value={filters[key]}
              onChange={(event) => setFilters((current) => ({ ...current, [key]: event.target.value }))}>
              <option value="">All</option>
              {[...new Set(catalog.fields.map((field) => field[key]))].sort().map((value) => (
                <option key={value} value={value}>{humanizeContract(value)}</option>
              ))}
            </select>
          </label>
        ))}
      </div>
      {RESEARCH_CATEGORIES.map((dataset) => {
        const fields = visible.filter((field) => field.research_category === dataset.category);
        return (
          <section aria-labelledby={dataset.id} className="data-field-dataset" key={dataset.category}>
            <header>
              <h3 id={dataset.id}>{dataset.title}</h3>
              <span>{fields.length} {fields.length === 1 ? "field" : "fields"}</span>
            </header>
            {fields.length > 0 ? <FieldTable fields={fields} title={dataset.title} /> : (
              <p className="data-field-empty">{query || Object.values(filters).some(Boolean)
                ? "No fields match these filters."
                : "No fields are currently available for research."}</p>
            )}
          </section>
        );
      })}
    </section>
  );
}

function FieldTable({ fields, title }: { fields: AlphaCatalogField[]; title: string }) {
  return (
    <div className="data-field-table-scroll">
      <table className="data-field-table">
        <caption className="visually-hidden">{title}</caption>
        <thead>
          <tr>
            <th scope="col">Formula field</th>
            <th scope="col">Meaning</th>
            <th scope="col">Research-time value</th>
            <th scope="col">Unit</th>
          </tr>
        </thead>
        <tbody>
          {fields.map((field) => (
            <tr key={field.field_id}>
              <th scope="row">
                <code>{field.identifier}</code>
                <small>{field.field_id}</small>
                {field.example !== "" ? <small>Example: <code>{field.example}</code></small> : null}
              </th>
              <td>
                <strong>{field.display_name}</strong>
                <span>{field.description}</span>
                <small>{field.source_endpoint}.{field.source_column} · {field.research_purpose}</small>
                <small>{humanizeContract(field.missingness)}</small>
              </td>
              <td>
                <span>{fieldTimeSemantics(field)}</span>
                <small>{humanizeContract(field.availability)}</small>
                <small>{field.applicable_company_types.length > 0
                  ? `Company types ${field.applicable_company_types.join(", ")}`
                  : "All supported instruments"}</small>
              </td>
              <td>
                <code>{field.unit}</code>
                <small>Source unit: {field.source_unit}</small>
                <small>{humanizeContract(field.reporting_scope)}</small>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function fieldTimeSemantics(field: AlphaCatalogField): string {
  if (field.report_period_selection === "latest_visible_full_year") {
    return "Latest full year visible on each Research Session";
  }
  if (field.report_period_selection === "latest_visible_quarterly_or_annual") {
    return "Latest quarterly or annual report visible on each Research Session";
  }
  return humanizeContract(field.report_period_selection);
}

function humanizeContract(value: string): string {
  const text = value.replaceAll("_", " ").replaceAll("-", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function DataPage() {
  const [resources, setResources] = useState<DataPageResources | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const result = await loadDataPage();
    if (result.resources !== null) setResources(result.resources);
    setError(result.error);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (error) return (
    <section aria-label="Data" className="page-section state-section">
      <p role="alert">{error}</p>
      <button onClick={() => void refresh()} type="button">Retry</button>
    </section>
  );
  if (!resources) {
    return <section aria-label="Data" className="page-section state-section"><p>Loading Data…</p></section>;
  }
  return (
    <DataOverviewView
      catalog={resources.catalog}
      onRefresh={() => void refresh()}
      overview={resources.overview}
    />
  );
}
