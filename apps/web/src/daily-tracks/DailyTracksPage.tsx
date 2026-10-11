import { useTranslation } from "react-i18next";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowClockwise } from "@phosphor-icons/react";

import { coreFetch } from "../auth/coreFetch";
import { followCoreLink, navigateCorePath } from "../shell/navigation";
import type { DailyTrackAnalysis } from "./DailyTrackAnalysisView";
import type { DailyTrackObservation } from "./DailyTrackObservationView";
import { DailyTrackWorkspace } from "./DailyTrackWorkspace";
import { DailyTrackComparison } from "./DailyTrackComparison";
import { BulkRefreshFeedback } from "./BulkRefreshFeedback";
import { dailyTrackCanRefresh, dailyTrackNeedsPolling } from "./progress";
import { refreshAllDailyTracks, type BulkRefreshItem } from "./refreshAll";
import { DailyTrackReadError, dailyTrackDetailOptions, dailyTrackKeys, readDailyTrackList } from "./queries";
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
  seed_name: string | null;
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

export type DailyTrackListItem = DailyTrackSummary & { seed_name: string | null };
export type DailyTrackList = { items: DailyTrackListItem[]; next_cursor: string | null };
type LoadState = "loading" | "reloading" | null;
type RefreshState = "submitting" | "accepted" | null;
type RetryState = "submitting" | "accepted" | null;
type ActionError = "refreshError" | "retryError" | "stopError";
type StopState = "submitting" | "accepted" | null;

export { dailyTrackCanRefresh, dailyTrackNeedsPolling } from "./progress";

export function DailyTracksPage({ trackId }: { trackId?: string }) {
  const { t } = useTranslation("daily");
  const queryClient = useQueryClient();
  const listQuery = useQuery({
    queryKey: dailyTrackKeys.list,
    queryFn: ({ signal }) => readDailyTrackList(signal),
    staleTime: 0,
  });
  const detailQuery = useQuery({
    ...dailyTrackDetailOptions(trackId),
    refetchInterval: query => query.state.status !== "error" && query.state.data
      && dailyTrackNeedsPolling(query.state.data) ? 500 : false,
  });
  const track = detailQuery.data ?? null;
  const items = listQuery.data?.items ?? null;
  const listError = listQuery.isError;
  const error = trackId ? detailQuery.isError : listError;
  const detailNotFound = detailQuery.error instanceof DailyTrackReadError && detailQuery.error.status === 404;
  const [reloading, setReloading] = useState(false);
  const loadState: LoadState = (trackId ? detailQuery.isLoading : listQuery.isLoading)
    ? "loading" : reloading ? "reloading" : null;
  const [actionError, setActionError] = useState<ActionError | null>(null);
  const [confirmStop, setConfirmStop] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const manageTrigger = useRef<HTMLButtonElement>(null);
  const reloadTrigger = useRef<HTMLButtonElement>(null);
  const mutationPending = useRef(false);
  const mutationController = useRef<AbortController | null>(null);
  const [advanceState, setAdvanceState] = useState<RefreshState>(null);
  const [bulkResult, setBulkResult] = useState<BulkRefreshItem[] | null>(null);
  const [bulkError, setBulkError] = useState(false);
  const [retryState, setRetryState] = useState<RetryState>(null);
  const [stopState, setStopState] = useState<StopState>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<{ status: number | null } | null>(null);
  const deleteGeneration = useRef(0);
  const deleteController = useRef<AbortController | null>(null);

  useEffect(() => {
    setAdvanceState(null);
    setBulkResult(null);
    setBulkError(false);
    setRetryState(null);
    setStopState(null);
    setDeleteError(null);
    setActionError(null);
    setConfirmStop(false);
    setConfirmDelete(false);
    setReloading(false);
  }, [trackId]);

  useEffect(() => () => {
    deleteGeneration.current += 1;
    deleteController.current?.abort();
    mutationController.current?.abort();
  }, [trackId]);

  useEffect(() => {
    if (track && !dailyTrackNeedsPolling(track)) {
      setAdvanceState(null);
      setRetryState(null);
      setStopState(null);
    }
  }, [track, detailQuery.dataUpdatedAt]);

  async function reloadFacts() {
    await queryClient.cancelQueries({ queryKey: dailyTrackKeys.all });
    await queryClient.invalidateQueries({ queryKey: dailyTrackKeys.all });
  }

  function reloadStatus() {
    setRetryState(null);
    setReloading(true);
    void reloadFacts().finally(() => setReloading(false));
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
      void reloadFacts();
    } catch {
      if (controller.signal.aborted) return;
      setAdvanceState(null);
      setActionError("refreshError");
    } finally {
      mutationPending.current = false;
    }
  }

  async function refreshAllTracks() {
    if (mutationPending.current) return;
    mutationPending.current = true;
    const controller = new AbortController();
    mutationController.current = controller;
    setAdvanceState("submitting");
    setBulkResult(null);
    setBulkError(false);
    try {
      const result = await refreshAllDailyTracks(controller.signal);
      setBulkResult(result);
      void reloadFacts();
    } catch {
      if (!controller.signal.aborted) setBulkError(true);
    } finally {
      mutationPending.current = false;
      if (!controller.signal.aborted) setAdvanceState(null);
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
      void reloadFacts();
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
      void reloadFacts();
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
      await queryClient.cancelQueries({ queryKey: dailyTrackKeys.all });
      if (generation !== deleteGeneration.current || controller.signal.aborted) return;
      queryClient.removeQueries({ queryKey: dailyTrackKeys.detail(trackId), exact: true });
      queryClient.setQueryData<DailyTrackList>(dailyTrackKeys.list, current => current
        ? { ...current, items: current.items.filter(item => item.id !== trackId) } : current);
      void queryClient.invalidateQueries({ queryKey: dailyTrackKeys.all });
      navigateCorePath("/daily-tracks");
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
    <PageHeader variant="console" title={t("title")} description={t("overviewDescription")} className="mb-0" actions={<>
      <Button size="lg" disabled={submitting || !items?.length} aria-busy={advanceState === "submitting"}
        onClick={() => void refreshAllTracks()}>{advanceState === "submitting" && <Spinner data-icon="inline-start" />}{t(advanceState === "submitting" ? "queuingAll" : "refreshAll")}</Button>
      {reloadAction}
    </>} />
    {advanceState === "submitting" && <p role="status">{t("bulkSubmitting")}</p>}
    {bulkError && <Alert variant="destructive"><AlertDescription>{t("bulkError")}</AlertDescription></Alert>}
    {bulkResult && <BulkRefreshFeedback items={bulkResult} />}
    {error ? <Alert variant="destructive"><AlertDescription>{t("listReloadFailed")}</AlertDescription></Alert> : null}
    {items?.length === 0 ? <Empty variant="page"><EmptyHeader><EmptyTitle role="heading" aria-level={2}>{t("emptyTitle")}</EmptyTitle><EmptyDescription>{t("emptyDescription")}</EmptyDescription></EmptyHeader>
      <Button nativeButton={false} role="link" render={<a href="/research-runs" onClick={followCoreLink} />}>{t("browseRuns")}</Button>
    </Empty> : <DailyTrackComparison items={items ?? []} />}
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
