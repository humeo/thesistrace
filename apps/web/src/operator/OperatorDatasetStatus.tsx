import { type ReactNode, useEffect, useRef, useState } from "react";

import { catalogLabel } from "../i18n/catalog";
import { i18n, useTranslation } from "../i18n";
import { formatNumber } from "../i18n/format";

import { OperatorPageNotFoundError } from "./operatorDirectoryClient";
import { FinancialRefreshTelemetry } from "./FinancialRefreshTelemetry";
import {
  OperatorDataRefreshActionDialog,
  type DataRefreshStatusAction,
} from "./OperatorDataRefreshActionDialog";
import {
  type DataRefreshKind,
  type DataRefreshOperationalStatus,
  type DatasetOperationalStatus,
  loadDatasetOperationalStatus,
} from "./operatorDataStatusClient";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { PageNavigation } from "../components/layout/PageNavigation";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter } from "../components/ui/sheet";
import { operatorDataClasses as styles } from "./operatorDataClasses";

const pollIntervalMilliseconds = 5_000;
const refreshKinds = ["dataset"] as const;

export function OperatorDatasetStatus({
  onAccessNotFound,
  reloadGeneration,
  onActionCompleted,
}: Readonly<{
  onAccessNotFound: () => void;
  reloadGeneration: number;
  onActionCompleted?: (receipt: import("./operatorMutationClient").DataRefreshActionReceipt) => void;
}>) {
  useTranslation("operator");
  const [data, setData] = useState<DatasetOperationalStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [cursors, setCursors] = useState<readonly (string | null)[]>([null]);
  const [manualReloadGeneration, setManualReloadGeneration] = useState(0);
  const [selected, setSelected] = useState<DataRefreshOperationalStatus | null>(null);
  const [action, setAction] = useState<DataRefreshStatusAction | null>(null);
  const currentPage = useRef<Readonly<{
    cursor: string | null;
    data: DatasetOperationalStatus;
  }> | null>(null);
  const detailsTrigger = useRef<HTMLButtonElement | null>(null);
  const actionTrigger = useRef<HTMLButtonElement | null>(null);
  const cursor = cursors.at(-1) ?? null;

  useEffect(() => {
    let disposed = false;
    let timer: number | undefined;
    let controller: AbortController | null = null;
    let requestGeneration = 0;
    let lastKnown = currentPage.current?.cursor === cursor
      ? currentPage.current.data
      : null;

    const clearTimer = (): void => {
      window.clearTimeout(timer);
      timer = undefined;
    };
    const schedule = (): void => {
      clearTimer();
      if (
        disposed
        || document.visibilityState !== "visible"
        || lastKnown === null
        || !datasetStatusNeedsPolling(lastKnown)
      ) return;
      timer = window.setTimeout(() => void load(), pollIntervalMilliseconds);
    };
    const load = async (): Promise<void> => {
      if (disposed || document.visibilityState !== "visible") return;
      clearTimer();
      controller?.abort();
      controller = new AbortController();
      const generation = ++requestGeneration;
      setLoading(true);
      try {
        const next = await loadDatasetOperationalStatus(cursor, controller.signal);
        if (disposed || generation !== requestGeneration) return;
        lastKnown = next;
        currentPage.current = { cursor, data: next };
        setData(next);
        setError(false);
        setLoading(false);
        schedule();
      } catch (reason) {
        if (
          disposed
          || generation !== requestGeneration
          || (reason instanceof DOMException && reason.name === "AbortError")
        ) return;
        setLoading(false);
        if (reason instanceof OperatorPageNotFoundError) {
          clearTimer();
          onAccessNotFound();
          return;
        }
        setError(true);
        schedule();
      }
    };
    const visibilityChanged = (): void => {
      if (document.visibilityState === "visible") void load();
      else {
        clearTimer();
        controller?.abort();
      }
    };
    const refreshOnRecovery = (): void => {
      if (document.visibilityState === "visible") void load();
    };

    document.addEventListener("visibilitychange", visibilityChanged);
    window.addEventListener("focus", refreshOnRecovery);
    window.addEventListener("online", refreshOnRecovery);
    void load();
    return () => {
      disposed = true;
      clearTimer();
      controller?.abort();
      document.removeEventListener("visibilitychange", visibilityChanged);
      window.removeEventListener("focus", refreshOnRecovery);
      window.removeEventListener("online", refreshOnRecovery);
    };
  }, [cursor, manualReloadGeneration, onAccessNotFound, reloadGeneration]);

  useEffect(() => {
    if (data === null) return;
    setSelected((current) => {
      if (current === null) return null;
      return [...data.operations, ...data.latestByKind].find(
        (operation) => operation.idempotencyKey === current.idempotencyKey,
      ) ?? current;
    });
  }, [data]);

  function dismissDetails(): void {
    setSelected(null);
    window.requestAnimationFrame(() => detailsTrigger.current?.focus());
  }

  function dismissAction(): void {
    setAction(null);
    window.requestAnimationFrame(() => actionTrigger.current?.focus());
  }

  function reloadAfterAction(): void {
    setManualReloadGeneration((current) => current + 1);
  }

  return (
    <>
      <OperatorDatasetStatusView
        cursorDepth={cursors.length - 1}
        data={data}
        error={error}
        loading={loading}
        onDetails={(operation, trigger) => {
          detailsTrigger.current = trigger;
          setSelected(operation);
        }}
        onNext={() => {
          if (data?.nextCursor === null || data?.nextCursor === undefined) return;
          setSelected(null);
          setCursors((current) => [...current, data.nextCursor]);
        }}
        onPrevious={() => {
          setSelected(null);
          setCursors((current) => current.length > 1 ? current.slice(0, -1) : current);
        }}
        onReload={() => setManualReloadGeneration((current) => current + 1)}
        onAction={(next, trigger) => {
          actionTrigger.current = trigger;
          setAction(next);
        }}
      />
      {selected === null ? null : (
        <OperatorDataStatusDrawer
          onDismiss={dismissDetails}
          onAction={(next, trigger) => {
            actionTrigger.current = trigger;
            setAction(next);
          }}
          operation={selected}
        />
      )}
      {action === null ? null : (
        <OperatorDataRefreshActionDialog
          action={action}
          onAccessNotFound={onAccessNotFound}
          onDismiss={dismissAction}
          onStateChanged={reloadAfterAction}
          onSucceeded={(receipt) => {
            onActionCompleted?.(receipt);
            setAction(null);
            reloadAfterAction();
            window.requestAnimationFrame(() => actionTrigger.current?.focus());
          }}
        />
      )}
    </>
  );
}

export function OperatorDatasetStatusView({
  cursorDepth,
  data,
  error,
  loading,
  onDetails,
  onNext,
  onPrevious,
  onReload,
  onAction,
}: Readonly<{
  cursorDepth: number;
  data: DatasetOperationalStatus | null;
  error: boolean;
  loading: boolean;
  onDetails: (operation: DataRefreshOperationalStatus, trigger: HTMLButtonElement) => void;
  onNext: () => void;
  onPrevious: () => void;
  onReload: () => void;
  onAction: (action: DataRefreshStatusAction, trigger: HTMLButtonElement) => void;
}>) {
  const { t } = useTranslation("operator");
  return (
    <section
      aria-busy={loading || undefined}
      aria-labelledby="operator-dataset-status-heading"
      className={styles.datasetStatus}
    >
      <header className={styles.sectionHeader}>
        <div>
          <h2 id="operator-dataset-status-heading">{t("data.status.heading")}</h2>
        </div>
        <Button variant="outline" onClick={onReload} type="button">{t("data.status.reload")}</Button>
      </header>

      {data === null ? (
        <div className={styles.loadState}>
          <p role={error ? "alert" : "status"}>
            {error
              ? t("data.status.unavailable")
              : t("data.status.loading")}
          </p>
          {error ? <Button variant="outline" onClick={onReload} type="button">{t("data.status.tryAgain")}</Button> : null}
        </div>
      ) : (
        <>
          <DatasetHeadSummary data={data} />
          <WorkerAvailability data={data} />
          {error ? (
            <Alert variant="destructive" role="alert"><AlertDescription>{t("data.status.stale")}</AlertDescription></Alert>
          ) : null}
          <LatestRefreshTable operations={data.latestByKind} />
          <OperationHistoryTable
            cursorDepth={cursorDepth}
            nextCursor={data.nextCursor}
            onDetails={onDetails}
            onNext={onNext}
            onPrevious={onPrevious}
            onAction={onAction}
            operations={data.operations}
          />
        </>
      )}
    </section>
  );
}

function DatasetHeadSummary({ data }: Readonly<{ data: DatasetOperationalStatus }>) {
  const { t } = useTranslation("operator");
  const head = data.head;
  return (
    <div className={styles.datasetHead}>
      <dl>
        <div>
          <dt>{t("data.status.identity")}</dt>
          <dd><code>{head.dataIdentity ?? t("data.status.noHead")}</code></dd>
        </div>
        <div>
          <dt>{t("data.status.dataThrough")}</dt>
          <dd>{head.dataThroughSession ?? t("data.status.unavailableValue")}</dd>
        </div>
        <div>
          <dt>{t("data.status.prepared")}</dt>
          <dd>{datasetTimestamp(head.preparedAt) ?? t("data.status.notAvailable")}</dd>
        </div>
      </dl>
      <div aria-label={t("data.status.coverage")} role="group">
        <DatasetFamilyStatus
          name={t("data.status.market")}
          status={<ReadinessStatus label={t("data.status.market")} ready={head.marketResearchReadiness} />}
        >
          <DatasetFact label={t("data.status.coverageStart")} value={head.marketCoverageStart} />
          <DatasetFact label={t("data.status.dataThrough")} value={head.dataThroughSession} />
          <DatasetFact label={t("data.status.lastRefresh")} value={datasetTimestamp(head.marketLastRefreshAt)} />
        </DatasetFamilyStatus>
        <DatasetFamilyStatus
          name={t("data.status.benchmarkName", { name: catalogLabel("benchmarks", "csi300-price-index-open") })}
          note={t("data.status.benchmarkNote")}
          status={<ReadinessStatus label={t("data.status.benchmark")} ready={head.benchmarkResearchReadiness} />}
        >
          <DatasetFact label={t("data.status.coverageStart")} value={head.benchmarkCoverageStart} />
          <DatasetFact label={t("data.status.coverageEnd")} value={head.benchmarkCoverageEnd} />
          <DatasetFact label={t("data.status.lastPublication")} value={datasetTimestamp(head.benchmarkLastPublishedAt)} />
        </DatasetFamilyStatus>
        <DatasetFamilyStatus
          name={t("data.status.financial")}
          status={(
            <Badge
              variant={head.financialResearchReadiness === "ready" ? "default" : "secondary"}
              className={`h-auto min-h-5 whitespace-normal text-left ${head.financialResearchReadiness === "ready_with_pending" || head.financialResearchReadiness === "ready_with_gaps" ? "text-[var(--warning)]" : ""}`}
            >
              {financialReadinessText(head.financialResearchReadiness)}
            </Badge>
          )}
        >
          <DatasetFact label={t("data.status.coverageStart")} value={head.financialCoverageStart} />
          <DatasetFact label={t("data.status.disclosureChecked")} value={head.financialAttemptedThroughSession} />
          <DatasetFact label={t("data.status.disclosureComplete")} value={head.financialCompleteThroughSession} />
          <DatasetFact label={t("data.status.statementPending")} value={head.financialPendingInstrumentCount} />
          <DatasetFact label={t("data.status.indicatorPending")} value={head.financialIndicatorPendingInstrumentCount} />
          <DatasetFact label={t("data.status.indicatorChecked")} value={head.financialIndicatorCheckedThroughSession} />
          <DatasetFact label={t("data.status.indicatorComplete")} value={head.financialIndicatorCompleteThroughSession} />
          <DatasetFact label={t("data.status.disclosureGaps")} value={head.financialDiscoveryGapCount} />
          <DatasetFact label={t("data.status.earliestUnresolved")} value={head.financialEarliestUnresolvedDate} />
          <DatasetFact label={t("data.status.lastRefresh")} value={datasetTimestamp(head.financialLastRefreshAt)} />
        </DatasetFamilyStatus>
        <DatasetFamilyStatus
          name={t("data.status.industry")}
          status={<ReadinessStatus label={t("data.status.industry")} ready={head.industryResearchReadiness} />}
        >
          <DatasetFact label={t("data.status.coverageStart")} value={head.industryCoverageStart} />
          <DatasetFact label={t("data.status.observedThrough")} value={head.industryObservationThroughSession} />
          <DatasetFact label={t("data.status.lastRefresh")} value={datasetTimestamp(head.industryLastRefreshAt)} />
        </DatasetFamilyStatus>
      </div>
    </div>
  );
}

function DatasetFamilyStatus({ name, status, note, children }: Readonly<{
  name: string;
  status: ReactNode;
  note?: string;
  children: ReactNode;
}>) {
  const { t } = useTranslation("operator");
  return (
    <section aria-label={t("data.status.familyLabel", { name })} className={styles.datasetFamily}>
      <header>
        <h3>{name}</h3>
        {status}
        {note === undefined ? null : <small>{note}</small>}
      </header>
      <dl>{children}</dl>
    </section>
  );
}

function DatasetFact({ label, value }: Readonly<{ label: string; value: ReactNode }>) {
  const { t } = useTranslation("operator");
  return <div><dt>{label}</dt><dd>{value == null ? <span className="text-muted-foreground">{t("data.status.notAvailable")}</span> : typeof value === "number" ? formatNumber(value) : value}</dd></div>;
}

function datasetTimestamp(value: string | null): ReactNode {
  return value === null ? null : (
    <time dateTime={value} title={value}>
      {new Date(value).toISOString().slice(0, 19).replace("T", " ")} UTC
    </time>
  );
}

function WorkerAvailability({ data }: Readonly<{ data: DatasetOperationalStatus }>) {
  const { t } = useTranslation("operator");
  const worker = data.worker;
  const visibleOperations = [...data.latestByKind, ...data.operations];
  const accepted = visibleOperations.some((operation) => operation.status === "accepted");
  const running = visibleOperations.some((operation) => operation.status === "running");
  return (
    <Alert variant={worker.available ? "default" : "destructive"} role={worker.available ? "status" : "alert"}>
      <AlertDescription className={styles.workerStatus}>
      <strong>
        {worker.available ? t("data.status.workerAvailable") : t("data.status.workerUnavailable")}
      </strong>
      {worker.available ? null : (
        <span>
          {accepted
            ? t("data.status.workerQueued")
            : running
              ? t("data.status.workerRunning")
              : t("data.status.workerNew")}
        </span>
      )}
      <small>{t("data.status.lastHeartbeatLabel")} {timestamp(worker.lastHeartbeatAt)}</small>
      </AlertDescription>
    </Alert>
  );
}

function ReadinessStatus({ label, ready }: Readonly<{ label: string; ready: boolean }>) {
  const { t } = useTranslation("operator");
  return (
    <Badge variant={ready ? "default" : "secondary"} className="h-auto min-h-5 whitespace-normal text-left">
      {t(ready ? "data.status.ready" : "data.status.notReady", { name: label })}
    </Badge>
  );
}

function LatestRefreshTable({
  operations,
}: Readonly<{ operations: readonly DataRefreshOperationalStatus[] }>) {
  const { t } = useTranslation("operator");
  return (
    <section aria-labelledby="operator-latest-refreshes-heading" className={styles.datasetSubsection}>
      <header>
        <h3 id="operator-latest-refreshes-heading">{t("data.status.latestHeading")}</h3>
      </header>
      <Table aria-label={t("data.status.latestTable")} scrollLabel={t("data.status.latestTable")} className={styles.latestTable}>
          <TableHeader><TableRow><TableHead>{t("data.status.kind")}</TableHead><TableHead>{t("data.status.state")}</TableHead><TableHead>{t("data.status.target")}</TableHead><TableHead>{t("data.status.updated")}</TableHead></TableRow></TableHeader>
          <TableBody>
            {refreshKinds.map((kind) => {
              const operation = operations.find((item) => item.kind === kind);
              return (
                <TableRow key={kind}>
                  <TableHead data-label={t("data.status.kind")} scope="row">{kindText(kind)}</TableHead>
                  <TableCell data-label={t("data.status.state")}>
                    {operation === undefined
                      ? <span className="text-muted-foreground">{t("data.status.noOperation")}</span>
                      : <OperationState operation={operation} />}
                  </TableCell>
                  <TableCell data-label={t("data.status.target")}>
                    {operation === undefined ? "—" : operationTarget(operation)}
                  </TableCell>
                  <TableCell data-label={t("data.status.updated")}>
                    {operation === undefined ? "—" : timestamp(operation.updatedAt)}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
    </section>
  );
}

function OperationHistoryTable({
  cursorDepth,
  nextCursor,
  onDetails,
  onNext,
  onPrevious,
  onAction,
  operations,
}: Readonly<{
  cursorDepth: number;
  nextCursor: string | null;
  onDetails: (operation: DataRefreshOperationalStatus, trigger: HTMLButtonElement) => void;
  onNext: () => void;
  onPrevious: () => void;
  onAction: (action: DataRefreshStatusAction, trigger: HTMLButtonElement) => void;
  operations: readonly DataRefreshOperationalStatus[];
}>) {
  const { t } = useTranslation("operator");
  return (
    <section aria-labelledby="operator-operation-history-heading" className={styles.datasetSubsection}>
      <header>
        <h3 id="operator-operation-history-heading">{t("data.status.historyHeading")}</h3>
      </header>
      {operations.length === 0 ? (
        <p className="m-0 py-6 text-sm text-muted-foreground">
          {cursorDepth === 0
            ? t("data.status.noHistory")
            : t("data.status.noOlder")}
        </p>
      ) : (
        <Table aria-label={t("data.status.historyTable")} scrollLabel={t("data.status.historyTable")} className={styles.historyTable}>
            <TableHeader>
              <TableRow>
                <TableHead>{t("data.status.operation")}</TableHead><TableHead>{t("data.status.kind")}</TableHead><TableHead>{t("data.status.state")}</TableHead><TableHead>{t("data.status.target")}</TableHead>
                <TableHead>{t("data.status.attemptPhase")}</TableHead><TableHead>{t("data.status.heartbeat")}</TableHead><TableHead>{t("data.status.created")}</TableHead><TableHead>{t("data.status.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {operations.map((operation) => (
                <TableRow key={operation.idempotencyKey}>
                  <TableHead data-label={t("data.status.operation")} scope="row"><code>{operation.idempotencyKey}</code></TableHead>
                  <TableCell data-label={t("data.status.kind")}>{kindText(operation.kind)}</TableCell>
                  <TableCell data-label={t("data.status.state")}><OperationState operation={operation} /></TableCell>
                  <TableCell data-label={t("data.status.target")}><code>{operationTarget(operation)}</code></TableCell>
                  <TableCell data-label={t("data.status.attemptPhase")}>
                    <span className={styles.operationPhase}>
                      <strong>{formatNumber(operation.attemptCount)}</strong>
                      <small>{operation.phase === null ? t("data.status.notStarted") : phaseText(operation.phase)}</small>
                    </span>
                  </TableCell>
                  <TableCell data-label={t("data.status.heartbeat")}>{timestamp(operation.lastHeartbeatAt)}</TableCell>
                  <TableCell data-label={t("data.status.created")}>{timestamp(operation.createdAt)}</TableCell>
                  <TableCell data-label={t("data.status.actions")}>
                    <div className={styles.rowActions}>
                      <OperationActionButton onAction={onAction} operation={operation} />
                      <Button variant="outline" aria-label={t("data.status.detailsAria", { key: operation.idempotencyKey })} onClick={(event) => onDetails(operation, event.currentTarget)} type="button">{t("data.status.details")}</Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
      )}
      <PageNavigation label={t("data.status.pages")} previousLabel={t("data.status.newer")} nextLabel={t("data.status.older")} previousDisabled={cursorDepth === 0} nextDisabled={nextCursor === null} onPrevious={onPrevious} onNext={onNext}>
        {t("data.status.page", { page: formatNumber(cursorDepth + 1) })}
      </PageNavigation>
    </section>
  );
}

function OperationState({ operation }: Readonly<{ operation: DataRefreshOperationalStatus }>) {
  const state = operationStateText(operation);
  const tone = operation.outcome === "degraded" ? "degraded" : operation.status;
  return <Badge variant={tone === "failed" ? "destructive" : tone === "succeeded" ? "default" : "secondary"} className="h-auto min-h-5 whitespace-normal text-left">{state}</Badge>;
}

export function OperatorDataStatusDrawer({
  onDismiss,
  onAction,
  operation,
}: Readonly<{
  onDismiss: () => void;
  onAction: (action: DataRefreshStatusAction, trigger: HTMLButtonElement) => void;
  operation: DataRefreshOperationalStatus;
}>) {
  const { t } = useTranslation("operator");
  const initialFocus = useRef<HTMLButtonElement | null>(null);
  return (
    <Sheet open onOpenChange={(open) => { if (!open) onDismiss(); }}>
      <SheetContent finalFocus={false} initialFocus={initialFocus} showCloseButton={false} side="right" className="w-full max-w-full overflow-y-auto sm:max-w-[540px]">
        <SheetHeader className="sticky top-0 z-10 flex-row items-center justify-between gap-4 border-b border-border bg-popover">
          <div>
            <p className={styles.eyebrow}>{kindText(operation.kind)}</p>
            <SheetTitle id="operator-data-operation-drawer-title" className="text-base leading-6 font-semibold">{t("data.status.detailsTitle")}</SheetTitle>
          </div>
          <Button variant="outline" aria-label={t("data.status.closeDetails")} onClick={onDismiss} ref={initialFocus} type="button">{t("data.status.close")}</Button>
        </SheetHeader>
        <div className={styles.telemetry}><FinancialRefreshTelemetry progress={operation.financialProgress} /></div>
        <dl className={styles.details}>
          <Detail label={t("data.status.state")} value={operationStateText(operation)} />
          <Detail label={t("data.status.target")} code value={operationTarget(operation)} />
          <Detail label={t("data.common.idempotencyKey")} code value={operation.idempotencyKey} />
          <Detail label={t("data.status.attempt")} value={formatNumber(operation.attemptCount)} />
          <Detail label={t("data.status.phase")} value={operation.phase === null ? t("data.status.notStarted") : phaseText(operation.phase)} />
          <Detail label={t("data.status.lastHeartbeat")} value={operation.lastHeartbeatAt ?? t("data.status.notStarted")} />
          <Detail label={t("data.status.created")} value={operation.createdAt} />
          <Detail label={t("data.status.started")} value={operation.startedAt ?? t("data.status.notStarted")} />
          <Detail label={t("data.status.finished")} value={operation.finishedAt ?? t("data.status.notFinished")} />
          <Detail label={t("data.status.queueWait")} value={durationText(operation.createdAt, operation.startedAt ?? operation.finishedAt)} />
          <Detail label={t("data.status.execution")} value={operation.startedAt === null ? t("data.status.notStarted") : durationText(operation.startedAt, operation.finishedAt)} />
          <Detail label={t("data.status.updated")} value={operation.updatedAt} />
          <Detail label={t("data.status.dataThrough")} value={operation.dataThroughSession ?? t("data.status.notPublished")} />
          <Detail label={t("data.status.lastRefresh")} value={operation.lastRefreshAt ?? t("data.status.notCompleted")} />
          <Detail label={t("data.status.financialComplete")} value={operation.financialCompleteThroughSession ?? t("data.status.notApplicable")} />
          <Detail label={t("data.status.changedCompanies")} value={countText(operation.matchedTriggerCount)} />
          <Detail label={t("data.status.checkedNoChange")} value={countText(operation.checkedNoStructuredChangeCount)} />
          <Detail label={t("data.status.acceptedInstruments")} value={countText(operation.acceptedInstrumentCount)} />
          <Detail label={t("data.status.failedInstruments")} value={countText(operation.failedInstrumentCount)} />
          <Detail label={t("data.status.pendingInstruments")} value={countText(operation.pendingInstrumentCount)} />
          <Detail label={t("data.status.disclosureGaps")} value={countText(operation.discoveryGapCount)} />
          <Detail label={t("data.status.outcome")} value={operation.outcome === null ? t("data.status.none") : outcomeText(operation.outcome)} />
          <Detail label={t("data.status.failureCode")} code value={operation.failureCode ?? t("data.status.none")} />
          <Detail label={t("data.status.previousFailure")} code value={operation.lastFailureCode ?? t("data.status.none")} />
        </dl>
        <SheetFooter className="flex-row justify-end"><OperationActionButton onAction={onAction} operation={operation} /></SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function OperationActionButton({
  onAction,
  operation,
}: Readonly<{
  onAction: (action: DataRefreshStatusAction, trigger: HTMLButtonElement) => void;
  operation: DataRefreshOperationalStatus;
}>) {
  const { t } = useTranslation("operator");
  if (operation.kind !== "dataset") return null;
  const action = operation.status === "accepted"
    ? "cancel"
    : operation.status === "failed" || operation.status === "cancelled"
      ? "retry"
      : null;
  if (action === null) return null;
  const label = t(action === "cancel" ? "data.status.cancel" : "data.status.retry");
  return (
    <Button
      variant={action === "cancel" ? "destructive" : "outline"}
      aria-label={t("data.status.operationAria", { action: label, key: operation.idempotencyKey })}
      onClick={(event) => onAction({ action, operation }, event.currentTarget)}
      type="button"
    >
      {label}
    </Button>
  );
}

function Detail({
  code = false,
  label,
  value,
}: Readonly<{ code?: boolean; label: string; value: string }>) {
  return <div><dt>{label}</dt><dd>{code ? <code>{value}</code> : value}</dd></div>;
}

export function datasetStatusNeedsPolling(data: DatasetOperationalStatus): boolean {
  return !data.worker.available || [...data.latestByKind, ...data.operations].some(
    (operation) => operation.status === "accepted" || operation.status === "running",
  );
}

function operationStateText(operation: DataRefreshOperationalStatus): string {
  if (operation.status === "accepted") return i18n.t("operator:data.status.acceptedQueued");
  if (operation.status === "running") {
    return i18n.t("operator:data.status.runningPhase", { phase: operation.phase === null ? i18n.t("operator:data.status.starting") : phaseText(operation.phase) });
  }
  if (operation.status === "cancelled") return i18n.t("operator:data.status.cancelled");
  if (operation.status === "failed") {
    if (operation.outcome === "business_rejected") return i18n.t("operator:data.status.failedBusiness");
    if (operation.outcome === "infrastructure_failed") return i18n.t("operator:data.status.failedInfrastructure");
    return i18n.t("operator:data.status.failed");
  }
  if (operation.outcome === "published") return i18n.t("operator:data.status.published");
  if (operation.outcome === "no_change") return i18n.t("operator:data.status.noChange");
  return i18n.t("operator:data.status.publishedDegraded");
}

function kindText(kind: DataRefreshKind): string {
  if (kind === "dataset") return i18n.t("operator:data.dataset.title");
  if (kind === "market") return i18n.t("operator:data.market.title");
  if (kind === "financial") return i18n.t("operator:data.financial.title");
  return i18n.t("operator:data.industry.title");
}

function operationTarget(operation: DataRefreshOperationalStatus): string {
  return operation.asOf ?? operation.observationThroughSession ?? i18n.t("operator:data.status.unavailableValue");
}

function phaseText(phase: string): string {
  const labels: Readonly<Record<string, string>> = {
    claim: i18n.t("operator:data.status.phases.claim"),
    current_head: i18n.t("operator:data.status.phases.current_head"),
    market: i18n.t("operator:data.status.phases.market"),
    validation: i18n.t("operator:data.status.phases.validation"),
    benchmark: i18n.t("operator:data.status.phases.benchmark"),
    materialization: i18n.t("operator:data.status.phases.materialization"),
    candidate_validation: i18n.t("operator:data.status.phases.candidate_validation"),
    publication: i18n.t("operator:data.status.phases.publication"),
    financial: i18n.t("operator:data.status.phases.financial"),
    industry: i18n.t("operator:data.status.phases.industry"),
  };
  return labels[phase] ?? phase;
}

function financialReadinessText(
  readiness: DatasetOperationalStatus["head"]["financialResearchReadiness"],
): string {
  if (readiness === "ready") return i18n.t("operator:data.status.financialReady");
  if (readiness === "ready_with_pending") return i18n.t("operator:data.status.financialPending");
  if (readiness === "ready_with_gaps") return i18n.t("operator:data.status.financialGaps");
  return i18n.t("operator:data.status.financialNotReady");
}

function outcomeText(outcome: NonNullable<DataRefreshOperationalStatus["outcome"]>): string {
  if (outcome === "published") return i18n.t("operator:data.status.published");
  if (outcome === "no_change") return i18n.t("operator:data.status.noChange");
  if (outcome === "degraded") return i18n.t("operator:data.status.publishedDegraded");
  if (outcome === "business_rejected") return i18n.t("operator:data.status.businessRejected");
  return i18n.t("operator:data.status.infrastructureFailed");
}

function timestamp(value: string | null): React.ReactNode {
  return value === null
    ? <span className="text-muted-foreground">{i18n.t("operator:data.status.notAvailable")}</span>
    : <time dateTime={value}>{value}</time>;
}

function countText(value: number | null): string {
  return value === null ? i18n.t("operator:data.status.notApplicable") : formatNumber(value);
}

function durationText(start: string, end: string | null): string {
  const seconds = Math.max(0, Math.floor(((end === null ? Date.now() : Date.parse(end)) - Date.parse(start)) / 1000));
  return seconds < 60 ? i18n.t("operator:data.telemetry.durationSeconds", { seconds: formatNumber(seconds) }) : i18n.t("operator:data.telemetry.durationMinutes", { minutes: formatNumber(Math.floor(seconds / 60)), seconds: formatNumber(seconds % 60) });
}
