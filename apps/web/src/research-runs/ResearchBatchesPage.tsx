import { readBatchCancelError, type BatchCancelError } from "./errors";
import { useTranslation } from "react-i18next";
import { i18n } from "../i18n";
import { formatNumber, formatUtcTimestamp } from "../i18n/format";
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
function kindLabel(batch: ResearchBatch) { return i18n.t(batch.batch_kind === "factor_evaluation" ? "batches:factor" : "batches:strategy"); }
function createdLabel(batch: ResearchBatch) { return formatUtcTimestamp(batch.created_at, true); }
function taskCounts(batch: ResearchBatch) {
  const progress = batch.progress;
  return "completed_factor_tasks" in progress
    ? { completed: progress.completed_factor_tasks, total: progress.total_factor_tasks }
    : { completed: progress.completed_strategy_tasks, total: progress.total_strategy_tasks };
}
function statusLabel(status: BatchStatus) { return i18n.t(`batches:statuses.${status}`); }
function BatchStatusLabel({ status }: { status: BatchStatus }) {
  useTranslation("batches");
  return <span className={`batch-status batch-status-${status}`}>{statusLabel(status)}</span>;
}

export function ResearchBatchesPage({ batchId }: { batchId?: string }) {
  const { t } = useTranslation("batches");
  const [activeOnly, setActiveOnly] = useState(true);
  const [cursors, setCursors] = useState<Array<string | null>>([null]);
  const [items, setItems] = useState<ResearchBatch[] | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [batch, setBatch] = useState<ResearchBatchDetail | null>(null);
  const [error, setError] = useState<"loadBatch" | "loadBatches" | null>(null);
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
      } catch {
        if (controller.signal.aborted) return;
        setLoading(false);
        setError(batchId ? "loadBatch" : "loadBatches");
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
    <section aria-label={t("title") } className="research-batches-page">
      <header className="page-header batch-page-header">
        <h1>{batchId ? t("batch") : i18n.t("runs:title")}</h1>
        {batchId ? <a href="/research-runs/batches" onClick={followCoreLink}>{t("back")} </a> : null}
      </header>
      {!batchId ? <ResearchRunsNavigation active="batches" /> : null}
      {error ? <div className="batch-load-error" role="alert">{t(error)}<button onClick={() => setRefresh(value => value + 1)}>{t("reload")} </button></div> : null}
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
            <div><dt>{t("period")} </dt><dd>{batch.scope.start_date} — {batch.scope.end_date}</dd></div>
            <div><dt>{t("universe")} </dt><dd>{i18n.t("research:top", { count: Number(batch.scope.universe.slice(3)) })}</dd></div>
            <div><dt>{t("neutralization")} </dt><dd>{i18n.t(batch.scope.neutralization === "industry" ? "research:industry" : "research:none")}</dd></div>
            <div><dt>{t("completedResearch")} </dt><dd>{formatNumber(taskCounts(batch).completed)} / {formatNumber(taskCounts(batch).total)}</dd></div>
          </dl>
          {batch.status === "cancelling" ? <p role="status">{t("cancellationRequested")} </p> : null}
          {batch.status === "cancelled" ? <p role="status">{t("cancelledRetained")} </p> : null}
          <section aria-label={t("research") } className="batch-items-section">
            <h2>{t("research")} <span>{formatNumber(batch.items.length)}</span></h2>
            <BatchItems items={batch.items} />
          </section>
        </>
      ) : loading ? <p role="status">{t("loadingBatch")} </p> : null : (
        <>
          <div className="batch-list-toolbar">
            <div aria-label={t("filter") } className="batch-filter-buttons">
              {([true, false] as const).map(value => <button key={String(value)} aria-pressed={activeOnly === value} onClick={() => {
                if (value === activeOnly) return;
                setActiveOnly(value); setCursors([null]); setItems(null); setNextCursor(null);
              }}>{t(value ? "active" : "all")}</button>)}
            </div>
            <button onClick={() => setRefresh(value => value + 1)} disabled={loading}>{t("reload")} </button>
          </div>
          {items === null && loading ? <p role="status">{t("loadingBatches")} </p> : null}
          {items?.length === 0 ? <p className="batch-empty">{t(activeOnly ? "emptyActive" : "empty")}</p> : null}
          {items && items.length > 0 ? <div className="batch-table-scroll"><table className="batch-table">
            <thead><tr><th scope="col">{t("batchColumn")} </th><th scope="col">{t("created")} </th><th scope="col">{t("completed")} </th><th scope="col">{t("status")} </th><th scope="col" aria-label={t("actions") } /></tr></thead>
            <tbody>{items.map(item => <tr key={item.id}>
              <th scope="row"><a href={batchPath(item.id)} onClick={followCoreLink}>{kindLabel(item)}<code>{item.id}</code></a></th>
              <td data-label={t("created") }><time dateTime={item.created_at}>{createdLabel(item)}</time></td>
              <td data-label={t("completed") }>{formatNumber(taskCounts(item).completed)} / {formatNumber(taskCounts(item).total)}</td>
              <td data-label={t("status") }><BatchStatusLabel status={item.status} /></td>
              <td>{active(item.status) ? <ResearchBatchCancelButton batchId={item.id} status={item.status} onAccepted={accepted} /> : null}</td>
            </tr>)}</tbody>
          </table></div> : null}
          <nav aria-label={t("pages") } className="batch-pagination">
            <span>{t("page", { page: formatNumber(cursors.length) })}</span>
            <button disabled={cursors.length === 1 || loading} onClick={() => { setCursors(values => values.slice(0, -1)); setItems(null); }}>{t("previous")} </button>
            <button disabled={!nextCursor || loading} onClick={() => { if (nextCursor) { setCursors(values => [...values, nextCursor]); setItems(null); } }}>{t("next")} </button>
          </nav>
        </>
      )}
    </section>
  );
}

function BatchItems({ items, links = true }: { items: BatchItem[]; links?: boolean }) {
  const { t } = useTranslation("batches");
  return <ul className="batch-items">{items.map(item => <li key={item.research_run_id}>
    {links && item.run_availability === "available" ? <a href={`/research-runs/${encodeURIComponent(item.research_run_id)}`} onClick={followCoreLink}>{item.item_key}</a>
      : <span>{item.item_key}{item.run_availability === "deleted" ? t("deleted") : ""}</span>}
    <BatchStatusLabel status={item.status} />
  </li>)}</ul>;
}

export function ResearchBatchCancelButton({ batchId, status, onAccepted }: {
  batchId: string;
  status: string;
  onAccepted?: (batch: ResearchBatchDetail) => void;
}) {
  const { t } = useTranslation("batches");
  const [open, setOpen] = useState(false);
  const [batch, setBatch] = useState<ResearchBatchDetail | null>(null);
  const [error, setError] = useState<"cancelLoadError" | BatchCancelError | null>(null);
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
      }).catch(() => { if (!request.signal.aborted) setError("cancelLoadError"); });
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
    let failureMessage: BatchCancelError = "cancelError";
    try {
      requestId.current ??= `batch_cancel_${crypto.randomUUID()}`;
      const response = await coreFetch(`/api/research-batches/${encodeURIComponent(batchId)}/cancel`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: requestId.current }), signal: request.signal,
      });
      if (!response.ok) {
        failureMessage = await readBatchCancelError(response);
        if (response.status === 409) setBatch(null);
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
      {t(status === "cancelling" ? "cancelling" : "cancel")}
    </button>
    {open ? <dialog ref={dialog} className="batch-cancel-dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId}
      onCancel={event => { event.preventDefault(); dismiss(); }}>
      <h2 id={titleId}>{t("cancelTitle")} </h2>
      <div id={descriptionId}>{batch ? <>
        <p>{kindLabel(batch)} · {createdLabel(batch)}</p>
        <code>{batch.id}</code>
        <p>{cancellable(batch.status) ? t("unfinished", { count: unfinished.length })
          : t("currentStatus", { status: statusLabel(batch.status).toLowerCase() })}</p>
      </> : !error ? <p role="status">{t("loadingAffected")} </p> : null}</div>
      {batch ? <BatchItems items={batch.items} links={false} /> : null}
      {error ? <div role="alert" className="inline-status-error"><p>{t(error)}</p><button disabled={submitting} onClick={() => setReload(value => value + 1)}>{t("reloadBatch")} </button></div> : null}
      <footer>
        <button autoFocus disabled={submitting} onClick={dismiss}>{t("keep")} </button>
        <button className="button-danger" disabled={!batch || !cancellable(batch.status) || submitting} onClick={() => void confirm()}>
          {t(submitting ? "cancelling" : "cancel")}
        </button>
      </footer>
    </dialog> : null}
  </>;
}
