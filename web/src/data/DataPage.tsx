import { ArrowClockwise } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";

import type { AlphaCatalog, AlphaCatalogField } from "../alphaCatalog";

export type DataOverview = {
  market_coverage: { start: string; end: string } | null;
  financial_coverage: {
    start: string;
    observation_through_session: string;
    reconciliation_status: string;
    historical_reconciliation_watermark: string;
    revision_coverage: string;
    seed_policy: string;
    sparse_facts: boolean;
  } | null;
  industry_coverage: {
    start: string;
    observation_through_session: string;
    classification_version: "SW2021";
  } | null;
  data_through_session: string | null;
  last_market_refresh_at: string | null;
  last_financial_refresh_at: string | null;
  last_industry_refresh_at: string | null;
  industry_refresh_status: "running" | "succeeded" | "failed" | null;
  industry_refresh_failure_code: string | null;
  market_research_readiness: boolean;
  financial_research_readiness: boolean;
  industry_research_readiness: boolean;
};

type DataPageResources = {
  overview: DataOverview;
  catalog: AlphaCatalog;
};

export type DataPageLoad =
  | { resources: DataPageResources; error: null }
  | { resources: null; error: string };

const DATASET_FAMILIES = [
  {
    familyId: "equity.eod_price",
    id: "market-data-fields",
    title: "Market data fields",
  },
  {
    familyId: "equity.financial_pit",
    id: "financial-data-fields",
    title: "Financial data fields",
  },
] as const;

export async function loadDataPage(
  request: typeof fetch = fetch,
): Promise<DataPageLoad> {
  try {
    const [overviewResponse, catalogResponse] = await Promise.all([
      request("/api/data"),
      request("/api/alpha/catalog"),
    ]);
    if (!overviewResponse.ok || !catalogResponse.ok) {
      throw new Error("Data unavailable");
    }
    const [overview, catalog] = await Promise.all([
      overviewResponse.json() as Promise<DataOverview>,
      catalogResponse.json() as Promise<AlphaCatalog>,
    ]);
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
  const financialCoverage = overview.financial_coverage;
  const industryCoverage = overview.industry_coverage;
  const industryState = overview.industry_refresh_status === "failed"
    ? "Last refresh failed"
    : overview.industry_research_readiness
      ? "Industry ready"
      : industryCoverage === null
        ? "Industry not ready"
        : "Industry stale";
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
        <span className="signal-strip-label"><span className="health-dot" /> Market data</span>
        <strong>{overview.market_research_readiness ? "Market ready" : "Market not ready"}</strong>
      </div>
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
      <div className="signal-strip" aria-label="Financial data readiness">
        <span className="signal-strip-label"><span className="health-dot" /> Financial data</span>
        <strong>{overview.financial_research_readiness ? "Finance ready" : "Finance not ready"}</strong>
      </div>
      <dl className="data-overview-stats" aria-label="Financial data coverage">
        <div>
          <dt>Financial coverage start</dt>
          <dd>{financialCoverage?.start ?? "Not available"}</dd>
        </div>
        <div>
          <dt>Observed through</dt>
          <dd>{financialCoverage?.observation_through_session ?? "Not available"}</dd>
        </div>
        <div>
          <dt>Reconciliation</dt>
          <dd>{financialCoverage?.reconciliation_status ?? "Not available"}</dd>
        </div>
        <div>
          <dt>Last financial refresh</dt>
          <dd>{overview.last_financial_refresh_at ?? "Not available"}</dd>
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

function ResearchFieldCatalog({ catalog }: { catalog: AlphaCatalog }) {
  return (
    <section aria-labelledby="research-fields-title" className="data-field-catalog">
      <header>
        <h2 id="research-fields-title">Research fields</h2>
        <span>{catalog.fields.length} available</span>
      </header>
      {DATASET_FAMILIES.map((dataset) => {
        const fields = catalog.fields.filter((field) => field.family_id === dataset.familyId);
        return (
          <section aria-labelledby={dataset.id} className="data-field-dataset" key={dataset.familyId}>
            <header>
              <h3 id={dataset.id}>{dataset.title}</h3>
              <span>{fields.length} {fields.length === 1 ? "field" : "fields"}</span>
            </header>
            {fields.length > 0 ? <FieldTable fields={fields} title={dataset.title} /> : (
              <p className="data-field-empty">No fields are currently available for research.</p>
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
                <span>{field.description}</span>
                <small>{humanizeContract(field.missingness)}</small>
              </td>
              <td>
                <span>{fieldTimeSemantics(field)}</span>
                <small>{humanizeContract(field.availability)}</small>
                <small>{field.applicable_company_types.length > 0
                  ? `Company types ${field.applicable_company_types.join(", ")}`
                  : "All supported instruments"}</small>
              </td>
              <td><code>{field.unit}</code></td>
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
