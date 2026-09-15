import { useEffect, useId, useRef, useState } from "react";
import { coreFetch } from "../auth/coreFetch";
import { followCoreLink, navigateCorePath } from "../shell/navigation";
import { ResearchRunsNavigation } from "./ResearchRunsNavigation";
import "./researchBatches.css";

type BatchStatus = "queued" | "running" | "cancelling" | "succeeded" | "completed_with_failures" | "failed" | "cancelled";
export type ResearchBatch = {
  id: string;
  batch_kind: "factor_evaluation" | "strategy_sweep";
  status: BatchStatus;
  created_at: string;
  scope: { start_date: string; end_date: string; universe: string; neutralization: string };
  progress: { completed_factor_tasks: number; total_factor_tasks: number }
    | { completed_strategy_tasks: number; total_strategy_tasks: number; shared_alpha_factor_status: string };
};
type BatchItem = {
  ordinal: number;
  item_key: string;
  research_run_id: string;
  status: Exclude<BatchStatus, "completed_with_failures">;
  run_availability: "available" | "deleted";
};
export type ResearchBatchDetail = ResearchBatch & {
  items: BatchItem[];
  live_progress: { estimated_percentage: number; phase: string } | null;
};
type BatchList = { items: ResearchBatch[]; next_cursor: string | null };

function batchPath(id: string) { return `/research-runs/batches/${encodeURIComponent(id)}`; }
function active(status: BatchStatus) { return ["queued", "running", "cancelling"].includes(status); }
function cancellable(status: BatchStatus) { return status === "queued" || status === "running"; }
function kindLabel(batch: ResearchBatch) { return batch.batch_kind === "factor_evaluation" ? "Factor evaluation" : "Strategy sweep"; }
function createdLabel(batch: ResearchBatch) { return `${batch.created_at.slice(0, 19).replace("T", " ")} UTC`; }
function taskCounts(batch: ResearchBatch) {
  const progress = batch.progress;
  return "completed_factor_tasks" in progress
    ? { completed: progress.completed_factor_tasks, total: progress.total_factor_tasks }
    : { completed: progress.completed_strategy_tasks, total: progress.total_strategy_tasks };
}
function statusLabel(status: BatchStatus) {
  return ({ queued: "Queued", running: "Running", cancelling: "Cancelling…", succeeded: "Completed",
    completed_with_failures: "Completed with failures", failed: "Failed", cancelled: "Cancelled" })[status];
}
function BatchStatusLabel({ status }: { status: BatchStatus }) {
  return <span className={`batch-status batch-status-${status}`}>{statusLabel(status)}</span>;
}

export function ResearchBatchesPage({ batchId }: { batchId?: string }) {
  const [activeOnly, setActiveOnly] = useState(true);
  const [cursors, setCursors] = useState<Array<string | null>>([null]);
  const [items, setItems] = useState<ResearchBatch[] | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [batch, setBatch] = useState<ResearchBatchDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const cursor = cursors.at(-1) ?? null;

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({ limit: "20", active_only: String(activeOnly) });
    if (cursor !== null) params.set("cursor", cursor);
    const path = batchId ? `/api/research-batches/${encodeURIComponent(batchId)}` : `/api/research-batches?${params}`;
    async function load() {
      try {
        const response = await coreFetch(path, { signal: controller.signal });
        if (!response.ok) throw new Error(batchId ? "Batch unavailable. Try reloading." : "Batches unavailable. Try reloading.");
        if (batchId) {
          const detail = await response.json() as ResearchBatchDetail;
          if (controller.signal.aborted) return;
          setBatch(detail);
          if (active(detail.status)) timer = setTimeout(() => void load(), 2000);
        } else {
          const page = await response.json() as BatchList;
          if (controller.signal.aborted) return;
          setItems(page.items);
          setNextCursor(page.next_cursor);
          timer = setTimeout(() => void load(), 5000);
        }
        setLoading(false);
      } catch (reason) {
        if (controller.signal.aborted) return;
        setLoading(false);
        setError(reason instanceof Error ? reason.message : "Batches unavailable. Try reloading.");
      }
    }
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [activeOnly, batchId, cursor, refresh]);

  function accepted(detail: ResearchBatchDetail) {
    setBatch(detail);
    setRefresh(value => value + 1);
    if (!batchId) navigateCorePath(batchPath(detail.id));
  }

  return (
    <section aria-label="Research batches" className="research-batches-page">
      <header className="page-header batch-page-header">
        <h1>{batchId ? "Research batch" : "Research Runs"}</h1>
        {batchId ? <a href="/research-runs/batches" onClick={followCoreLink}>Back to Batches</a> : null}
      </header>
      {!batchId ? <ResearchRunsNavigation active="batches" /> : null}
      {error ? <div className="batch-load-error" role="alert">{error}<button onClick={() => setRefresh(value => value + 1)}>Reload</button></div> : null}
      {batchId ? batch?.id === batchId ? (
        <>
          <header className="batch-detail-heading">
            <div><h2>{kindLabel(batch)}</h2><p>{createdLabel(batch)}</p><code>{batch.id}</code></div>
            <div className="batch-detail-actions">
              <BatchStatusLabel status={batch.status} />
              {active(batch.status) ? <ResearchBatchCancelButton batchId={batch.id} status={batch.status} onAccepted={accepted} /> : null}
            </div>
          </header>
          <dl className="batch-scope">
            <div><dt>Research period</dt><dd>{batch.scope.start_date} — {batch.scope.end_date}</dd></div>
            <div><dt>Universe</dt><dd>{batch.scope.universe.replace(/^top/, "Top ")}</dd></div>
            <div><dt>Neutralization</dt><dd>{batch.scope.neutralization === "industry" ? "Industry" : "None"}</dd></div>
            <div><dt>Completed research</dt><dd>{taskCounts(batch).completed} / {taskCounts(batch).total}</dd></div>
          </dl>
          {batch.status === "cancelling" ? <p role="status">Cancellation requested. Waiting for the running work to stop.</p> : null}
          {batch.status === "cancelled" ? <p role="status">Batch cancelled. Completed results are retained.</p> : null}
          <section aria-label="Research in this batch" className="batch-items-section">
            <h2>Research in this batch <span>{batch.items.length}</span></h2>
            <BatchItems items={batch.items} />
          </section>
        </>
      ) : loading ? <p role="status">Loading batch…</p> : null : (
        <>
          <div className="batch-list-toolbar">
            <div aria-label="Batch status filter" className="batch-filter-buttons">
              {([true, false] as const).map(value => <button key={String(value)} aria-pressed={activeOnly === value} onClick={() => {
                if (value === activeOnly) return;
                setActiveOnly(value); setCursors([null]); setItems(null); setNextCursor(null);
              }}>{value ? "Active" : "All batches"}</button>)}
            </div>
            <button onClick={() => setRefresh(value => value + 1)} disabled={loading}>Reload</button>
          </div>
          {items === null && loading ? <p role="status">Loading batches…</p> : null}
          {items?.length === 0 ? <p className="batch-empty">{activeOnly ? "No queued or running batches." : "No research batches yet."}</p> : null}
          {items && items.length > 0 ? <div className="batch-table-scroll"><table className="batch-table">
            <thead><tr><th scope="col">Batch</th><th scope="col">Created</th><th scope="col">Completed</th><th scope="col">Status</th><th scope="col" aria-label="Actions" /></tr></thead>
            <tbody>{items.map(item => <tr key={item.id}>
              <th scope="row"><a href={batchPath(item.id)} onClick={followCoreLink}>{kindLabel(item)}<code>{item.id}</code></a></th>
              <td data-label="Created"><time dateTime={item.created_at}>{createdLabel(item)}</time></td>
              <td data-label="Completed">{taskCounts(item).completed} / {taskCounts(item).total}</td>
              <td data-label="Status"><BatchStatusLabel status={item.status} /></td>
              <td>{active(item.status) ? <ResearchBatchCancelButton batchId={item.id} status={item.status} onAccepted={accepted} /> : null}</td>
            </tr>)}</tbody>
          </table></div> : null}
          <nav aria-label="Batch pages" className="batch-pagination">
            <span>Page {cursors.length}</span>
            <button disabled={cursors.length === 1 || loading} onClick={() => { setCursors(values => values.slice(0, -1)); setItems(null); }}>Previous</button>
            <button disabled={!nextCursor || loading} onClick={() => { if (nextCursor) { setCursors(values => [...values, nextCursor]); setItems(null); } }}>Next</button>
          </nav>
        </>
      )}
    </section>
  );
}

function BatchItems({ items, links = true }: { items: BatchItem[]; links?: boolean }) {
  return <ul className="batch-items">{items.map(item => <li key={item.research_run_id}>
    {links && item.run_availability === "available" ? <a href={`/research-runs/${encodeURIComponent(item.research_run_id)}`} onClick={followCoreLink}>{item.item_key}</a>
      : <span>{item.item_key}{item.run_availability === "deleted" ? " (deleted)" : ""}</span>}
    <BatchStatusLabel status={item.status} />
  </li>)}</ul>;
}

export function ResearchBatchCancelButton({ batchId, status, onAccepted }: {
  batchId: string;
  status: string;
  onAccepted?: (batch: ResearchBatchDetail) => void;
}) {
  const [open, setOpen] = useState(false);
  const [batch, setBatch] = useState<ResearchBatchDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [reload, setReload] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const controller = useRef<AbortController | null>(null);
  const requestId = useRef<string | null>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    if (!open) return;
    const element = dialog.current!;
    element.showModal();
    const request = new AbortController();
    controller.current = request;
    setBatch(null);
    setError(null);
    void coreFetch(`/api/research-batches/${encodeURIComponent(batchId)}`, { signal: request.signal })
      .then(async response => {
        if (!response.ok) throw new Error("Batch unavailable. Reload before cancelling.");
        const detail = await response.json() as ResearchBatchDetail;
        if (!request.signal.aborted) setBatch(detail);
      }).catch(() => { if (!request.signal.aborted) setError("Batch unavailable. Reload before cancelling."); });
    return () => { request.abort(); if (element.open) element.close(); };
  }, [batchId, open, reload]);
  useEffect(() => () => { controller.current?.abort(); }, []);

  function dismiss() {
    if (submitting) return;
    dialog.current?.close();
    setOpen(false);
    trigger.current?.focus();
  }

  async function confirm() {
    if (!batch || !cancellable(batch.status) || submitting) return;
    setSubmitting(true);
    setError(null);
    const request = new AbortController();
    controller.current = request;
    let failureMessage = "Batch cancellation failed. Try again.";
    try {
      requestId.current ??= `batch_cancel_${crypto.randomUUID()}`;
      const response = await coreFetch(`/api/research-batches/${encodeURIComponent(batchId)}/cancel`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: requestId.current }), signal: request.signal,
      });
      if (!response.ok) {
        if (response.status === 409) {
          setBatch(null);
          failureMessage = "Batch state changed. Reload to see its current status.";
        }
        throw new Error(failureMessage);
      }
      const updated = await response.json() as ResearchBatchDetail;
      if (request.signal.aborted) return;
      dialog.current?.close();
      setOpen(false);
      onAccepted?.(updated);
      if (window.location.pathname !== batchPath(batchId)) navigateCorePath(batchPath(batchId));
      else trigger.current?.focus();
    } catch {
      if (!request.signal.aborted) setError(failureMessage);
    } finally {
      if (!request.signal.aborted) setSubmitting(false);
    }
  }

  const unfinished = batch?.items.filter(item => active(item.status)) ?? [];
  return <>
    <button ref={trigger} type="button" disabled={status === "cancelling"} aria-haspopup="dialog" onClick={() => setOpen(true)}>
      {status === "cancelling" ? "Cancelling…" : "Cancel batch"}
    </button>
    {open ? <dialog ref={dialog} className="batch-cancel-dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId}
      onCancel={event => { event.preventDefault(); dismiss(); }}>
      <h2 id={titleId}>Cancel batch?</h2>
      <div id={descriptionId}>{batch ? <>
        <p>{kindLabel(batch)} · {createdLabel(batch)}</p>
        <code>{batch.id}</code>
        <p>{cancellable(batch.status) ? `${unfinished.length} unfinished research ${unfinished.length === 1 ? "run will" : "runs will"} be cancelled. Completed results will remain.`
          : `This batch is ${statusLabel(batch.status).toLowerCase()}.`}</p>
      </> : !error ? <p role="status">Loading affected research…</p> : null}</div>
      {batch ? <BatchItems items={batch.items} links={false} /> : null}
      {error ? <div role="alert" className="inline-status-error"><p>{error}</p><button disabled={submitting} onClick={() => setReload(value => value + 1)}>Reload batch</button></div> : null}
      <footer>
        <button autoFocus disabled={submitting} onClick={dismiss}>Keep batch</button>
        <button className="button-danger" disabled={!batch || !cancellable(batch.status) || submitting} onClick={() => void confirm()}>
          {submitting ? "Cancelling…" : "Cancel batch"}
        </button>
      </footer>
    </dialog> : null}
  </>;
}
