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
    setError(null);
    const response = await fetch("/api/data/update", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    });
    if (!response.ok) {
      setError("Data Update was not accepted");
      return;
    }
    await refresh();
  }

  if (error) return (
    <section aria-label="Data">
      <p role="alert">{error}</p>
      <button onClick={() => void refresh()}>Retry</button>
    </section>
  );
  if (!overview) return <section aria-label="Data"><p>Loading Data…</p></section>;

  const release = overview.latest_release;
  return (
    <section aria-label="Data">
      <h1>Data</h1>
      <button disabled={overview.status === "updating"} onClick={() => void updateData()}>
        Update Data
      </button>
      <button onClick={() => void refresh()}>Refresh</button>
      {overview.status === "updating" && <p role="status">Updating canonical data…</p>}
      {overview.status === "failed" && <p role="alert">Data Update failed</p>}
      {overview.status === "idle" && overview.latest_update_outcome === "no_change" && (
        <p role="status">No new completed Research Session. Latest Release unchanged.</p>
      )}
      {!release && overview.status !== "updating" && <p>No Dataset Releases yet.</p>}
      {release && (
        <article>
          <h2>Latest Dataset Release</h2>
          <p>{release.id}</p>
          <p>{release.session_count} Research Sessions</p>
          <p>{release.covered_session_range.start} — {release.covered_session_range.end}</p>
          <p>{release.predecessor_id === null ? "First Release" : "Later Release"}</p>
        </article>
      )}
      <h2>Release History</h2>
      <ol aria-label="Dataset Release history">
        {history.map((item) => (
          <li key={item.id}>
            <span>{item.id}</span>
            <span> · {item.session_count} sessions</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
