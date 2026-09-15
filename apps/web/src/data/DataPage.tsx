import { ArrowClockwise, Copy, MagnifyingGlass, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";

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
  const financial = overview.financial_coverage;
  const marketFamilies = overview.field_families.filter((family) => family.research_category === "market");
  const financialFamilies = overview.field_families.filter((family) => family.research_category === "financial");
  const industryState = overview.industry_research_readiness ? "ready"
    : overview.industry_coverage ? "partial" : "not_ready";
  const rows = [
    { name: "Market data", description: "Prices, volume & valuation", coverage: overview.market_coverage,
      state: categoryReadiness(marketFamilies), families: marketFamilies },
    { name: "Financial data", description: "Statements & financial indicators",
      coverage: financial ? { start: financial.start, end: financial.discovery_complete_through_session } : null,
      state: categoryReadiness(financialFamilies), families: financialFamilies },
    { name: "Industry data", description: "SW2021 classification",
      coverage: overview.industry_coverage ? { start: overview.industry_coverage.start,
        end: overview.industry_coverage.observation_through_session } : null,
      state: industryState, families: [] },
    { name: "Strategy benchmark", description: STRATEGY_BENCHMARK_DISPLAY_NAME,
      coverage: overview.benchmark_coverage,
      state: overview.benchmark_research_readiness ? "ready" : "not_ready", families: [] },
  ];
  return (
    <section aria-label="Data" className="page-section data-page">
      <header className="page-hero">
        <div><h1>Data</h1><p>Explore available data and find fields for your research.</p></div>
        <button className="button button-quiet" onClick={onRefresh} type="button">
          <ArrowClockwise aria-hidden="true" size={17} /> Reload status
        </button>
      </header>
      <section className="data-coverage" aria-labelledby="data-coverage-title">
        <header><h2 id="data-coverage-title">Data coverage</h2>
          <p>Availability refers to the published data range.</p></header>
        <div className="data-coverage-head" aria-hidden="true"><span>Dataset</span><span>Available range</span><span>Research availability</span></div>
        {rows.map((row) => <div className="data-coverage-row" key={row.name}>
          <div><h3>{row.name}</h3><p>{row.description}</p></div>
          <div className="data-coverage-range"><span className="visually-hidden">Available range: </span>
            {row.coverage ? `${row.coverage.start} — ${row.coverage.end}` : "No published coverage"}</div>
          <div className="data-availability"><span aria-hidden="true" className={row.state === "ready" ? "health-dot" : "health-dot health-dot-warning"} />
            {row.state === "ready" ? "Available" : row.state === "not_ready" ? "Not available" : "Limited coverage"}</div>
          {row.state !== "ready" && row.families.length > 0 && <p className="data-coverage-limitation">
            {row.families.filter((family) => family.readiness !== "ready").map((family) =>
              `${family.available_field_ids.length} of ${family.supported_field_ids.length} fields available${family.coverage_end ? ` through ${family.coverage_end}` : ""}`).join("; ")}.
            {row.name === "Financial data" && financial && ` Financial data has ${financial.pending_instrument_count} instruments awaiting verification and ${financial.discovery_gap_count} gaps in publication checks${financial.earliest_unresolved_date ? `, starting ${financial.earliest_unresolved_date}` : ""}. Values may be missing or incomplete.`}
          </p>}
        </div>)}
        <p className="data-coverage-footnote">{overview.data_through_session ? `Data through ${overview.data_through_session}. ` : "No published data date. "}
          Field availability varies by instrument and date.</p>
      </section>
      <ResearchFieldCatalog catalog={catalog} />
      <CommonInputCatalog catalog={catalog} />
    </section>
  );
}

function CommonInputCatalog({ catalog }: { catalog: AlphaCatalog }) {
  const inputs = catalog.builtins.filter((builtin) => builtin.result_type === "common_series");
  if (inputs.length === 0) return null;
  return (
    <details className="data-field-catalog data-common-inputs">
      <summary>Common market inputs <span>{inputs.length} expressions</span></summary>
      <p>Calculated from historical members of your selected research Universe. Industry inputs use its SW2021 L1 subset, not a full industry or official index. Selecting an industry here does not change the stock selection Universe.</p>
      <div className="data-field-table-scroll">
        <table className="data-field-table">
          <caption className="visually-hidden">Common market expressions</caption>
          <thead><tr><th scope="col">Expression</th><th scope="col">Meaning</th><th scope="col">Missing values</th></tr></thead>
          <tbody>{inputs.map((input) => (
            <tr key={input.identifier}>
              <th scope="row"><code>{input.identifier}({input.parameters.map((parameter) => parameter.name).join(", ")})</code></th>
              <td>{input.description}<small>{input.examples.join(" · ")}</small></td>
              <td>{input.missing_value_behavior}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <details>
        <summary>SW2021 L1 industry parameters ({catalog.industries.length})</summary>
        <p>These codes identify industries; data coverage is checked for the chosen research period.</p>
        <ul>{catalog.industries.map((industry) => <li key={industry.code}><code>{industry.code}</code> {industry.name}</li>)}</ul>
      </details>
    </details>
  );
}

function categoryReadiness(families: FieldFamilyAvailability[]): FieldFamilyAvailability["readiness"] {
  if (!families.some((family) => family.available_field_ids.length > 0)) return "not_ready";
  if (families.some((family) => family.readiness === "partial" || family.readiness === "not_ready")) return "partial";
  if (families.some((family) => family.readiness === "ready_with_gaps")) return "ready_with_gaps";
  if (families.some((family) => family.readiness === "ready_with_pending")) return "ready_with_pending";
  return "ready";
}

const PAGE_SIZE = 25;

const PURPOSE_LABELS: Record<string, string> = {
  "估值": "Valuation",
  "利润与现金流基础值": "Earnings & cash flow fundamentals",
  "利润与现金流金额": "Earnings & cash flow amounts",
  "单季度增长": "Quarterly growth",
  "单季度指标": "Quarterly metrics",
  "同比增长": "Year-over-year growth",
  "收入与利润结构": "Revenue & earnings composition",
  "每股指标": "Per-share metrics",
  "流动性": "Liquidity",
  "现金流": "Cash flow",
  "现金流与资本支出比率": "Cash flow & capital expenditure ratios",
  "盈利": "Earnings",
  "盈利能力": "Profitability",
  "股息": "Dividends",
  "股本": "Share capital",
  "营运效率": "Operating efficiency",
  "行情": "Market prices",
  "财务结构与偿债": "Capital structure & solvency",
  "资产与资本基础值": "Asset & capital fundamentals",
  "资产负债": "Balance sheet",
  "较年初增长": "Year-to-date growth"
};

export function ResearchFieldCatalog({ catalog }: { catalog: AlphaCatalog }) {
  const [search, setSearch] = useState("");
  const searchInput = useRef<HTMLInputElement>(null);
  const [category, setCategory] = useState("");
  const [purpose, setPurpose] = useState("");
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const query = search.trim().toLocaleLowerCase();
  const visible = catalog.fields.filter((field) => (
    (!category || field.research_category === category) &&
    [field.identifier, field.display_name, field.description].some((value) => value.toLocaleLowerCase().includes(query)) &&
    (!purpose || field.research_purpose === purpose)
  ));
  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pageFields = visible.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);
  const selected = pageFields.find((field) => field.field_id === selectedId) ?? pageFields[0];
  return <section aria-labelledby="research-fields-title" className="data-field-catalog data-explorer">
    <header><h2 id="research-fields-title">Research fields</h2><span>{catalog.fields.length} fields</span></header>
    <div className="data-search"><MagnifyingGlass aria-hidden="true" size={20} />
      <label className="visually-hidden" htmlFor="data-field-search">Search fields</label>
      <input id="data-field-search" ref={searchInput} onChange={(event) => { setSearch(event.target.value); setPage(1); }}
        placeholder="Search by name, meaning or formula…" type="text" role="searchbox" value={search} />
      {search !== "" && <button className="button button-quiet data-search-clear" type="button" aria-label="Clear search"
        onClick={() => { setSearch(""); setPage(1); searchInput.current?.focus(); }}>
        <X aria-hidden="true" size={16} />
      </button>}
    </div>
    <div className="data-field-filters">
      <div className="data-categories" role="group" aria-label="Field category">
        {[{ value: "", label: "All fields" }, { value: "market", label: "Market" }, { value: "financial", label: "Financial" }].map((item) =>
          <button className="button button-quiet" type="button" key={item.value} aria-pressed={category === item.value}
            onClick={() => { setCategory(item.value); setPage(1); }}>
            {item.label}{item.value && <span>{catalog.fields.filter((field) => field.research_category === item.value).length}</span>}
          </button>)}
      </div>
      <label>
        <span className="visually-hidden">Research purpose</span>
        <select value={purpose} onChange={(event) => { setPurpose(event.target.value); setPage(1); }}>
          <option value="">All purposes</option>
          {[...new Set(catalog.fields.map((field) => field.research_purpose))].sort((a, b) => PURPOSE_LABELS[a].localeCompare(PURPOSE_LABELS[b])).map((value) =>
            <option key={value} value={value}>{PURPOSE_LABELS[value]}</option>)}
        </select>
      </label>
    </div>
    {pageFields.length ? <div className="data-explorer-layout">
      <div className="data-field-results">
        <div className="data-field-dataset data-field-table-scroll">
          <table className="data-field-table data-explorer-table">
            <caption className="visually-hidden">Research fields</caption>
            <thead><tr><th scope="col">Field</th><th scope="col">Formula name</th><th scope="col">Unit</th></tr></thead>
            <tbody>{pageFields.map((field) => <tr key={field.field_id} onClick={() => setSelectedId(field.field_id)}
              className={selected?.field_id === field.field_id ? "is-selected" : undefined}>
              <th scope="row"><button type="button" aria-pressed={selected?.field_id === field.field_id}
                aria-controls="data-field-detail">
                <span>{field.display_name}</span></button></th>
              <td><code>{field.identifier}</code></td><td><code>{field.unit}</code></td>
            </tr>)}</tbody>
          </table>
        </div>
        <nav className="data-pagination" aria-label="Field pages">
          <span role="status">Showing {(currentPage - 1) * PAGE_SIZE + 1}–{Math.min(currentPage * PAGE_SIZE, visible.length)} of {visible.length}</span>
          <div><button className="button button-quiet" type="button" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>Previous</button>
            <span>{currentPage} / {pageCount}</span>
            <button className="button button-quiet" type="button" disabled={currentPage === pageCount} onClick={() => setPage(currentPage + 1)}>Next</button></div>
        </nav>
      </div>
      {selected && <FieldDetail key={selected.field_id} field={selected} />}
    </div> : <p className="data-field-empty" role="status">{catalog.fields.length ? "No fields match these filters." : "No fields are currently available for research."}</p>}
  </section>;
}

function FieldDetail({ field }: { field: AlphaCatalogField }) {
  const [copyStatus, setCopyStatus] = useState("");
  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); setCopyStatus("Copied"); }
    catch { setCopyStatus("Copy unavailable. Select and copy the text."); }
  }
  return <aside id="data-field-detail" aria-label="Field details" className="data-field-detail">
    <h3>{field.display_name}</h3>
    <div className="data-copy"><code>{field.identifier}</code><button className="button button-quiet" type="button" aria-label="Copy formula name" onClick={() => void copy(field.identifier)}><Copy aria-hidden="true" size={16} /></button></div>
    <p>{field.description}</p>
    <dl><div><dt>Unit</dt><dd>{field.unit}</dd></div>
      <div><dt>Period</dt><dd>{fieldTimeSemantics(field)}</dd></div>
      <div><dt>Available at</dt><dd>{humanizeContract(field.availability)}</dd></div>
      <div><dt>Missing values</dt><dd>{humanizeContract(field.missingness)}</dd></div>
      <div><dt>Applies to</dt><dd>{field.applicable_company_types.length ? `Company types ${field.applicable_company_types.join(", ")}` : "All supported instruments"}</dd></div></dl>
    {field.example && <div className="data-example"><span>Example</span><div className="data-copy"><code>{field.example}</code><button className="button button-quiet" type="button" aria-label="Copy example" onClick={() => void copy(field.example)}><Copy aria-hidden="true" size={16} /></button></div></div>}
    <p role="status" className="data-copy-status">{copyStatus}</p>

  </aside>;
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
