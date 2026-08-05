import { useEffect, useRef, useState } from "react";

import {
  DailyTrackAnalysisView,
  type DailyTrackAnalysis,
} from "./DailyTrackAnalysisView";

type DailyTrackSummary = {
  id: string;
  status: "active" | "blocked" | "stopped";
  seed_run_id: string;
  seed_release_id: string;
  current_release_id: string;
  definition_id: string;
  definition_revision: number;
  result_checksum_sha256: string;
  strategy_session: string;
};

type DailyTrackDetail = {
  id: string;
  status: "active" | "blocked" | "stopped";
  origin: {
    seed_run_id: string;
    seed_release_id: string;
    definition_id: string;
    definition_revision: number;
    result_checksum_sha256: string;
    strategy_session: string;
  };
  head_release_id: string;
  strategy_session: string;
  lag_releases: number;
  blocked_reason: string | null;
  factor: DailyTrackAnalysis["factor"];
  strategy: DailyTrackAnalysis["strategy"];
};

type DailyTrackList = { items: DailyTrackSummary[]; next_cursor: string | null };
type LoadState = "loading" | "refreshing" | null;
type RetryState = "submitting" | "accepted" | null;
type StopState = "submitting" | "accepted" | null;

export function DailyTracksPage({ trackId }: { trackId?: string }) {
  const [track, setTrack] = useState<DailyTrackDetail | null>(null);
  const [items, setItems] = useState<DailyTrackSummary[] | null>(null);
  const [error, setError] = useState(false);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [refreshGeneration, setRefreshGeneration] = useState(0);
  const [retryState, setRetryState] = useState<RetryState>(null);
  const [stopState, setStopState] = useState<StopState>(null);
  const loadGeneration = useRef(0);

  useEffect(() => {
    setRetryState(null);
    setStopState(null);
  }, [trackId]);

  useEffect(() => {
    const controller = new AbortController();
    const generation = ++loadGeneration.current;
    setError(false);
    const path = trackId ? `/api/daily-tracks/${trackId}` : "/api/daily-tracks";

    async function load() {
      try {
        const response = await fetch(path, { signal: controller.signal });
        if (!response.ok) throw new Error("DailyTrack unavailable");
        if (trackId) {
          const nextTrack = (await response.json()) as DailyTrackDetail;
          if (generation !== loadGeneration.current) return;
          setTrack(nextTrack);
        } else {
          const nextItems = ((await response.json()) as DailyTrackList).items;
          if (generation !== loadGeneration.current) return;
          setItems(nextItems);
        }
        setLoadState(null);
      } catch (reason: unknown) {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        if (generation === loadGeneration.current) {
          setError(true);
          setLoadState(null);
        }
      }
    }

    void load();
    return () => {
      if (generation === loadGeneration.current) loadGeneration.current += 1;
      controller.abort();
    };
  }, [refreshGeneration, trackId]);

  function refresh() {
    setRetryState(null);
    setLoadState("refreshing");
    setRefreshGeneration((value) => value + 1);
  }

  async function retryBlockedTrack() {
    if (!trackId) return;
    setRetryState("submitting");
    try {
      const response = await fetch(`/api/daily-tracks/${trackId}/retry`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: `retry_${crypto.randomUUID()}` }),
      });
      if (!response.ok) throw new Error("DailyTrack Retry was not accepted");
      await response.json();
      setRetryState("accepted");
      setRefreshGeneration((value) => value + 1);
    } catch {
      setRetryState(null);
      setError(true);
    }
  }

  async function stopTrack() {
    if (!trackId) return;
    setStopState("submitting");
    try {
      const response = await fetch(`/api/daily-tracks/${trackId}/stop`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: `stop_${crypto.randomUUID()}` }),
      });
      if (!response.ok) throw new Error("DailyTrack Stop was not accepted");
      await response.json();
      setStopState("accepted");
      setRefreshGeneration((value) => value + 1);
    } catch {
      setStopState(null);
      setError(true);
    }
  }

  if (error) {
    return (
      <section aria-label="Daily Tracks">
        <h1>DailyTrack</h1>
        <p role="alert">DailyTrack unavailable</p>
        <button onClick={refresh}>Retry</button>
      </section>
    );
  }
  if (trackId && track === null) {
    return <section aria-label="Daily Tracks"><p>Loading DailyTrack…</p></section>;
  }
  if (!trackId && items === null) {
    return <section aria-label="Daily Tracks"><p>Loading DailyTracks…</p></section>;
  }
  if (track) {
    const analysis: DailyTrackAnalysis = {
      factor: track.factor,
      strategy: track.strategy,
    };
    return (
      <section aria-label="Daily Tracks">
        <header className="page-header">
          <div>
            <p className="eyebrow">Persisted daily research</p>
            <h1>DailyTrack</h1>
          </div>
          <button disabled={loadState !== null} onClick={refresh}>Refresh</button>
          {track.status === "blocked" ? (
            <button
              disabled={retryState === "submitting"}
              onClick={() => void retryBlockedTrack()}
            >
              Retry blocked target
            </button>
          ) : null}
          {track.status !== "stopped" ? (
            <button
              disabled={stopState === "submitting"}
              onClick={() => void stopTrack()}
            >
              Stop DailyTrack
            </button>
          ) : null}
        </header>
        {track.status !== "stopped" ? (
          <p>Stopping this DailyTrack is irreversible.</p>
        ) : null}
        {loadState === "refreshing" ? (
          <p role="status">Refreshing DailyTrack…</p>
        ) : null}
        {retryState === "submitting" ? (
          <p role="status">Retrying blocked DailyTrack…</p>
        ) : null}
        {retryState === "accepted" ? (
          <p role="status">Retry accepted for the blocked target.</p>
        ) : null}
        {stopState === "submitting" ? (
          <p role="status">Stopping DailyTrack…</p>
        ) : null}
        {stopState === "accepted" ? (
          <p role="status">DailyTrack stopped permanently.</p>
        ) : null}
        <div className="research-run-facts">
          <p><strong>Status</strong> {track.status}</p>
          <p><strong>Head Release</strong> {track.head_release_id}</p>
          <p>
            <strong>Lag</strong>{" "}
            {track.lag_releases === 0
              ? "Up to date"
              : `${track.lag_releases} ${track.lag_releases === 1 ? "Release" : "Releases"} behind`}
          </p>
          <p><strong>Strategy session</strong> {track.strategy_session}</p>
          {track.blocked_reason ? (
            <p><strong>Blocked</strong> {track.blocked_reason}</p>
          ) : null}
        </div>

        <section className="research-result-section">
          <div className="section-heading">
            <p className="eyebrow">Immutable starting point</p>
            <h2>Tracking Origin</h2>
          </div>
          <div className="research-run-facts">
            <p>
              <strong>Seed ResearchRun</strong>{" "}
              <a href={`/research-runs/${track.origin.seed_run_id}`}>
                {track.origin.seed_run_id}
              </a>
            </p>
            <p><strong>Seed Release</strong> {track.origin.seed_release_id}</p>
            <p>
              <strong>Definition</strong>{" "}
              <a href={`/definitions/${track.origin.definition_id}`}>
                Revision {track.origin.definition_revision}
              </a>
            </p>
            <p><strong>Origin strategy session</strong> {track.origin.strategy_session}</p>
            <p><strong>Result checksum</strong> {track.origin.result_checksum_sha256}</p>
          </div>
        </section>

        <DailyTrackAnalysisView analysis={analysis} />
      </section>
    );
  }
  return (
    <section aria-label="Daily Tracks">
      <h1>Daily Tracks</h1>
      {items?.length === 0 ? <p>No DailyTracks yet.</p> : null}
      <ol aria-label="Daily Tracks">
        {items?.map((item) => (
          <li key={item.id}>
            <a href={`/daily-tracks/${item.id}`}>{item.id}</a>
            <span> · {item.status}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
