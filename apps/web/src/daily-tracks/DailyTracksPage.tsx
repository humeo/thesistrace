import { useTranslation } from "react-i18next";
import { formatCurrency, formatNumber, formatUtcTimestamp } from "../i18n/format";
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
  checkpoint_manifest_sha256: string;
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
  blocked_code: string | null;
  observation: DailyTrackObservation;
  strategy: DailyTrackAnalysis["strategy"];
};

type DailyTrackList = { items: DailyTrackSummary[]; next_cursor: string | null };
type LoadState = "loading" | "reloading" | null;
type RefreshState = "submitting" | "accepted" | null;
type RetryState = "submitting" | "accepted" | null;
type ActionError = "refreshError" | "retryError" | "stopError";
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
  const { t } = useTranslation("daily");
  const [track, setTrack] = useState<DailyTrackDetail | null>(null);
  const [items, setItems] = useState<DailyTrackSummary[] | null>(null);
  const [error, setError] = useState(false);
  const [actionError, setActionError] = useState<ActionError | null>(null);
  const [confirmStop, setConfirmStop] = useState(false);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [refreshGeneration, setRefreshGeneration] = useState(0);
  const [advanceState, setAdvanceState] = useState<RefreshState>(null);
  const [retryState, setRetryState] = useState<RetryState>(null);
  const [stopState, setStopState] = useState<StopState>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<{ status: number | null } | null>(null);
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
      setActionError("refreshError");
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
      setActionError("retryError");
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
      setActionError("stopError");
    }
  }

  async function deleteTrack(): Promise<void> {
    if (!trackId || track?.status !== "stopped" || deleting) return;
    if (!window.confirm(t("deleteConfirm", { id: trackId }))) return;
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
      if (!response.ok) { if (generation === deleteGeneration.current) setDeleteError({ status: response.status }); return; }
      if (generation !== deleteGeneration.current) return;
      window.location.assign("/daily-tracks");
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      if (generation !== deleteGeneration.current) return;
      setDeleteError({ status: null });
    } finally {
      if (generation === deleteGeneration.current) {
        deleteController.current = null;
        setDeleting(false);
      }
    }
  }

  if (error && track === null && items === null) {
    return (
      <section aria-label={t("title") } className="state-section">
        <h1>{t("track")} </h1>
        <p role="alert">{t("unavailable")} </p>
        <button onClick={reloadStatus}>{t("retry")} </button>
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
          {t(advanceState === "submitting" ? "queuing" : dailyTrackNeedsPolling(track) ? "updating" : "refresh")}
        </button> : null}
        {track.status === "blocked" ? <button className="primary-action" disabled={retryState !== null}
          onClick={() => void retryBlockedTrack()}>{t("retryBlocked")} </button> : null}
        <button disabled={loadState !== null || deleting} onClick={reloadStatus}>{t("reloadStatus")} </button>
        <details className="track-manage"><summary>{t("manage")} </summary><div>
          {track.status === "active" || track.status === "blocked" ? <button onClick={() => setConfirmStop(true)}
            disabled={stopState !== null}>{t("stop")} </button> : null}
          {track.status === "stopped" ? <button disabled={deleting} onClick={() => void deleteTrack()}>
            {t(deleting ? "deleting" : "delete")}</button> : null}
          {track.status === "stopping" ? <span>{t("stoppingTrack")} </span> : null}
        </div></details>
      </>} notices={<>
        {error ? <p className="track-action-error" role="alert">{t("reloadFailed")} </p> : null}
        {loadState === "reloading" ? <p className="track-action-notice" role="status">{t("reloading")} </p> : null}
        {advanceState === "accepted" ? <p className="track-action-notice" role="status">{t("refreshAccepted")} </p> : null}
        {retryState !== null ? <p className="track-action-notice" role="status">{t(retryState === "submitting" ? "retrying" : "retryAccepted")}</p> : null}
        {track.status === "stopping" ? <p className="track-action-notice" role="status">{t("stopWaiting")} </p> : null}
        {actionError || deleteError ? <p className="track-action-error" role="alert">{actionError ? t(actionError) : deleteError?.status == null ? t("deleteError") : t("deleteHttpError", { status: deleteError.status })}</p> : null}
      </>} />
      <StopTrackDialog open={confirmStop} submitting={stopState === "submitting"}
        error={actionError} onCancel={() => setConfirmStop(false)} onConfirm={() => void stopTrack()} />
    </>;
  }
  return (
    <section aria-label={t("title") } className="daily-track-list">
      <header className="track-header"><div><h1>{t("title")} </h1>
        <p>{t("description")} </p></div>
        <button disabled={loadState !== null} onClick={reloadStatus}>{t("reloadStatus")} </button></header>
      {error ? <p className="track-action-error" role="alert">{t("listReloadFailed")} </p> : null}
      {items?.length === 0 ? <div className="track-list-empty"><h2>{t("emptyTitle")} </h2>
        <p>{t("emptyDescription")} </p>
        <a className="track-text-link" href="/research-runs">{t("browseRuns")} </a></div> : (
        <div className="track-table-scroll" role="region" aria-label={t("list") } tabIndex={0}>
          <table className="track-table"><thead><tr><th scope="col">{t("trackColumn")} </th><th scope="col">{t("status")} </th>
            <th scope="col">{t("trackingFrom")} </th><th scope="col">{t("lastObservation")} </th><th scope="col">{t("seed")} </th></tr></thead>
            <tbody>{items?.map((item) => <tr key={item.id}>
              <th scope="row"><a href={`/daily-tracks/${item.id}`}>{item.id}</a></th>
              <td><span className="track-status" data-status={item.status}>{t(`statuses.${item.status}`)}</span></td>
              <td><time>{item.origin_session}</time></td><td><time>{item.strategy_session}</time></td>
              <td><code>{item.seed_run_id}</code></td>
            </tr>)}</tbody></table>
        </div>
      )}
    </section>
  );
}

function TrackLoading({ detail }: { detail: boolean }) {
  const { t } = useTranslation("daily");
  return <section className="state-section" aria-label={t("title") } aria-busy="true">
    <p role="status">{t(detail ? "loading" : "loadingList")}</p>
  </section>;
}

function StopTrackDialog({ open, submitting, error, onCancel, onConfirm }: {
  open: boolean; submitting: boolean; error: ActionError | null; onCancel: () => void; onConfirm: () => void;
}) {
  const { t } = useTranslation("daily");
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return <dialog ref={dialogRef} className="track-stop-dialog" aria-labelledby="track-stop-title"
    onCancel={(event) => { event.preventDefault(); if (!submitting) onCancel(); }}>
    <h2 id="track-stop-title">{t("stopTitle")} </h2>
    <p>{t("stopDescription")} </p>
    {error ? <p role="alert">{t(error)}</p> : null}
    <footer><button onClick={onCancel} disabled={submitting}>{t("keep")} </button>
      <button className="track-danger-button" onClick={onConfirm} disabled={submitting}>{t(submitting ? "stopping" : "stop")}</button></footer>
  </dialog>;
}

export function TrackingProgressView({
  progress,
}: {
  progress: DailyTrackDetail["progress"];
}) {
  const { t } = useTranslation("daily");
  return (
    <>
      <p><strong>{t("advancePhase")} </strong> {t(`phases.${progress.phase}`)}</p>
      {progress.target_start_session && progress.target_end_session ? (
        <p>
          <strong>{t("frozenTarget")} </strong>{" "}
          {t("targetRange", { start: progress.target_start_session, end: progress.target_end_session, count: progress.target_session_count })}
        </p>
      ) : null}
      {progress.current_session ? (
        <p><strong>{t("currentSession")} </strong> {progress.current_session}</p>
      ) : null}
      {progress.cycle_attempt ? (
        <p><strong>{t("attemptCycle")} </strong> {formatNumber(progress.cycle_attempt)}/{formatNumber(progress.cycle_attempt_limit)}</p>
      ) : null}
      {progress.retry_wait && progress.next_attempt_eligible_at ? (
        <p><strong>{t("retryEligible")} </strong> {formatUtcTimestamp(progress.next_attempt_eligible_at, true)}</p>
      ) : null}
    </>
  );
}

export function TrackingOriginView({ origin }: { origin: DailyTrackDetail["origin"] }) {
  const { t } = useTranslation("daily");
  return (
    <section className="research-result-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">{t("immutableAccount")} </p>
          <h2>{t("origin")} </h2>
        </div>
      </div>
      <div className="research-run-facts">
        <p>
          <strong>{t("seed")} </strong>{" "}
          {origin.seed_research_available ? (
            <a href={`/research-runs/${origin.seed_run_id}`}>{origin.seed_run_id}</a>
          ) : (
            <span>{origin.seed_run_id}{t("deleted")}</span>
          )}
        </p>
        <p><strong>{t("originSession")} </strong> {origin.strategy_session}</p>
        <p>{t("originDescription")} </p>
        <p>
          <strong>{t("originNav")} </strong>{" "}
          <span title={origin.terminal_account.net_nav}>
            {formatCnyDecimal(origin.terminal_account.net_nav)}
          </span>
        </p>
        <p>
          <strong>{t("originCash")} </strong>{" "}
          <span title={origin.terminal_account.net_cash}>
            {formatCnyDecimal(origin.terminal_account.net_cash)}
          </span>
        </p>
        <p><strong>{t("originHoldings")} </strong> {formatNumber(origin.terminal_account.positions.length)}</p>
        <p><strong>{t("checksum")} </strong> {origin.result_checksum_sha256}</p>
      </div>
    </section>
  );
}

function formatCnyDecimal(value: string): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  return formatCurrency(numeric);
}
