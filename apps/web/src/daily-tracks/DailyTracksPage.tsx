import { useEffect, useRef, useState } from "react";

import { coreFetch } from "../auth/coreFetch";
import type { DailyTrackAnalysis } from "./DailyTrackAnalysisView";
import type { DailyTrackObservation } from "./DailyTrackObservationView";
import { DailyTrackWorkspace } from "./DailyTrackWorkspace";
import type { TerminalStrategyState } from "../research-runs/ResearchRunsPage";
import "./daily-tracks.css";

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
  observation: DailyTrackObservation;
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
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmStop, setConfirmStop] = useState(false);
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
    setActionError(null);
    setConfirmStop(false);
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
            setRetryState(null);
            setStopState(null);
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
    setActionError(null);
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
      setActionError("The update could not be queued. Reload the status and try again.");
    }
  }

  async function retryBlockedTrack() {
    if (!trackId) return;
    setRetryState("submitting");
    setActionError(null);
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
      setActionError("The retry could not be queued. Reload the status and try again.");
    }
  }

  async function stopTrack() {
    if (!trackId) return;
    setStopState("submitting");
    setActionError(null);
    try {
      const response = await coreFetch(`/api/daily-tracks/${trackId}/stop`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: `stop_${crypto.randomUUID()}` }),
      });
      if (!response.ok) throw new Error("DailyTrack Stop was not accepted");
      await response.json();
      setStopState("accepted");
      setConfirmStop(false);
      setRefreshGeneration((value) => value + 1);
    } catch {
      setStopState(null);
      setActionError("The track could not be stopped. Please try again.");
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

  if (error && track === null && items === null) {
    return (
      <section aria-label="Daily Tracks" className="state-section">
        <h1>DailyTrack</h1>
        <p role="alert">DailyTrack unavailable</p>
        <button onClick={reloadStatus}>Retry</button>
      </section>
    );
  }
  if (trackId && track === null) {
    return <TrackLoading detail />;
  }
  if (!trackId && items === null) {
    return <TrackLoading detail={false} />;
  }
  if (track) {
    return <>
      <DailyTrackWorkspace key={track.id} track={track} actions={<>
        {track.status === "active" ? <button className="primary-action"
          disabled={!dailyTrackCanRefresh(track) || advanceState !== null}
          onClick={() => void refreshToLatestData()}>
          {advanceState === "submitting" ? "Queuing update…" : dailyTrackNeedsPolling(track) ? "Updating…" : "Refresh to latest data"}
        </button> : null}
        {track.status === "blocked" ? <button className="primary-action" disabled={retryState !== null}
          onClick={() => void retryBlockedTrack()}>Retry blocked target</button> : null}
        <button disabled={loadState !== null || deleting} onClick={reloadStatus}>Reload status</button>
        <details className="track-manage"><summary>Manage</summary><div>
          {track.status === "active" || track.status === "blocked" ? <button onClick={() => setConfirmStop(true)}
            disabled={stopState !== null}>Stop DailyTrack</button> : null}
          {track.status === "stopped" ? <button disabled={deleting} onClick={() => void deleteTrack()}>
            {deleting ? "Deleting…" : "Delete DailyTrack"}</button> : null}
          {track.status === "stopping" ? <span>Stopping DailyTrack…</span> : null}
        </div></details>
      </>} notices={<>
        {error ? <p className="track-action-error" role="alert">Could not reload the track. Showing the last loaded observation; use Reload status to try again.</p> : null}
        {loadState === "reloading" ? <p className="track-action-notice" role="status">Reloading DailyTrack status…</p> : null}
        {advanceState === "accepted" ? <p className="track-action-notice" role="status">DailyTrack Refresh accepted. Your current observation remains visible while the update runs.</p> : null}
        {retryState !== null ? <p className="track-action-notice" role="status">{retryState === "submitting" ? "Retrying blocked DailyTrack…" : "Retry accepted for the blocked target."}</p> : null}
        {track.status === "stopping" ? <p className="track-action-notice" role="status">DailyTrack is stopping. Waiting for the current execution to finish stopping.</p> : null}
        {actionError || deleteError ? <p className="track-action-error" role="alert">{actionError || deleteError}</p> : null}
      </>} />
      <StopTrackDialog open={confirmStop} submitting={stopState === "submitting"}
        error={actionError} onCancel={() => setConfirmStop(false)} onConfirm={() => void stopTrack()} />
    </>;
  }
  return (
    <section aria-label="Daily Tracks" className="daily-track-list">
      <header className="track-header"><div><h1>Daily Tracks</h1>
        <p>Follow your strategies through each new trading session.</p></div>
        <button disabled={loadState !== null} onClick={reloadStatus}>Reload status</button></header>
      {error ? <p className="track-action-error" role="alert">Could not reload your tracks. Showing the last loaded list.</p> : null}
      {items?.length === 0 ? <div className="track-list-empty"><h2>Your strategy watch starts with a backtest</h2>
        <p>Open a successful Strategy Backtest and start a Daily Track to follow its holdings and returns.</p>
        <a className="track-text-link" href="/research-runs">Browse Research Runs</a></div> : (
        <div className="track-table-scroll" role="region" aria-label="Daily Tracks list" tabIndex={0}>
          <table className="track-table"><thead><tr><th scope="col">Track</th><th scope="col">Status</th>
            <th scope="col">Tracking from</th><th scope="col">Last observation</th><th scope="col">Seed ResearchRun</th></tr></thead>
            <tbody>{items?.map((item) => <tr key={item.id}>
              <th scope="row"><a href={`/daily-tracks/${item.id}`}>{item.id}</a></th>
              <td><span className="track-status" data-status={item.status}>{item.status}</span></td>
              <td><time>{item.origin_session}</time></td><td><time>{item.strategy_session}</time></td>
              <td><code>{item.seed_run_id}</code></td>
            </tr>)}</tbody></table>
        </div>
      )}
    </section>
  );
}

function TrackLoading({ detail }: { detail: boolean }) {
  return <section className="track-loading" aria-label="Daily Tracks" aria-busy="true">
    <p role="status">{detail ? "Loading DailyTrack…" : "Loading DailyTracks…"}</p>
    <div aria-hidden="true" className="track-loading-header" />
    <div aria-hidden="true" className="track-loading-strip"><span /><span /><span /><span /></div>
    <div aria-hidden="true" className="track-loading-content" />
  </section>;
}

function StopTrackDialog({ open, submitting, error, onCancel, onConfirm }: {
  open: boolean; submitting: boolean; error: string | null; onCancel: () => void; onConfirm: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return <dialog ref={dialogRef} className="track-stop-dialog" aria-labelledby="track-stop-title"
    onCancel={(event) => { event.preventDefault(); if (!submitting) onCancel(); }}>
    <h2 id="track-stop-title">Stop this DailyTrack?</h2>
    <p>Stopping is permanent. The last published holdings and performance stay available, but this track cannot receive further updates.</p>
    {error ? <p role="alert">{error}</p> : null}
    <footer><button onClick={onCancel} disabled={submitting}>Keep tracking</button>
      <button className="track-danger-button" onClick={onConfirm} disabled={submitting}>{submitting ? "Stopping…" : "Stop DailyTrack"}</button></footer>
  </dialog>;
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
