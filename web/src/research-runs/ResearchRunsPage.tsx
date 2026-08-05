import { useEffect, useRef, useState } from "react";

import {
  ResearchAnalysisView,
  type ResearchAnalysis,
} from "../analysis/ResearchAnalysisView";

type ResearchRun = {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  definition_id: string;
  definition_revision: number;
  dataset_release_id: string;
  rerun_of_id?: string;
  failure_reason?: string;
  result?: ResearchAnalysis;
};

type ResearchRunList = { items: ResearchRun[]; next_cursor: string | null };
type LoadState = "loading" | "refreshing" | null;

export function ResearchRunsPage({ runId }: { runId?: string }) {
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [items, setItems] = useState<ResearchRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [canceling, setCanceling] = useState(false);
  const [rerunning, setRerunning] = useState(false);
  const [startingTracking, setStartingTracking] = useState(false);
  const [refreshGeneration, setRefreshGeneration] = useState(0);
  const loadGeneration = useRef(0);
  const cancelGeneration = useRef(0);
  const cancelController = useRef<AbortController | null>(null);
  const cancelRequest = useRef<{ runId: string; requestId: string } | null>(null);
  const rerunGeneration = useRef(0);
  const rerunController = useRef<AbortController | null>(null);
  const rerunRequest = useRef<{ runId: string; requestId: string } | null>(null);
  const trackingGeneration = useRef(0);
  const trackingController = useRef<AbortController | null>(null);
  const trackingRequest = useRef<{ runId: string; requestId: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const generation = ++loadGeneration.current;
    let timeout: number | undefined;
    setError(null);
    setLoadState(refreshGeneration === 0 ? "loading" : "refreshing");
    const path = runId ? `/api/research-runs/${runId}` : "/api/research-runs";

    async function load(polling = false) {
      try {
        const response = await fetch(path, { signal: controller.signal });
        if (!response.ok) throw new Error("ResearchRun unavailable");
        if (generation !== loadGeneration.current) return;
        if (runId) {
          const nextRun = (await response.json()) as ResearchRun;
          if (generation !== loadGeneration.current) return;
          setRun(nextRun);
          if (nextRun.status === "queued" || nextRun.status === "running") {
            timeout = window.setTimeout(() => void load(true), 500);
          }
        } else {
          const nextItems = ((await response.json()) as ResearchRunList).items;
          if (generation !== loadGeneration.current) return;
          setItems(nextItems);
          if (nextItems.some((item) => item.status === "queued" || item.status === "running")) {
            timeout = window.setTimeout(() => void load(true), 500);
          }
        }
        if (!polling) setLoadState(null);
      } catch (reason: unknown) {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        if (generation !== loadGeneration.current) return;
        setLoadState(null);
        setError("ResearchRun unavailable");
      }
    }

    void load();
    return () => {
      if (generation === loadGeneration.current) loadGeneration.current += 1;
      if (timeout !== undefined) window.clearTimeout(timeout);
      controller.abort();
    };
  }, [refreshGeneration, runId]);

  useEffect(() => () => {
    cancelGeneration.current += 1;
    cancelController.current?.abort();
    cancelController.current = null;
    cancelRequest.current = null;
    rerunGeneration.current += 1;
    rerunController.current?.abort();
    rerunController.current = null;
    rerunRequest.current = null;
    trackingGeneration.current += 1;
    trackingController.current?.abort();
    trackingController.current = null;
    trackingRequest.current = null;
  }, [runId]);

  function refresh() {
    setRefreshGeneration((generation) => generation + 1);
  }

  async function cancel() {
    if (run === null || !["queued", "running"].includes(run.status)) return;
    const targetRun = run;
    const generation = ++cancelGeneration.current;
    loadGeneration.current += 1;
    setLoadState(null);
    cancelController.current?.abort();
    const controller = new AbortController();
    cancelController.current = controller;
    setCanceling(true);
    setError(null);
    const pending = cancelRequest.current;
    const requestId = pending?.runId === targetRun.id
      ? pending.requestId
      : `cancel_${crypto.randomUUID()}`;
    cancelRequest.current = { runId: targetRun.id, requestId };
    try {
      const response = await fetch(`/api/research-runs/${targetRun.id}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: requestId }),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("ResearchRun cancellation failed");
      if (generation !== cancelGeneration.current) return;
      setRun((await response.json()) as ResearchRun);
      cancelRequest.current = null;
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      if (generation !== cancelGeneration.current) return;
      setError("ResearchRun cancellation failed");
    } finally {
      if (generation === cancelGeneration.current) {
        cancelController.current = null;
        setCanceling(false);
      }
    }
  }

  async function rerunSelected() {
    if (run === null || !["succeeded", "failed", "cancelled"].includes(run.status)) return;
    const targetRun = run;
    const generation = ++rerunGeneration.current;
    loadGeneration.current += 1;
    setLoadState(null);
    rerunController.current?.abort();
    const controller = new AbortController();
    rerunController.current = controller;
    setRerunning(true);
    setError(null);
    const pending = rerunRequest.current;
    const requestId = pending?.runId === targetRun.id
      ? pending.requestId
      : `rerun_${crypto.randomUUID()}`;
    rerunRequest.current = { runId: targetRun.id, requestId };
    try {
      const response = await fetch(`/api/research-runs/${targetRun.id}/rerun`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: requestId }),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("ResearchRun rerun failed");
      const nextRun = (await response.json()) as ResearchRun;
      if (generation !== rerunGeneration.current) return;
      rerunRequest.current = null;
      window.location.assign(`/research-runs/${nextRun.id}`);
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      if (generation !== rerunGeneration.current) return;
      setError("ResearchRun rerun failed");
    } finally {
      if (generation === rerunGeneration.current) {
        rerunController.current = null;
        setRerunning(false);
      }
    }
  }

  async function startTracking() {
    if (run === null || run.status !== "succeeded") return;
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
    const requestId = pending?.runId === targetRun.id
      ? pending.requestId
      : `track_${crypto.randomUUID()}`;
    trackingRequest.current = { runId: targetRun.id, requestId };
    try {
      const response = await fetch(`/api/research-runs/${targetRun.id}/daily-tracks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: requestId }),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("Start Tracking failed");
      const track = (await response.json()) as { id: string };
      if (generation !== trackingGeneration.current) return;
      trackingRequest.current = null;
      window.location.assign(`/daily-tracks/${track.id}`);
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      if (generation !== trackingGeneration.current) return;
      setError("Start Tracking failed");
    } finally {
      if (generation === trackingGeneration.current) {
        trackingController.current = null;
        setStartingTracking(false);
      }
    }
  }

  if (error) {
    return (
      <section aria-label="Research Runs">
        <h1>ResearchRun</h1>
        <p role="alert">{error}</p>
        <button onClick={refresh}>Retry</button>
      </section>
    );
  }
  if (runId && run === null) {
    return <section aria-label="Research Runs"><p>Loading ResearchRun…</p></section>;
  }
  if (!runId && items === null) {
    return <section aria-label="Research Runs"><p>Loading Research Runs…</p></section>;
  }
  if (run) {
    return (
      <section aria-label="Research Runs" className="research-run-page">
        <header className="research-run-header">
          <div>
            <p className="eyebrow">Immutable research execution</p>
            <h1>ResearchRun</h1>
          </div>
          <div>
            {run.status === "queued" || run.status === "running" ? (
              <button disabled={canceling} onClick={() => void cancel()}>
                {canceling ? "Cancelling…" : "Cancel"}
              </button>
            ) : null}
            {["succeeded", "failed", "cancelled"].includes(run.status) ? (
              <button
                disabled={rerunning || startingTracking}
                onClick={() => void rerunSelected()}
              >
                {rerunning ? "Rerunning…" : "Rerun"}
              </button>
            ) : null}
            {run.status === "succeeded" ? (
              <button
                disabled={rerunning || startingTracking}
                onClick={() => void startTracking()}
              >
                {startingTracking ? "Starting Tracking…" : "Start Tracking"}
              </button>
            ) : null}
            <button
              disabled={loadState !== null || canceling || rerunning || startingTracking}
              onClick={refresh}
            >
              Refresh
            </button>
          </div>
        </header>
        {loadState === "refreshing" ? (
          <p role="status">Refreshing ResearchRun…</p>
        ) : null}
        <div className="research-run-facts">
          <p><strong>Status</strong> {run.status}</p>
          <p>
            <strong>Definition</strong>{" "}
            <a href={`/definitions/${run.definition_id}`}>
              Revision {run.definition_revision}
            </a>
          </p>
          <p><strong>Dataset Release</strong> {run.dataset_release_id}</p>
          {run.rerun_of_id ? (
            <p>
              <strong>Rerun of</strong>{" "}
              <a href={`/research-runs/${run.rerun_of_id}`}>{run.rerun_of_id}</a>
            </p>
          ) : null}
        </div>
        {run.status === "failed" && run.failure_reason ? (
          <p role="alert"><strong>Failure</strong> {run.failure_reason}</p>
        ) : null}
        {run.status === "succeeded" && run.result ? (
          <ResearchAnalysisView analysis={run.result} />
        ) : null}
      </section>
    );
  }
  return (
    <section aria-label="Research Runs">
      <h1>Research Runs</h1>
      {items?.length === 0 ? <p>No Research Runs yet.</p> : null}
      <ol aria-label="Research Runs">
        {items?.map((item) => (
          <li key={item.id}>
            <a href={`/research-runs/${item.id}`}>{item.id}</a>
            <span> · {item.status}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
