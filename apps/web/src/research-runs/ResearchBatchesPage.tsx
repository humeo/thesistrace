import { readBatchCancelError, type BatchCancelError } from "./errors";
import { useTranslation } from "react-i18next";
import { i18n } from "../i18n";
import { formatNumber, formatUtcTimestamp } from "../i18n/format";
import { useEffect, useRef, useState } from "react";
import { coreFetch } from "../auth/coreFetch";
import { followCoreLink, navigateCorePath } from "../shell/navigation";
import { ResearchRunsNavigation } from "./ResearchRunsNavigation";
import { Page, PageContent, PageHeader, Section } from "../components/layout/Page";
import { PageNavigation } from "../components/layout/PageNavigation";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Empty, EmptyHeader, EmptyTitle } from "../components/ui/empty";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Progress, ProgressLabel } from "../components/ui/progress";
import { ToggleGroup, ToggleGroupItem } from "../components/ui/toggle-group";
import { AlertDialog, AlertDialogTrigger, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from "../components/ui/alert-dialog";

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
  return <Badge variant={status === "failed" || status === "completed_with_failures" ? "destructive" : status === "succeeded" ? "default" : "outline"}>{statusLabel(status)}</Badge>;
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

  return <Page className="console-workspace" aria-label={t("title")}>
    <PageContent className="flex flex-col gap-6">
      <PageHeader variant="console" className="mb-0" title={batchId ? t("batch") : i18n.t("runs:title")} actions={batchId
        ? <Button variant="outline" nativeButton={false} role="link" render={<a href="/research-runs/batches" onClick={followCoreLink} />}>{t("back")}</Button> : undefined} />
      {!batchId && <ResearchRunsNavigation active="batches" />}
      {error && <Alert variant="destructive"><AlertDescription>{t(error)}<Button variant="outline" onClick={() => setRefresh(value => value + 1)}>{t("reload")}</Button></AlertDescription></Alert>}
      {batchId ? batch?.id === batchId ? <>
        <Section title={kindLabel(batch)} actions={<>
          <BatchStatusLabel status={batch.status} />
          {active(batch.status) && <ResearchBatchCancelButton key={batch.id} batchId={batch.id} status={batch.status} onAccepted={accepted} />}
        </>}>
          <p className="m-0 text-sm text-muted-foreground">{createdLabel(batch)}</p>
          <code className="text-xs [overflow-wrap:anywhere]">{batch.id}</code>
          <BatchProgress batch={batch} />
          <dl className="m-0 grid gap-4 border-y border-border py-4 sm:grid-cols-3">
            <div><dt className="text-xs text-muted-foreground">{t("period")}</dt><dd className="m-0 text-sm">{batch.scope.start_date} — {batch.scope.end_date}</dd></div>
            <div><dt className="text-xs text-muted-foreground">{t("universe")}</dt><dd className="m-0 text-sm">{i18n.t("research:top", { count: Number(batch.scope.universe.slice(3)) })}</dd></div>
            <div><dt className="text-xs text-muted-foreground">{t("neutralization")}</dt><dd className="m-0 text-sm">{i18n.t(batch.scope.neutralization === "industry" ? "research:industry" : "research:none")}</dd></div>
          </dl>
        </Section>
        {batch.status === "cancelling" && <p role="status">{t("cancellationRequested")}</p>}
        {batch.status === "cancelled" && <p role="status">{t("cancelledRetained")}</p>}
        <Section title={<>{t("research")} · {formatNumber(batch.items.length)}</>}><BatchItems items={batch.items} /></Section>
      </> : loading ? <p role="status">{t("loadingBatch")}</p> : null : <>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <ToggleGroup aria-label={t("filter")} value={[activeOnly ? "active" : "all"]} onValueChange={values => {
            if (!values.length) return;
            const value = values[0] === "active";
            if (value === activeOnly) return;
            setActiveOnly(value); setCursors([null]); setItems(null); setNextCursor(null);
          }} variant="outline">
            <ToggleGroupItem value="active">{t("active")}</ToggleGroupItem>
            <ToggleGroupItem value="all">{t("all")}</ToggleGroupItem>
          </ToggleGroup>
          <Button variant="outline" onClick={() => setRefresh(value => value + 1)} disabled={loading}>{t("reload")}</Button>
        </div>
        {items === null && loading && <p role="status">{t("loadingBatches")}</p>}
        {items?.length === 0 && !error && <Empty><EmptyHeader><EmptyTitle>{t(activeOnly ? "emptyActive" : "empty")}</EmptyTitle></EmptyHeader></Empty>}
        {items && items.length > 0 && <Table density="comfortable" scrollLabel={t("title")} className="min-w-[720px]">
          <TableHeader><TableRow><TableHead scope="col">{t("batchColumn")}</TableHead><TableHead scope="col">{t("created")}</TableHead><TableHead scope="col">{t("completed")}</TableHead><TableHead scope="col">{t("status")}</TableHead><TableHead scope="col" aria-label={t("actions")} /></TableRow></TableHeader>
          <TableBody>{items.map(item => <TableRow key={item.id}>
            <TableCell className="min-w-48 max-w-72 whitespace-normal [overflow-wrap:anywhere]"><a className="block min-h-11 content-center text-primary underline-offset-4 hover:underline md:min-h-0" href={batchPath(item.id)} onClick={followCoreLink}>{kindLabel(item)}<code className="block text-xs">{item.id}</code></a></TableCell>
            <TableCell><time dateTime={item.created_at}>{createdLabel(item)}</time></TableCell>
            <TableCell>{formatNumber(taskCounts(item).completed)} / {formatNumber(taskCounts(item).total)}</TableCell>
            <TableCell><BatchStatusLabel status={item.status} /></TableCell>
            <TableCell>{active(item.status) && <ResearchBatchCancelButton batchId={item.id} status={item.status} onAccepted={accepted} />}</TableCell>
          </TableRow>)}</TableBody>
        </Table>}
        <PageNavigation label={t("pages")} previousLabel={t("previous")} nextLabel={t("next")}
          previousDisabled={cursors.length === 1 || loading} nextDisabled={!nextCursor || loading}
          onPrevious={() => { setCursors(values => values.slice(0, -1)); setItems(null); }}
          onNext={() => { if (nextCursor) { setCursors(values => [...values, nextCursor]); setItems(null); } }}>
          {t("page", { page: formatNumber(cursors.length) })}
        </PageNavigation>
      </>}
    </PageContent>
  </Page>;
}

function BatchProgress({ batch }: { batch: ResearchBatch }) {
  const { t } = useTranslation("batches");
  const { completed, total } = taskCounts(batch);
  return <Progress value={total > 0 ? completed / total * 100 : null}>
    <ProgressLabel>{t("completedResearch")}: {formatNumber(completed)} / {formatNumber(total)}</ProgressLabel>
  </Progress>;
}

function BatchItems({ items, links = true }: { items: BatchItem[]; links?: boolean }) {
  const { t } = useTranslation("batches");
  return <ul className="m-0 flex list-none flex-col p-0">{items.map(item => <li key={item.research_run_id} className="flex min-w-0 items-start justify-between gap-4 border-b border-border py-3 text-sm">
    {links && item.run_availability === "available" ? <a className="block min-h-11 min-w-0 flex-1 content-center text-primary [overflow-wrap:anywhere] hover:underline md:min-h-0" href={`/research-runs/${encodeURIComponent(item.research_run_id)}`} onClick={followCoreLink}>{item.item_key}</a>
      : <span className="min-w-0 [overflow-wrap:anywhere]">{item.item_key}{item.run_availability === "deleted" ? t("deleted") : ""}</span>}
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
  const submittingRef = useRef(false);
  const keepButton = useRef<HTMLButtonElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const controller = useRef<AbortController | null>(null);
  const requestId = useRef<string | null>(null);
  useEffect(() => { requestId.current = null; }, [batchId]);

  useEffect(() => {
    if (!open) return;
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
    return () => request.abort();
  }, [batchId, open, reload]);
  useEffect(() => () => { controller.current?.abort(); }, []);

  async function confirm() {
    if (!batch || !cancellable(batch.status) || submittingRef.current) return;
    submittingRef.current = true;
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
      setOpen(false);
      onAccepted?.(updated);
      if (window.location.pathname !== batchPath(batchId)) navigateCorePath(batchPath(batchId));

    } catch {
      if (!request.signal.aborted) setError(failureMessage);
    } finally {
      submittingRef.current = false;
      if (!request.signal.aborted) setSubmitting(false);
    }
  }

  const unfinished = batch?.items.filter(item => active(item.status)) ?? [];
  return <AlertDialog open={open} onOpenChange={(next, event) => {
    if (submittingRef.current) { event.cancel(); return; }
    setOpen(next);
  }}>
    <AlertDialogTrigger ref={trigger} render={<Button variant="outline" />} disabled={status === "cancelling"}>
      {t(status === "cancelling" ? "cancelling" : "cancel")}
    </AlertDialogTrigger>
    <AlertDialogContent className="w-[calc(100%-2rem)] max-w-[560px] max-h-[calc(100dvh-3rem)] overflow-y-auto p-6 sm:max-w-[560px]" initialFocus={keepButton} finalFocus={trigger}>
      <AlertDialogHeader><AlertDialogTitle>{t("cancelTitle")}</AlertDialogTitle>
        <AlertDialogDescription render={<div />}>
          {batch ? <>
            <p>{kindLabel(batch)} · {createdLabel(batch)}</p>
            <code className="[overflow-wrap:anywhere]">{batch.id}</code>
            <p>{cancellable(batch.status) ? t("unfinished", { count: unfinished.length }) : t("currentStatus", { status: statusLabel(batch.status).toLowerCase() })}</p>
          </> : !error ? <p role="status">{t("loadingAffected")}</p> : null}
        </AlertDialogDescription>
      </AlertDialogHeader>
      {batch && <div className="max-h-64 overflow-y-auto" tabIndex={0} role="region" aria-label={t("research")}><BatchItems items={batch.items} links={false} /></div>}
      {error && <Alert variant="destructive"><AlertDescription>{t(error)}<Button variant="outline" disabled={submitting} onClick={() => setReload(value => value + 1)}>{t("reloadBatch")}</Button></AlertDescription></Alert>}
      <AlertDialogFooter>
        <AlertDialogCancel ref={keepButton} disabled={submitting}>{t("keep")}</AlertDialogCancel>
        <AlertDialogAction variant="destructive" disabled={!batch || !cancellable(batch.status) || submitting} onClick={() => void confirm()}>
          {t(submitting ? "cancelling" : "cancel")}
        </AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>;
}
