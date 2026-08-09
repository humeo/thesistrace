import { useCallback, useEffect, useState } from "react";

export type DataOverview = {
  dataset_coverage: { start: string; end: string } | null;
  data_through_session: string | null;
  last_refresh_at: string | null;
  readiness: boolean;
};

export function DataOverviewView({
  overview,
  onRefresh,
}: {
  overview: DataOverview;
  onRefresh: () => void;
}) {
  const coverage = overview.dataset_coverage;
  return (
    <section aria-label="Data" className="page-section data-page">
      <header className="page-hero">
        <div>
          <p className="eyebrow">Current research data</p>
          <h1>Data overview</h1>
          <p className="hero-copy">The current market-data coverage available to research.</p>
        </div>
        <div className="hero-actions">
          <button className="button button-quiet" onClick={onRefresh}>Refresh ↻</button>
        </div>
      </header>
      <div className="signal-strip" aria-label="Data readiness">
        <span className="signal-strip-label"><span className="health-dot" /> Canonical data</span>
        <strong>{overview.readiness ? "Ready for research" : "Data not ready"}</strong>
      </div>
      <dl className="data-overview-stats" aria-label="Current data coverage">
        <div>
          <dt>Coverage start</dt>
          <dd>{coverage?.start ?? "—"}</dd>
        </div>
        <div>
          <dt>Coverage end</dt>
          <dd>{coverage?.end ?? "—"}</dd>
        </div>
        <div>
          <dt>Data through</dt>
          <dd>{overview.data_through_session ?? "—"}</dd>
        </div>
        <div>
          <dt>Last successful refresh</dt>
          <dd>{overview.last_refresh_at ?? "—"}</dd>
        </div>
      </dl>
    </section>
  );
}

export function DataPage() {
  const [overview, setOverview] = useState<DataOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const response = await fetch("/api/data");
    if (!response.ok) throw new Error("Data overview unavailable");
    setOverview((await response.json()) as DataOverview);
    setError(null);
  }, []);

  useEffect(() => {
    void refresh().catch((reason: Error) => setError(reason.message));
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
