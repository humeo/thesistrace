import { useRef, useState } from "react";
import { coreFetch } from "../auth/coreFetch";

export type RerunSource =
  | { kind: "research_run"; run_id: string }
  | { kind: "daily_track"; track_id: string; checkpoint_manifest_sha256: string; through_session: string };

export function CurrentDataRerun({ source, folderId, navigate = path => window.location.assign(path) }: {
  source: RerunSource; folderId: string; navigate?: (path: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef<{ key: string; request_id: string } | null>(null);
  const inFlight = useRef(false);
  async function submit() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true); setError(null);
    const key = JSON.stringify({ source, folderId });
    if (pending.current?.key !== key) pending.current = { key, request_id: crypto.randomUUID() };
    try {
      const response = await coreFetch("/api/research-runs", {
        method: "POST", body: JSON.stringify({
          request_id: pending.current.request_id, folder_id: folderId, rerun_source: source,
        }),
      });
      const result = await response.json() as { id?: string; issues?: { field: string; message: string }[]; detail?: unknown };
      if (!response.ok || !result.id) {
        const issues = result.issues?.map(issue => `${issue.field}: ${issue.message}`).join("; ");
        throw new Error(issues || (typeof result.detail === "string" ? result.detail : "The backtest could not be submitted. Try again."));
      }
      navigate(`/research-runs/${encodeURIComponent(result.id)}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The backtest could not be submitted.");
    } finally {
      inFlight.current = false; setBusy(false);
    }
  }
  return <div className="daily-holdings-rerun">
    <p>Create a new backtest with the same strategy and capital using current data. Results may differ; the original result stays available.
      {source.kind === "daily_track" && <> Runs from the original research start through {source.through_session}.</>}</p>
    <button type="button" disabled={busy} onClick={() => void submit()}>{busy ? "Submitting backtest…" : "Rerun to generate holdings"}</button>
    {error && <p role="alert">{error}</p>}
  </div>;
}

export type RerunOrigin = {
  source_run_id: string; source_track_id?: string | null;
  source_data_generation_id: string; source_checkpoint_manifest_sha256?: string | null;
};
export function CurrentDataRerunOrigin({ origin }: { origin: RerunOrigin }) {
  return <p className="research-run-rerun-origin">
    Current-data rerun · {origin.source_track_id
      ? <a href={`/daily-tracks/${encodeURIComponent(origin.source_track_id)}`}>Source Daily Track</a>
      : <a href={`/research-runs/${encodeURIComponent(origin.source_run_id)}`}>Source Research Run</a>}
    . Uses current data and rules; results may differ from the source.
  </p>;
}
