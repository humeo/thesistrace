import { useTranslation } from "react-i18next";
import { useEffect, useRef, useState } from "react";
import { ArrowClockwise } from "@phosphor-icons/react";

import { coreFetch } from "../auth/coreFetch";
import { followCoreLink } from "../shell/navigation";
import type { DailyTrackAnalysis } from "./DailyTrackAnalysisView";
import type { DailyTrackObservation } from "./DailyTrackObservationView";
import { DailyTrackWorkspace } from "./DailyTrackWorkspace";
import { DailyTrackComparison } from "./DailyTrackComparison";
import type { TerminalStrategyState } from "../research-runs/ResearchRunsPage";
import { Page, PageHeader, PageContent } from "../components/layout/Page";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Empty, EmptyHeader, EmptyTitle, EmptyDescription } from "../components/ui/empty";
import { Spinner } from "../components/ui/spinner";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../components/ui/tooltip";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem } from "../components/ui/dropdown-menu";
import { AlertDialog, AlertDialogContent, AlertDialogTitle, AlertDialogDescription, AlertDialogHeader, AlertDialogFooter } from "../components/ui/alert-dialog";

export type DailyTrackSummary = {
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
  const [listError, setListError] = useState(false);
  const [error, setError] = useState(false);
  const [detailNotFound, setDetailNotFound] = useState(false);
  const [actionError, setActionError] = useState<ActionError | null>(null);
  const [confirmStop, setConfirmStop] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const manageTrigger = useRef<HTMLButtonElement>(null);
  const reloadTrigger = useRef<HTMLButtonElement>(null);
  const mutationPending = useRef(false);
  const mutationController = useRef<AbortController | null>(null);
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
    setConfirmDelete(false);
    setTrack(null);
    setItems(null);
    setListError(false);
    setLoadState("loading");
    setDetailNotFound(false);
  }, [trackId]);

  useEffect(() => () => {
    deleteGeneration.current += 1;
    deleteController.current?.abort();
    mutationController.current?.abort();
  }, [trackId]);

  useEffect(() => {
    const controller = new AbortController();
    const generation = ++loadGeneration.current;
    let timeout: number | undefined;
    setError(false);
    setDetailNotFound(false);
    const path = trackId ? `/api/daily-tracks/${trackId}` : "/api/daily-tracks";

    async function load(polling = false) {
      try {
        const response = await coreFetch(path, { signal: controller.signal });
        if (!response.ok) {
          if (trackId && response.status === 404 && generation === loadGeneration.current) setDetailNotFound(true);
          throw new Error("DailyTrack unavailable");
        }
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

  useEffect(() => {
    if (!trackId) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await coreFetch("/api/daily-tracks", { signal: controller.signal });
        if (!response.ok) throw new Error("DailyTrack list unavailable");
        const list = await response.json() as DailyTrackList;
        if (!controller.signal.aborted) { setItems(list.items); setListError(false); }
      } catch {
        if (!controller.signal.aborted) setListError(true);
      }
    })();
    return () => controller.abort();
  }, [refreshGeneration, trackId]);

  function reloadStatus() {
    setRetryState(null);
    setLoadState("reloading");
    setRefreshGeneration((value) => value + 1);
  }

  async function refreshToLatestData() {
    if (!trackId || !track || !dailyTrackCanRefresh(track) || advanceState !== null || mutationPending.current) return;
    mutationPending.current = true;
    const controller = new AbortController();
    mutationController.current = controller;
    setAdvanceState("submitting");
    setActionError(null);
    try {
      const response = await coreFetch(`/api/daily-tracks/${trackId}/refresh`, {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: `refresh_${crypto.randomUUID()}` }),
      });
      if (!response.ok) throw new Error("DailyTrack Refresh was not accepted");
      await response.json();
      setAdvanceState("accepted");
      setRefreshGeneration((value) => value + 1);
    } catch {
      if (controller.signal.aborted) return;
      setAdvanceState(null);
      setActionError("refreshError");
    } finally {
      mutationPending.current = false;
    }
  }

  async function retryBlockedTrack() {
    if (!trackId || track?.status !== "blocked" || retryState !== null || mutationPending.current) return;
    mutationPending.current = true;
    const controller = new AbortController();
    mutationController.current = controller;
    setRetryState("submitting");
    setActionError(null);
    try {
      const response = await coreFetch(`/api/daily-tracks/${trackId}/retry`, {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: `retry_${crypto.randomUUID()}` }),
      });
      if (!response.ok) throw new Error("DailyTrack Retry was not accepted");
      await response.json();
      setRetryState("accepted");
      setRefreshGeneration((value) => value + 1);
    } catch {
      if (controller.signal.aborted) return;
      setRetryState(null);
      setActionError("retryError");
    } finally {
      mutationPending.current = false;
    }
  }

  async function stopTrack() {
    if (!trackId || !track || !["active", "blocked"].includes(track.status) || stopState !== null || mutationPending.current) return;
    mutationPending.current = true;
    const controller = new AbortController();
    mutationController.current = controller;
    setStopState("submitting");
    setActionError(null);
    try {
      const response = await coreFetch(`/api/daily-tracks/${trackId}/stop`, {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: `stop_${crypto.randomUUID()}` }),
      });
      if (!response.ok) throw new Error("DailyTrack Stop was not accepted");
      await response.json();
      setStopState("accepted");
      setConfirmStop(false);
      setRefreshGeneration((value) => value + 1);
    } catch {
      if (controller.signal.aborted) return;
      setStopState(null);
      setActionError("stopError");
    } finally {
      mutationPending.current = false;
    }
  }

  async function deleteTrack(): Promise<void> {
    if (!trackId || track?.status !== "stopped" || deleting || mutationPending.current) return;
    mutationPending.current = true;
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
        mutationPending.current = false;
      }
    }
  }

  const submitting = advanceState === "submitting" || retryState === "submitting" || stopState === "submitting" || deleting;
  const reloadAction = <TooltipProvider><Tooltip>
    <TooltipTrigger render={<Button variant="ghost" size="icon-lg" ref={reloadTrigger} aria-label={t("reloadStatus")}
      aria-busy={loadState === "reloading"} disabled={loadState !== null || submitting} onClick={reloadStatus} />}>
      {loadState === "reloading" ? <Spinner /> : <ArrowClockwise aria-hidden="true" />}
    </TooltipTrigger>
    <TooltipContent side="bottom">{t("reloadStatus")}</TooltipContent>
  </Tooltip></TooltipProvider>;
  if (error && track === null && (trackId || items === null)) {
    return <Page className="console-workspace" aria-label={t("title")}><PageContent><PageHeader variant="console" title={t("title")} />
      {detailNotFound
        ? <Alert><AlertDescription>{t("notFound")}<Button nativeButton={false} role="link" render={<a href="/daily-tracks" onClick={followCoreLink} />}>{t("backToList")}</Button></AlertDescription></Alert>
        : <Alert variant="destructive"><AlertDescription>{t("unavailable")}<Button variant="outline" onClick={reloadStatus}>{t("retry")}</Button></AlertDescription></Alert>}
    </PageContent></Page>;
  }
  if (trackId && track === null) return <TrackLoading detail />;
  if (!trackId && items === null) return <TrackLoading detail={false} />;
  if (trackId && track) {
    return <>
      <DailyTrackWorkspace key={track.id} track={track} items={items} listError={listError} onReloadList={reloadStatus} reloadAction={reloadAction} actions={<>
        {track.status === "active" ? <Button disabled={!dailyTrackCanRefresh(track) || advanceState !== null || submitting}
          onClick={() => void refreshToLatestData()}>{t(advanceState === "submitting" ? "queuing" : dailyTrackNeedsPolling(track) ? "updating" : "refresh")}</Button> : null}
        {track.status === "blocked" ? <Button disabled={retryState !== null || submitting} onClick={() => void retryBlockedTrack()}>{t("retryBlocked")}</Button> : null}
        <DropdownMenu><DropdownMenuTrigger render={<Button variant="outline" ref={manageTrigger} />} disabled={submitting || track.status === "stopping"}>{t("manage")}</DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-56"><DropdownMenuGroup>
            {track.status === "active" || track.status === "blocked" ? <DropdownMenuItem variant="destructive" onClick={() => { setActionError(null); setConfirmStop(true); }} disabled={stopState !== null}>{t("stop")}</DropdownMenuItem> : null}
            {track.status === "stopped" ? <DropdownMenuItem variant="destructive" onClick={() => { setDeleteError(null); setConfirmDelete(true); }}>{t("delete")}</DropdownMenuItem> : null}
          </DropdownMenuGroup></DropdownMenuContent>
        </DropdownMenu>
      </>} notices={<>
        {error ? <Alert variant="destructive"><AlertDescription>{t("reloadFailed")}</AlertDescription></Alert> : null}
        {loadState === "reloading" ? <p role="status">{t("reloading")}</p> : null}
        {advanceState === "accepted" ? <p role="status">{t("refreshAccepted")}</p> : null}
        {retryState !== null ? <p role="status">{t(retryState === "submitting" ? "retrying" : "retryAccepted")}</p> : null}
        {track.status === "stopping" ? <p role="status">{t("stopWaiting")}</p> : null}
        {actionError || deleteError ? <Alert variant="destructive"><AlertDescription>{actionError ? t(actionError) : deleteError?.status == null ? t("deleteError") : t("deleteHttpError", { status: deleteError.status })}</AlertDescription></Alert> : null}
      </>} />
      <TrackActionDialog open={confirmStop} submitting={stopState === "submitting"} title={t("stopTitle")} description={t("stopDescription")}
        cancelLabel={t("keep")} confirmLabel={t(stopState === "submitting" ? "stopping" : "stop")}
        error={actionError ? t(actionError) : null} onCancel={() => setConfirmStop(false)} onConfirm={() => void stopTrack()} finalFocus={() => stopState === "accepted" || manageTrigger.current?.disabled ? reloadTrigger.current : manageTrigger.current} />
      <TrackActionDialog open={confirmDelete} submitting={deleting} title={t("delete")} description={t("deleteConfirm", { id: trackId })}
        cancelLabel={t("cancel")} confirmLabel={t(deleting ? "deleting" : "delete")}
        error={deleteError ? deleteError.status == null ? t("deleteError") : t("deleteHttpError", { status: deleteError.status }) : null}
        onCancel={() => setConfirmDelete(false)} onConfirm={() => void deleteTrack()} finalFocus={() => stopState === "accepted" || manageTrigger.current?.disabled ? reloadTrigger.current : manageTrigger.current} />
    </>;
  }
  return <Page className="console-workspace" aria-label={t("title")}><PageContent className="flex flex-col gap-6">
    <PageHeader variant="console" title={t("title")} className="mb-0" actions={reloadAction} />
    {error ? <Alert variant="destructive"><AlertDescription>{t("listReloadFailed")}</AlertDescription></Alert> : null}
    {items?.length === 0 ? <Empty variant="page"><EmptyHeader><EmptyTitle role="heading" aria-level={2}>{t("emptyTitle")}</EmptyTitle><EmptyDescription>{t("emptyDescription")}</EmptyDescription></EmptyHeader>
      <Button nativeButton={false} role="link" render={<a href="/research-runs" onClick={followCoreLink} />}>{t("browseRuns")}</Button>
    </Empty> : <DailyTrackComparison items={items ?? []} revision={refreshGeneration} />}
  </PageContent></Page>;
}

function TrackLoading({ detail }: { detail: boolean }) {
  const { t } = useTranslation("daily");
  return <Page className="console-workspace" aria-label={t("title")} aria-busy="true"><PageContent><p role="status">{t(detail ? "loading" : "loadingList")}</p></PageContent></Page>;
}

function TrackActionDialog({ open, submitting, title, description, cancelLabel, confirmLabel, error, onCancel, onConfirm, finalFocus }: {
  open: boolean; submitting: boolean; title: string; description: string; cancelLabel: string; confirmLabel: string; error: string | null;
  onCancel: () => void; onConfirm: () => void; finalFocus: () => HTMLButtonElement | null;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  return <AlertDialog open={open} onOpenChange={value => { if (!value && !submitting) onCancel(); }}>
    <AlertDialogContent initialFocus={cancelRef} finalFocus={finalFocus}>
      <AlertDialogHeader><AlertDialogTitle>{title}</AlertDialogTitle><AlertDialogDescription className="[overflow-wrap:anywhere]">{description}</AlertDialogDescription></AlertDialogHeader>
      {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
      <AlertDialogFooter><Button variant="outline" ref={cancelRef} onClick={onCancel} disabled={submitting}>{cancelLabel}</Button>
        <Button variant="destructive" onClick={onConfirm} disabled={submitting}>{confirmLabel}</Button></AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>;
}
