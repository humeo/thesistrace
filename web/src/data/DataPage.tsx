import { useCallback, useEffect, useState } from "react";

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
  data_through_session: string | null;
  last_market_refresh_at: string | null;
  last_financial_refresh_at: string | null;
  market_research_readiness: boolean;
  financial_research_readiness: boolean;
};

export type DataOverviewLoad =
  | { overview: DataOverview; error: null }
  | { overview: null; error: string };

export async function loadDataOverview(
  request: typeof fetch = fetch,
): Promise<DataOverviewLoad> {
  try {
    const response = await request("/api/data");
    if (!response.ok) throw new Error("Data overview unavailable");
    return { overview: (await response.json()) as DataOverview, error: null };
  } catch {
    return { overview: null, error: "Data overview unavailable" };
  }
}

export function DataOverviewView({
  overview,
  onRefresh,
}: {
  overview: DataOverview;
  onRefresh: () => void;
}) {
  const marketCoverage = overview.market_coverage;
  const financialCoverage = overview.financial_coverage;
  return (
    <section aria-label="Data" className="page-section data-page">
      <header className="page-hero">
        <div>
          <p className="eyebrow">Current research data</p>
          <h1>Data overview</h1>
          <p className="hero-copy">The current market and financial data available to research.</p>
        </div>
        <div className="hero-actions">
          <button className="button button-quiet" onClick={onRefresh}>Refresh ↻</button>
        </div>
      </header>
      <div className="signal-strip" aria-label="Data readiness">
        <span className="signal-strip-label"><span className="health-dot" /> Canonical data</span>
        <strong>{overview.market_research_readiness ? "Market ready" : "Market not ready"}</strong>
      </div>
      <dl className="data-overview-stats" aria-label="Market data coverage">
        <div>
          <dt>Market coverage start</dt>
          <dd>{marketCoverage?.start ?? "—"}</dd>
        </div>
        <div>
          <dt>Market coverage end</dt>
          <dd>{marketCoverage?.end ?? "—"}</dd>
        </div>
        <div>
          <dt>Data through</dt>
          <dd>{overview.data_through_session ?? "—"}</dd>
        </div>
        <div>
          <dt>Last market refresh</dt>
          <dd>{overview.last_market_refresh_at ?? "—"}</dd>
        </div>
      </dl>
      <div className="signal-strip" aria-label="Financial data readiness">
        <span className="signal-strip-label"><span className="health-dot" /> Financial data</span>
        <strong>{overview.financial_research_readiness ? "Finance ready" : "Finance not ready"}</strong>
      </div>
      <dl className="data-overview-stats" aria-label="Financial data coverage">
        <div>
          <dt>Financial coverage start</dt>
          <dd>{financialCoverage?.start ?? "—"}</dd>
        </div>
        <div>
          <dt>Observed through</dt>
          <dd>{financialCoverage?.observation_through_session ?? "—"}</dd>
        </div>
        <div>
          <dt>Reconciliation</dt>
          <dd>{financialCoverage?.reconciliation_status ?? "—"}</dd>
        </div>
        <div>
          <dt>Last financial refresh</dt>
          <dd>{overview.last_financial_refresh_at ?? "—"}</dd>
        </div>
      </dl>
    </section>
  );
}

export function DataPage() {
  const [overview, setOverview] = useState<DataOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const result = await loadDataOverview();
    if (result.overview !== null) setOverview(result.overview);
    setError(result.error);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (error) return (
    <section aria-label="Data" className="page-section state-section">
      <p role="alert">{error}</p>
      <button onClick={() => void refresh()}>Retry</button>
    </section>
  );
  if (!overview) {
    return <section aria-label="Data" className="page-section state-section"><p>Loading Data…</p></section>;
  }
  return <DataOverviewView overview={overview} onRefresh={() => void refresh()} />;
}
