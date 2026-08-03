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

export function DataPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const response = await fetch("/api/data");
    if (!response.ok) throw new Error("Data overview unavailable");
    setOverview((await response.json()) as Overview);
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

  if (error) return <section aria-label="Data"><p role="alert">{error}</p></section>;
  if (!overview) return <section aria-label="Data"><p>Loading Data…</p></section>;

  const release = overview.latest_release;
  return (
    <section aria-label="Data">
      <h1>Data</h1>
      <button disabled={overview.status === "updating"} onClick={() => void updateData()}>
        Update Data
      </button>
      {overview.status === "updating" && <p role="status">Updating canonical data…</p>}
      {overview.status === "failed" && <p role="alert">Data Update failed</p>}
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
    </section>
  );
}
