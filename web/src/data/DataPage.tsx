import { useCallback, useEffect, useState } from "react";

type Release = {
  id: string;
  predecessor_id: string | null;
  session_count: number;
  covered_session_range: { start: string; end: string };
};

type Overview = {
  status: "idle" | "updating" | "failed";
  latest_release: Release | null;
  latest_update_outcome: "published" | "no_change" | "failed" | null;
};

type ReleaseHistory = { items: Release[]; next_cursor: string | null };

export function DataPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [history, setHistory] = useState<Release[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [overviewResponse, historyResponse] = await Promise.all([
      fetch("/api/data"),
      fetch("/api/data/releases"),
    ]);
    if (!overviewResponse.ok || !historyResponse.ok) {
      throw new Error("Data overview unavailable");
    }
    setOverview((await overviewResponse.json()) as Overview);
    setHistory(((await historyResponse.json()) as ReleaseHistory).items);
    setError(null);
  }, []);

  useEffect(() => {
    void refresh().catch((reason: Error) => setError(reason.message));
  }, [refresh]);

  useEffect(() => {
    if (overview?.status !== "updating") return;
    const timer = window.setInterval(() => {
      void refresh().catch((reason: Error) => setError(reason.message));
    }, 250);
    return () => window.clearInterval(timer);
  }, [overview?.status, refresh]);

  async function updateData() {
    const previousOverview = overview;
    setError(null);
    setOverview((current) => current && { ...current, status: "updating" });
    let response: Response;
    try {
      response = await fetch("/api/data/update", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
      });
    } catch {
      setOverview(previousOverview);
      setError("Data Update was not accepted");
      return;
    }
    if (!response.ok) {
      setOverview(previousOverview);
      setError("Data Update was not accepted");
      return;
    }
    await refresh();
  }

  if (error) return (
    <section aria-label="Data" className="page-section state-section">
      <p role="alert">{error}</p>
      <button onClick={() => void refresh()}>Retry</button>
    </section>
  );
  if (!overview) return <section aria-label="Data" className="page-section state-section"><p>Loading Data…</p></section>;

  const release = overview.latest_release;
  return (
    <section aria-label="Data" className="page-section data-page">
      <header className="page-hero">
        <div>
          <p className="eyebrow">The source ledger</p>
          <h1>Data room</h1>
          <p className="hero-copy">A quiet, versioned record of the market sessions your research can stand on.</p>
        </div>
        <div className="hero-actions">
          <button className="button button-primary" disabled={overview.status === "updating"} onClick={() => void updateData()}>
            <span className="button-glyph">＋</span> Update data
          </button>
          <button className="button button-quiet" onClick={() => void refresh()}>Refresh ↻</button>
        </div>
      </header>
      <div className="signal-strip" aria-label="Data status">
        <span className="signal-strip-label"><span className="health-dot" /> Canonical source</span>
        <strong>{overview.status === "updating" ? "Syncing now" : overview.status === "failed" ? "Attention needed" : "Ready for research"}</strong>
        <span className="signal-strip-note">{overview.latest_update_outcome === "no_change" ? "No new completed session" : "The latest release is immutable"}</span>
      </div>
      {overview.status === "updating" && <p className="inline-status" role="status">Updating canonical data…</p>}
      {overview.status === "failed" && <p className="inline-status inline-status-error" role="alert">Data update failed. Check the source connection and retry.</p>}
      {overview.status === "idle" && overview.latest_update_outcome === "no_change" && (
        <p className="inline-status" role="status">No new completed research session. Latest release unchanged.</p>
      )}
      {!release && overview.status !== "updating" && <p className="empty-state">No dataset releases yet.</p>}
      {release && (
        <article className="release-card">
          <div className="release-card-heading"><div><p className="eyebrow">Latest release</p><h2>{release.id}</h2></div><span className="release-badge">{release.predecessor_id === null ? "First release" : "Published"}</span></div>
          <div className="release-stats">
            <div><span>Research sessions</span><strong>{release.session_count}</strong></div>
            <div><span>Covered range</span><strong>{release.covered_session_range.start} <i>→</i> {release.covered_session_range.end}</strong></div>
          </div>
        </article>
      )}
      <div className="section-heading history-heading"><div><p className="eyebrow">Chain of custody</p><h2>Release history</h2></div><span>{history.length} releases</span></div>
      <ol className="release-list" aria-label="Dataset Release history">
        {history.map((item) => (
          <li key={item.id}>
            <span className="release-list-id">{item.id}</span>
            <span>{item.session_count} sessions</span>
            <span>{item.covered_session_range.start} — {item.covered_session_range.end}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
