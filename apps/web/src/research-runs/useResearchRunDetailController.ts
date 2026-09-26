import { useEffect, useRef, useState } from "react";

import { coreFetch } from "../auth/coreFetch";
import { navigateCorePath } from "../shell/navigation";
import { readCancelError, readTrackingError, type CancelError, type HttpActionError, type RunError } from "./errors";
import type { ResearchRun } from "./ResearchRunsPage";

type LoadState = "loading" | "refreshing" | null;

/** Owns one ResearchRun's polling and state-changing actions. */
export function useResearchRunDetailController(runId: string | undefined) {
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [error, setError] = useState<RunError | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [canceling, setCanceling] = useState(false);
  const [cancelError, setCancelError] = useState<CancelError | null>(null);
  const [startingTracking, setStartingTracking] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteError, setDeleteError] = useState<HttpActionError | null>(null);
  const [refreshGeneration, setRefreshGeneration] = useState(0);
  const loadGeneration = useRef(0);
  const cancelGeneration = useRef(0);
  const cancelController = useRef<AbortController | null>(null);
  const cancelRequest = useRef<{ runId: string; requestId: string } | null>(null);
  const trackingGeneration = useRef(0);
  const trackingController = useRef<AbortController | null>(null);
  const trackingRequest = useRef<{ runId: string; requestId: string } | null>(null);
  const deleteGeneration = useRef(0);
  const deleteController = useRef<AbortController | null>(null);
  const deleteTrigger = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (runId === undefined) return;
    const controller = new AbortController();
    const generation = ++loadGeneration.current;
    let timeout: number | undefined;
    setError(null);
    setLoadState(run?.id === runId ? "refreshing" : "loading");

    async function load(polling = false) {
      try {
        const response = await coreFetch(`/api/research-runs/${runId}`, { signal: controller.signal });
        if (response.status === 403 || response.status === 404) {
          if (generation === loadGeneration.current) {
            setRun(null);
            setLoadState(null);
            setError({ code: response.status === 403 ? "runForbidden" : "runNotFound" });
          }
          return;
        }
        if (!response.ok) throw new Error("ResearchRun unavailable");
        if (generation !== loadGeneration.current) return;
        const nextRun = (await response.json()) as ResearchRun;
        if (generation !== loadGeneration.current) return;
        setRun(nextRun);
        if (isTerminal(nextRun.status)) setCancelError(null);
        if (["queued", "running", "cancelling"].includes(nextRun.status)) {
          timeout = window.setTimeout(() => void load(true), 500);
        }
        if (!polling) setLoadState(null);
      } catch (reason: unknown) {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        if (generation !== loadGeneration.current) return;
        setLoadState(null);
        setError({ code: "loadError" });
      }
    }

    void load();
    return () => {
      if (generation === loadGeneration.current) loadGeneration.current += 1;
      if (timeout !== undefined) window.clearTimeout(timeout);
      controller.abort();
    };
  }, [runId, refreshGeneration]);

  useEffect(() => {
    setCancelError(null);
    setCanceling(false);
    return () => {
      cancelGeneration.current += 1;
      cancelController.current?.abort();
      cancelController.current = null;
      cancelRequest.current = null;
      trackingGeneration.current += 1;
      trackingController.current?.abort();
      trackingController.current = null;
      trackingRequest.current = null;
      deleteGeneration.current += 1;
      deleteController.current?.abort();
      deleteController.current = null;
    };
  }, [runId]);

  function refresh(): void {
    setRefreshGeneration((generation) => generation + 1);
  }

  async function cancel(): Promise<void> {
    if (run === null || run.batch_id || canceling || !["queued", "running"].includes(run.status)) return;
    const targetRun = run;
    const generation = ++cancelGeneration.current;
    loadGeneration.current += 1;
    setLoadState(null);
    cancelController.current?.abort();
    const controller = new AbortController();
    cancelController.current = controller;
    setCanceling(true);
    setCancelError(null);
    const pending = cancelRequest.current;
    const requestId = pending?.runId === targetRun.id ? pending.requestId : `cancel_${crypto.randomUUID()}`;
    cancelRequest.current = { runId: targetRun.id, requestId };
    let failure: CancelError = "cancelError";
    try {
      const response = await coreFetch(`/api/research-runs/${targetRun.id}/cancel`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: requestId }), signal: controller.signal,
      });
      if (!response.ok) {
        failure = await readCancelError(response);
        throw new Error("ResearchRun cancellation failed");
      }
      const nextRun = (await response.json()) as ResearchRun;
      if (generation !== cancelGeneration.current) return;
      setRun((current) => current?.id === targetRun.id ? { ...current, ...nextRun } : current);
      cancelRequest.current = null;
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      if (generation !== cancelGeneration.current) return;
      setCancelError(failure);
    } finally {
      if (generation === cancelGeneration.current) {
        cancelController.current = null;
        setCanceling(false);
        refresh();
      }
    }
  }

  async function startTracking(): Promise<void> {
    if (run === null || run.status !== "succeeded" || deleting) return;
    const targetRun = run;
    const generation = ++trackingGeneration.current;
    loadGeneration.current += 1;
    setLoadState(null);
    trackingController.current?.abort();
    const controller = new AbortController();
    trackingController.current = controller;
    setStartingTracking(true);
    setError(null);
    const pending = trackingRequest.current;
    const requestId = pending?.runId === targetRun.id ? pending.requestId : `track_${crypto.randomUUID()}`;
    trackingRequest.current = { runId: targetRun.id, requestId };
    try {
      const response = await coreFetch(`/api/research-runs/${targetRun.id}/daily-tracks`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: requestId }), signal: controller.signal,
      });
      if (!response.ok) {
        const failure = await readTrackingError(response);
        if (generation === trackingGeneration.current) setError(failure);
        return;
      }
      const track = (await response.json()) as { id: string };
      if (generation !== trackingGeneration.current) return;
      trackingRequest.current = null;
      navigateCorePath(`/daily-tracks/${track.id}`);
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      if (generation !== trackingGeneration.current) return;
      setError({ code: "trackingError" });
    } finally {
      if (generation === trackingGeneration.current) {
        trackingController.current = null;
        setStartingTracking(false);
      }
    }
  }

  function openDeleteDialog(): void {
    setDeleteError(null);
    setDeleteDialogOpen(true);
  }

  function closeDeleteDialog(): void {
    if (deleting) return;
    setDeleteDialogOpen(false);
    setDeleteError(null);
    window.requestAnimationFrame(() => deleteTrigger.current?.focus());
  }

  async function performResearchDeletion(): Promise<void> {
    if (run === null || !isTerminal(run.status) || deleting || startingTracking) return;
    const generation = ++deleteGeneration.current;
    deleteController.current?.abort();
    const controller = new AbortController();
    deleteController.current = controller;
    setDeleting(true);
    setDeleteError(null);
    try {
      const response = await coreFetch(`/api/research-runs/${run.id}`, { method: "DELETE", signal: controller.signal });
      if (!response.ok) {
        if (generation === deleteGeneration.current) setDeleteError({ status: response.status });
        return;
      }
      if (generation !== deleteGeneration.current) return;
      window.location.assign("/research-runs");
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

  return {
    run, setRun, error, loadState, canceling, cancelError, startingTracking, deleting,
    deleteDialogOpen, deleteError, deleteTrigger, refresh, cancel, startTracking,
    openDeleteDialog, closeDeleteDialog, performResearchDeletion,
  };
}

function isTerminal(status: ResearchRun["status"]): boolean {
  return status === "succeeded" || status === "failed" || status === "cancelled";
}
