import { useEffect, useRef, useState } from "react";

import { coreFetch } from "../auth/coreFetch";
import {
  DailyTrackAnalysisView,
  type DailyTrackAnalysis,
} from "./DailyTrackAnalysisView";
import type { TerminalStrategyState } from "../research-runs/ResearchRunsPage";

type DailyTrackSummary = {
  id: string;
  status: "active" | "blocked" | "stopping" | "stopped";
  seed_run_id: string;
  result_checksum_sha256: string;
  origin_session: string;
  strategy_session: string;
};

export type DailyTrackDetail = {
  id: string;
  status: "active" | "blocked" | "stopping" | "stopped";
  origin: {
    seed_run_id: string;
    seed_research_available: boolean;
    result_checksum_sha256: string;
    strategy_session: string;
    terminal_account: TerminalStrategyState;
  };
  strategy_session: string;
  data_through_session: string;
  lag_sessions: number;
  progress: {
    head_session: string;
    lag_sessions: number;
    phase: "waiting" | "queued" | "retry_wait" | "starting" | "calculating" | "result_ready" | "staging" | "stopping" | "blocked" | "up_to_date" | "stopped";
    target_start_session: string | null;
    target_end_session: string | null;
    target_session_count: number;
    completed_target_sessions: number;
    current_session: string | null;
    cycle_attempt: number | null;
    cycle_attempt_limit: number;
    retry_wait: boolean;
    next_attempt_eligible_at: string | null;
  };
  blocked_reason: string | null;
  factor: DailyTrackAnalysis["factor"];
  strategy: DailyTrackAnalysis["strategy"];
};

type DailyTrackList = { items: DailyTrackSummary[]; next_cursor: string | null };
type LoadState = "loading" | "reloading" | null;
type RefreshState = "submitting" | "accepted" | null;
type RetryState = "submitting" | "accepted" | null;
type StopState = "submitting" | "accepted" | null;

export function dailyTrackNeedsPolling(
  track: Pick<DailyTrackDetail, "status" | "progress">,
): boolean {
  return track.status === "stopping" || [
    "queued",
    "retry_wait",
    "starting",
    "calculating",
    "result_ready",
    "staging",
  ].includes(track.progress.phase);
}

export function dailyTrackCanRefresh(
  track: Pick<DailyTrackDetail, "status" | "lag_sessions" | "progress">,
): boolean {
  return track.status === "active"
    && track.lag_sessions > 0
    && track.progress.phase === "waiting";
}

export function DailyTracksPage({ trackId }: { trackId?: string }) {
  const [track, setTrack] = useState<DailyTrackDetail | null>(null);
  const [items, setItems] = useState<DailyTrackSummary[] | null>(null);
  const [error, setError] = useState(false);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [refreshGeneration, setRefreshGeneration] = useState(0);
  const [advanceState, setAdvanceState] = useState<RefreshState>(null);
  const [retryState, setRetryState] = useState<RetryState>(null);
  const [stopState, setStopState] = useState<StopState>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const loadGeneration = useRef(0);
  const deleteGeneration = useRef(0);
  const deleteController = useRef<AbortController | null>(null);

  useEffect(() => {
    setAdvanceState(null);
    setRetryState(null);
    setStopState(null);
    setDeleteError(null);
  }, [trackId]);

  useEffect(() => () => {
    deleteGeneration.current += 1;
    deleteController.current?.abort();
  }, [trackId]);

  useEffect(() => {
    const controller = new AbortController();
    const generation = ++loadGeneration.current;
    let timeout: number | undefined;
    setError(false);
    const path = trackId ? `/api/daily-tracks/${trackId}` : "/api/daily-tracks";

    async function load(polling = false) {
      try {
        const response = await coreFetch(path, { signal: controller.signal });
        if (!response.ok) throw new Error("DailyTrack unavailable");
        if (trackId) {
          const nextTrack = (await response.json()) as DailyTrackDetail;
          if (generation !== loadGeneration.current) return;
          setTrack(nextTrack);
          if (dailyTrackNeedsPolling(nextTrack)) {
            timeout = window.setTimeout(() => void load(true), 500);
          } else {
            setAdvanceState(null);
          }
        } else {
          const nextItems = ((await response.json()) as DailyTrackList).items;
          if (generation !== loadGeneration.current) return;
          setItems(nextItems);
        }
        if (!polling) setLoadState(null);
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
      if (timeout !== undefined) window.clearTimeout(timeout);
      controller.abort();
    };
  }, [refreshGeneration, trackId]);

  function reloadStatus() {
    setRetryState(null);
    setLoadState("reloading");
    setRefreshGeneration((value) => value + 1);
  }

  async function refreshToLatestData() {
    if (!trackId || !track || !dailyTrackCanRefresh(track)) return;
    setAdvanceState("submitting");
    try {
      const response = await coreFetch(`/api/daily-tracks/${trackId}/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: `refresh_${crypto.randomUUID()}` }),
      });
      if (!response.ok) throw new Error("DailyTrack Refresh was not accepted");
      await response.json();
      setAdvanceState("accepted");
      setRefreshGeneration((value) => value + 1);
    } catch {
      setAdvanceState(null);
      setError(true);
    }
  }

  async function retryBlockedTrack() {
    if (!trackId) return;
    setRetryState("submitting");
    try {
      const response = await coreFetch(`/api/daily-tracks/${trackId}/retry`, {
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
      const response = await coreFetch(`/api/daily-tracks/${trackId}/stop`, {
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

  async function deleteTrack(): Promise<void> {
    if (!trackId || track?.status !== "stopped" || deleting) return;
    if (!window.confirm(`Permanently delete DailyTrack ${trackId}?`)) return;
    const generation = ++deleteGeneration.current;
    deleteController.current?.abort();
    const controller = new AbortController();
    deleteController.current = controller;
    setDeleting(true);
    setDeleteError(null);
    try {
      const response = await coreFetch(`/api/daily-tracks/${trackId}`, {
        method: "DELETE",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`DailyTrack deletion failed (${response.status})`);
      if (generation !== deleteGeneration.current) return;
      window.location.assign("/daily-tracks");
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      if (generation !== deleteGeneration.current) return;
      setDeleteError(
        reason instanceof Error ? reason.message : "DailyTrack deletion failed",
      );
    } finally {
      if (generation === deleteGeneration.current) {
        deleteController.current = null;
        setDeleting(false);
      }
    }
  }

  if (error) {
    return (
      <section aria-label="Daily Tracks" className="state-section">
        <h1>DailyTrack</h1>
        <p role="alert">DailyTrack unavailable</p>
        <button onClick={reloadStatus}>Retry</button>
      </section>
    );
  }
  if (trackId && track === null) {
    return <section aria-label="Daily Tracks" className="state-section"><p>Loading DailyTrack…</p></section>;
  }
  if (!trackId && items === null) {
    return <section aria-label="Daily Tracks" className="state-section"><p>Loading DailyTracks…</p></section>;
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
          <div className="page-header-actions">
            {track.status === "active" ? (
              <button
                disabled={!dailyTrackCanRefresh(track) || advanceState !== null}
                onClick={() => void refreshToLatestData()}
              >
                Refresh to latest data
              </button>
            ) : null}
            <button disabled={loadState !== null || deleting} onClick={reloadStatus}>
              Reload status
            </button>
            {track.status === "blocked" ? (
              <button
                disabled={retryState === "submitting"}
                onClick={() => void retryBlockedTrack()}
              >
                Retry blocked target
              </button>
            ) : null}
            {track.status === "active" || track.status === "blocked" ? (
              <button
                disabled={stopState === "submitting"}
                onClick={() => void stopTrack()}
              >
                Stop DailyTrack
              </button>
            ) : null}
            {track.status === "stopped" ? (
              <button disabled={deleting} onClick={() => void deleteTrack()}>
                {deleting ? "Deleting…" : "Delete DailyTrack"}
              </button>
            ) : null}
          </div>
        </header>
        {track.status === "active" || track.status === "blocked" ? (
          <p>Stopping this DailyTrack is irreversible.</p>
        ) : null}
        {loadState === "reloading" ? (
          <p role="status">Reloading DailyTrack status…</p>
        ) : null}
        {advanceState === "submitting" ? (
          <p role="status">Queuing DailyTrack Refresh…</p>
        ) : null}
        {advanceState === "accepted" ? (
          <p role="status">DailyTrack Refresh accepted.</p>
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
          <p role="status">DailyTrack Stop accepted.</p>
        ) : null}
        {track.status === "stopping" ? (
          <p role="status">DailyTrack is stopping; its execution child is still being confirmed.</p>
        ) : null}
        {track.status === "stopped" ? (
          <p role="status">DailyTrack stopped permanently.</p>
        ) : null}
        {deleteError !== null ? <p role="alert">{deleteError}</p> : null}
        <div className="research-run-facts">
          <p><strong>Status</strong> {track.status}</p>
          <p><strong>Data through</strong> {track.data_through_session}</p>
          <p>
            <strong>Lag</strong>{" "}
            {track.lag_sessions === 0
              ? "Up to date"
              : `${track.lag_sessions} ${track.lag_sessions === 1 ? "session" : "sessions"} behind`}
          </p>
          <p><strong>Strategy session</strong> {track.strategy_session}</p>
          <TrackingProgressView progress={track.progress} />
          {track.blocked_reason ? (
            <p><strong>Blocked</strong> {track.blocked_reason}</p>
          ) : null}
        </div>

        <TrackingOriginView origin={track.origin} />

        <DailyTrackAnalysisView analysis={analysis} />
      </section>
    );
  }
  return (
    <section aria-label="Daily Tracks">
      <h1>Daily Tracks</h1>
      {items?.length === 0 ? <p>No DailyTracks yet.</p> : null}
      <ol aria-label="Daily Tracks" className="track-history">
        {items?.map((item) => (
          <li key={item.id}>
            <a href={`/daily-tracks/${item.id}`}><strong>{item.id}</strong></a>
            <dl>
              <div><dt>Status</dt><dd>{item.status}</dd></div>
              <div><dt>Origin session</dt><dd>{item.origin_session}</dd></div>
              <div><dt>Strategy session</dt><dd>{item.strategy_session}</dd></div>
              <div><dt>Seed ResearchRun</dt><dd><code>{item.seed_run_id}</code></dd></div>
            </dl>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function TrackingProgressView({
  progress,
}: {
  progress: DailyTrackDetail["progress"];
}) {
  return (
    <>
      <p><strong>Advance phase</strong> {progress.phase}</p>
      {progress.target_start_session && progress.target_end_session ? (
        <p>
          <strong>Frozen target</strong>{" "}
          {progress.target_start_session} to {progress.target_end_session}{" "}
          ({progress.target_session_count} sessions)
        </p>
      ) : null}
      {progress.current_session ? (
        <p><strong>Current session</strong> {progress.current_session}</p>
      ) : null}
      {progress.cycle_attempt ? (
        <p><strong>Attempt cycle</strong> {progress.cycle_attempt}/{progress.cycle_attempt_limit}</p>
      ) : null}
      {progress.retry_wait && progress.next_attempt_eligible_at ? (
        <p><strong>Retry eligible</strong> {progress.next_attempt_eligible_at}</p>
      ) : null}
    </>
  );
}

export function TrackingOriginView({ origin }: { origin: DailyTrackDetail["origin"] }) {
  return (
    <section className="research-result-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Immutable starting account</p>
          <h2>Tracking Origin</h2>
        </div>
      </div>
      <div className="research-run-facts">
        <p>
          <strong>Seed ResearchRun</strong>{" "}
          {origin.seed_research_available ? (
            <a href={`/research-runs/${origin.seed_run_id}`}>{origin.seed_run_id}</a>
          ) : (
            <span>{origin.seed_run_id} (deleted)</span>
          )}
        </p>
        <p><strong>Origin strategy session</strong> {origin.strategy_session}</p>
        <p>
          <strong>Origin net NAV</strong>{" "}
          <span title={origin.terminal_account.net_nav}>
            {formatCnyDecimal(origin.terminal_account.net_nav)}
          </span>
        </p>
        <p>
          <strong>Origin net cash</strong>{" "}
          <span title={origin.terminal_account.net_cash}>
            {formatCnyDecimal(origin.terminal_account.net_cash)}
          </span>
        </p>
        <p><strong>Origin holdings</strong> {origin.terminal_account.positions.length}</p>
        <p><strong>Result checksum</strong> {origin.result_checksum_sha256}</p>
      </div>
    </section>
  );
}

function formatCnyDecimal(value: string): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "CNY",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(numeric);
}
