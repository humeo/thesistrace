import { ArrowClockwise, Copy, MagnifyingGlass, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";

import type { AlphaCatalog, AlphaCatalogField } from "../alphaCatalog";
import { coreFetch } from "../auth/coreFetch";
import { useTranslation } from "../i18n";
import { builtinDisplay, catalogLabel, compareResearchPurposes, fieldDisplay, matchesResearchField } from "../i18n/catalog";

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
}: {
  catalog: AlphaCatalog;
  overview: DataOverview;
  onRefresh: () => void;
}) {
  const { t } = useTranslation("data");
  const financial = overview.financial_coverage;
  const marketFamilies = overview.field_families.filter((family) => family.research_category === "market");
  const financialFamilies = overview.field_families.filter((family) => family.research_category === "financial");
  const industryState = overview.industry_research_readiness ? "ready"
    : overview.industry_coverage ? "partial" : "not_ready";
  const rows = [
    { id: "market" as const, description: t("marketDescription"), coverage: overview.market_coverage,
      state: categoryReadiness(marketFamilies), families: marketFamilies },
    { id: "financial" as const, description: t("financialDescription"),
      coverage: financial ? { start: financial.start, end: financial.discovery_complete_through_session } : null,
      state: categoryReadiness(financialFamilies), families: financialFamilies },
    { id: "industry" as const, description: t("industryDescription"),
      coverage: overview.industry_coverage ? { start: overview.industry_coverage.start,
        end: overview.industry_coverage.observation_through_session } : null,
      state: industryState, families: [] },
    { id: "benchmark" as const, description: catalogLabel("benchmarks", "csi300-price-index-open"),
      coverage: overview.benchmark_coverage,
      state: overview.benchmark_research_readiness ? "ready" : "not_ready", families: [] },
  ];
  return (
    <section aria-label={t("title")} className="page-section data-page">
      <header className="page-hero">
        <div><h1>{t("title")}</h1><p>{t("introduction")}</p></div>
        <button className="button button-quiet" onClick={onRefresh} type="button">
          <ArrowClockwise aria-hidden="true" size={17} /> {t("reload")}
        </button>
      </header>
      <section className="data-coverage" aria-labelledby="data-coverage-title">
        <header><h2 id="data-coverage-title">{t("coverage")}</h2>
          <p>{t("coverageHint")}</p></header>
        <div className="data-coverage-head" aria-hidden="true"><span>{t("dataset")}</span><span>{t("availableRange")}</span><span>{t("researchAvailability")}</span></div>
        {rows.map((row) => <div className="data-coverage-row" key={row.id}>
          <div><h3>{t(`${row.id}Title`)}</h3><p>{row.description}</p></div>
          <div className="data-coverage-range"><span className="visually-hidden">{t("availableRange")}: </span>
            {row.coverage ? `${row.coverage.start} — ${row.coverage.end}` : t("noCoverage")}</div>
          <div className="data-availability"><span aria-hidden="true" className={row.state === "ready" ? "health-dot" : "health-dot health-dot-warning"} />
            {t(row.state === "ready" ? "available" : row.state === "not_ready" ? "notAvailable" : "limitedCoverage")}</div>
          {row.state !== "ready" && row.families.length > 0 && <p className="data-coverage-limitation">
            {row.families.filter((family) => family.readiness !== "ready").map((family) =>
              t("familyAvailability", { available: family.available_field_ids.length, total: family.supported_field_ids.length }) + (family.coverage_end ? t("through", { date: family.coverage_end }) : "")).join("; ")}.{" "}
            {row.id === "financial" && financial && <>{t("financialPending", { pending: financial.pending_instrument_count, gaps: financial.discovery_gap_count })}{" "}
              {financial.earliest_unresolved_date && t("earliestGap", { date: financial.earliest_unresolved_date })}{" "}{t("incompleteValues")}</>}
          </p>}
        </div>)}
        <p className="data-coverage-footnote">{overview.data_through_session ? t("dataThrough", { date: overview.data_through_session }) : t("noDataDate")}{" "}
          {t("availabilityVaries")}</p>
      </section>
      <ResearchFieldCatalog catalog={catalog} />
      <CommonInputCatalog catalog={catalog} />
    </section>
  );
}

function CommonInputCatalog({ catalog }: { catalog: AlphaCatalog }) {
  const { t } = useTranslation("data");
  const inputs = catalog.builtins.filter((builtin) => builtin.result_type === "common_series");
  if (inputs.length === 0) return null;
  return (
    <details className="data-field-catalog data-common-inputs">
      <summary>{t("commonInputs")} <span>{t("expressions", { total: inputs.length })}</span></summary>
      <p>{t("commonInputHint")}</p>
      <div className="data-field-table-scroll">
        <table className="data-field-table">
          <caption className="visually-hidden">{t("commonExpressions")}</caption>
          <thead><tr><th scope="col">{t("expression")}</th><th scope="col">{t("meaning")}</th><th scope="col">{t("missingValues")}</th></tr></thead>
          <tbody>{inputs.map((input) => (
            <tr key={input.identifier}>
              <th scope="row"><code>{input.identifier}({input.parameters.map((parameter) => parameter.name).join(", ")})</code></th>
              <td>{builtinDisplay(input.identifier).description}<small>{input.examples.join(" · ")}</small></td>
              <td>{builtinDisplay(input.identifier).missing}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <details>
        <summary>{t("industryParameters", { total: catalog.industries.length })}</summary>
        <p>{t("industryHint")}</p>
        <ul>{catalog.industries.map((industry) => <li key={industry.code}><code>{industry.code}</code> {catalogLabel("industries", industry.code)}</li>)}</ul>
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

export function ResearchFieldCatalog({ catalog }: { catalog: AlphaCatalog }) {
  const { t } = useTranslation("data");
  const [search, setSearch] = useState("");
  const searchInput = useRef<HTMLInputElement>(null);
  const [category, setCategory] = useState("");
  const [purpose, setPurpose] = useState("");
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const visible = catalog.fields.filter((field) => (
    (!category || field.research_category === category) &&
    matchesResearchField(field, search) &&
    (!purpose || field.research_purpose === purpose)
  ));
  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pageFields = visible.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);
  const selected = pageFields.find((field) => field.field_id === selectedId) ?? pageFields[0];
  return <section aria-labelledby="research-fields-title" className="data-field-catalog data-explorer">
    <header><h2 id="research-fields-title">{t("researchFields")}</h2><span>{t("fieldCount", { total: catalog.fields.length })}</span></header>
    <div className="data-search"><MagnifyingGlass aria-hidden="true" size={20} />
      <label className="visually-hidden" htmlFor="data-field-search">{t("searchFields")}</label>
      <input id="data-field-search" ref={searchInput} onChange={(event) => { setSearch(event.target.value); setPage(1); }}
        placeholder={t("searchPlaceholder")} type="text" role="searchbox" value={search} />
      {search !== "" && <button className="button button-quiet data-search-clear" type="button" aria-label={t("clearSearch")}
        onClick={() => { setSearch(""); setPage(1); searchInput.current?.focus(); }}>
        <X aria-hidden="true" size={16} />
      </button>}
    </div>
    <div className="data-field-filters">
      <div className="data-categories" role="group" aria-label={t("category")}>
        {[{ value: "", label: t("allFields") }, { value: "market", label: t("market") }, { value: "financial", label: t("financial") }].map((item) =>
          <button className="button button-quiet" type="button" key={item.value} aria-pressed={category === item.value}
            onClick={() => { setCategory(item.value); setPage(1); }}>
            {item.label}{item.value && <span>{catalog.fields.filter((field) => field.research_category === item.value).length}</span>}
          </button>)}
      </div>
      <label>
        <span className="visually-hidden">{t("purpose")}</span>
        <select value={purpose} onChange={(event) => { setPurpose(event.target.value); setPage(1); }}>
          <option value="">{t("allPurposes")}</option>
          {[...new Set(catalog.fields.map((field) => field.research_purpose))].sort(compareResearchPurposes).map((value) =>
            <option key={value} value={value}>{catalogLabel("purposes", value)}</option>)}
        </select>
      </label>
    </div>
    {pageFields.length ? <div className="data-explorer-layout">
      <div className="data-field-results">
        <div className="data-field-dataset data-field-table-scroll">
          <table className="data-field-table data-explorer-table">
            <caption className="visually-hidden">{t("researchFields")}</caption>
            <thead><tr><th scope="col">{t("field")}</th><th scope="col">{t("formulaName")}</th><th scope="col">{t("unit")}</th></tr></thead>
            <tbody>{pageFields.map((field) => <tr key={field.field_id} onClick={() => setSelectedId(field.field_id)}
              className={selected?.field_id === field.field_id ? "is-selected" : undefined}>
              <th scope="row"><button type="button" aria-pressed={selected?.field_id === field.field_id}
                aria-controls="data-field-detail">
                <span>{fieldDisplay(field.field_id).name}</span></button></th>
              <td><code>{field.identifier}</code></td><td><code>{catalogLabel("units", field.unit)}</code></td>
            </tr>)}</tbody>
          </table>
        </div>
        <nav className="data-pagination" aria-label={t("pages")}>
          <span role="status">{t("showing", { start: (currentPage - 1) * PAGE_SIZE + 1, end: Math.min(currentPage * PAGE_SIZE, visible.length), total: visible.length })}</span>
          <div><button className="button button-quiet" type="button" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>{t("previous")}</button>
            <span>{currentPage} / {pageCount}</span>
            <button className="button button-quiet" type="button" disabled={currentPage === pageCount} onClick={() => setPage(currentPage + 1)}>{t("next")}</button></div>
        </nav>
      </div>
      {selected && <FieldDetail key={selected.field_id} field={selected} />}
    </div> : <p className="data-field-empty" role="status">{t(catalog.fields.length ? "noMatches" : "noFields")}</p>}
  </section>;
}

function FieldDetail({ field }: { field: AlphaCatalogField }) {
  const { t } = useTranslation("data");
  const [copyStatus, setCopyStatus] = useState<"copied" | "copyUnavailable" | null>(null);
  const display = fieldDisplay(field.field_id);
  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); setCopyStatus("copied"); }
    catch { setCopyStatus("copyUnavailable"); }
  }
  return <aside id="data-field-detail" aria-label={t("details")} className="data-field-detail">
    <h3>{display.name}</h3>
    <div className="data-copy"><code>{field.identifier}</code><button className="button button-quiet" type="button" aria-label={t("copyFormula")} onClick={() => void copy(field.identifier)}><Copy aria-hidden="true" size={16} /></button></div>
    <p>{display.description}</p>
    <dl><div><dt>{t("unit")}</dt><dd>{catalogLabel("units", field.unit)}</dd></div>
      <div><dt>{t("period")}</dt><dd>{catalogLabel("reportPeriods", field.report_period_selection)}</dd></div>
      <div><dt>{t("availableAt")}</dt><dd>{catalogLabel("availability", field.availability)}</dd></div>
      <div><dt>{t("missingValues")}</dt><dd>{catalogLabel("missingness", field.missingness)}</dd></div>
      <div><dt>{t("appliesTo")}</dt><dd>{field.applicable_company_types.length ? t("companyTypes", { types: field.applicable_company_types.join(", ") }) : t("allInstruments")}</dd></div></dl>
    {field.example && <div className="data-example"><span>{t("example")}</span><div className="data-copy"><code>{field.example}</code><button className="button button-quiet" type="button" aria-label={t("copyExample")} onClick={() => void copy(field.example)}><Copy aria-hidden="true" size={16} /></button></div></div>}
    <p role="status" className="data-copy-status">{copyStatus && t(copyStatus)}</p>

  </aside>;
}

export function DataPage() {
  const { t } = useTranslation("data");
  const [resources, setResources] = useState<DataPageResources | null>(null);
  const [error, setError] = useState<"unavailable" | null>(null);

  const refresh = useCallback(async () => {
    const result = await loadDataPage();
    if (result.resources !== null) setResources(result.resources);
    setError(result.error);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (error) return (
    <section aria-label={t("title")} className="page-section state-section">
      <p role="alert">{t(error)}</p>
      <button onClick={() => void refresh()} type="button">{t("retry")}</button>
    </section>
  );
  if (!resources) {
    return <section aria-label={t("title")} className="page-section state-section"><p>{t("loading")}</p></section>;
  }
  return (
    <DataOverviewView
      catalog={resources.catalog}
      onRefresh={() => void refresh()}
      overview={resources.overview}
    />
  );
}
