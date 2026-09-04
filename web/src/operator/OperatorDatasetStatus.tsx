import { type ReactNode, useEffect, useRef, useState } from "react";

import { STRATEGY_BENCHMARK_DISPLAY_NAME } from "../benchmark";

import { OperatorPageNotFoundError } from "./operatorDirectoryClient";
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
import { containDialogKeyboardFocus } from "./operatorDialog";

const pollIntervalMilliseconds = 5_000;
const refreshKinds = ["market", "financial", "industry"] as const;

export function OperatorDatasetStatus({
  onAccessNotFound,
  reloadGeneration,
}: Readonly<{
  onAccessNotFound: () => void;
  reloadGeneration: number;
}>) {
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
          onSucceeded={() => {
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
  return (
    <section
      aria-busy={loading || undefined}
      aria-labelledby="operator-dataset-status-heading"
      className="operator-section operator-dataset-status"
    >
      <header className="operator-section-header operator-dataset-status-header">
        <div>
          <h2 id="operator-dataset-status-heading">Current research Dataset</h2>
        </div>
        <button onClick={onReload} type="button">Reload</button>
      </header>

      {data === null ? (
        <div className={error ? "operator-load-state operator-load-error" : "operator-load-state"}>
          <p role={error ? "alert" : "status"}>
            {error
              ? "Dataset status is temporarily unavailable."
              : "Loading Dataset status…"}
          </p>
          {error ? <button onClick={onReload} type="button">Try again</button> : null}
        </div>
      ) : (
        <>
          <DatasetHeadSummary data={data} />
          <WorkerAvailability data={data} />
          {error ? (
            <p className="inline-status inline-status-error" role="alert">
              Status refresh failed. Showing the last safe response; Reload or automatic
              polling will try again while this page is visible.
            </p>
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
  const head = data.head;
  return (
    <div className="operator-dataset-head">
      <dl>
        <div>
          <dt>Data identity</dt>
          <dd><code>{head.dataIdentity ?? "No Dataset Head"}</code></dd>
        </div>
        <div>
          <dt>Data through</dt>
          <dd>{head.dataThroughSession ?? "Unavailable"}</dd>
        </div>
        <div>
          <dt>Prepared</dt>
          <dd>{datasetTimestamp(head.preparedAt) ?? "Not available"}</dd>
        </div>
      </dl>
      <div aria-label="Current data coverage" role="group">
        <DatasetFamilyStatus
          name="Market"
          status={<ReadinessStatus label="Market" ready={head.marketResearchReadiness} />}
        >
          <DatasetFact label="Coverage start" value={head.marketCoverageStart} />
          <DatasetFact label="Data through" value={head.dataThroughSession} />
          <DatasetFact label="Last refresh" value={datasetTimestamp(head.marketLastRefreshAt)} />
        </DatasetFamilyStatus>
        <DatasetFamilyStatus
          name={`${STRATEGY_BENCHMARK_DISPLAY_NAME} Benchmark`}
          note="Updates with Market Refresh"
          status={<ReadinessStatus label="Benchmark" ready={head.benchmarkResearchReadiness} />}
        >
          <DatasetFact label="Coverage start" value={head.benchmarkCoverageStart} />
          <DatasetFact label="Coverage end" value={head.benchmarkCoverageEnd} />
          <DatasetFact label="Last publication" value={datasetTimestamp(head.benchmarkLastPublishedAt)} />
        </DatasetFamilyStatus>
        <DatasetFamilyStatus
          name="Financial"
          status={(
            <span className={`operator-state ${head.financialResearchReadiness === "ready"
              ? "operator-state-active"
              : head.financialResearchReadiness === "not_ready" ? "" : "operator-state-warning"}`}
            >
              {financialReadinessText(head.financialResearchReadiness)}
            </span>
          )}
        >
          <DatasetFact label="Coverage start" value={head.financialCoverageStart} />
          <DatasetFact label="Discovery attempted through" value={head.financialAttemptedThroughSession} />
          <DatasetFact label="Discovery complete through" value={head.financialCompleteThroughSession} />
          <DatasetFact label="Pending instruments" value={head.financialPendingInstrumentCount} />
          <DatasetFact label="Discovery gaps" value={head.financialDiscoveryGapCount} />
          <DatasetFact label="Earliest unresolved" value={head.financialEarliestUnresolvedDate} />
          <DatasetFact label="Last refresh" value={datasetTimestamp(head.financialLastRefreshAt)} />
        </DatasetFamilyStatus>
        <DatasetFamilyStatus
          name="Industry"
          status={<ReadinessStatus label="Industry" ready={head.industryResearchReadiness} />}
        >
          <DatasetFact label="Coverage start" value={head.industryCoverageStart} />
          <DatasetFact label="Observed through" value={head.industryObservationThroughSession} />
          <DatasetFact label="Last refresh" value={datasetTimestamp(head.industryLastRefreshAt)} />
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
  return (
    <section aria-label={`${name} data status`} className="operator-data-family">
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
  return <div><dt>{label}</dt><dd>{value ?? <span className="operator-muted">Not available</span>}</dd></div>;
}

function datasetTimestamp(value: string | null): ReactNode {
  return value === null ? null : (
    <time dateTime={value} title={value}>
      {new Date(value).toISOString().slice(0, 19).replace("T", " ")} UTC
    </time>
  );
}

function WorkerAvailability({ data }: Readonly<{ data: DatasetOperationalStatus }>) {
  const worker = data.worker;
  const visibleOperations = [...data.latestByKind, ...data.operations];
  const accepted = visibleOperations.some((operation) => operation.status === "accepted");
  const running = visibleOperations.some((operation) => operation.status === "running");
  return (
    <div
      className={`inline-status operator-worker-status${worker.available ? "" : " inline-status-error"}`}
      role={worker.available ? "status" : "alert"}
    >
      <strong>
        Data Operator Worker {worker.available ? "available" : "unavailable"}
      </strong>
      {worker.available ? null : (
        <span>
          {accepted
            ? "Accepted work is durably queued but cannot start until the Worker recovers."
            : running
              ? "Running work will be recovered from its durable claim when the Worker recovers."
              : "New work can be accepted durably but cannot start until the Worker recovers."}
        </span>
      )}
      <small>Last Worker heartbeat: {timestamp(worker.lastHeartbeatAt)}</small>
    </div>
  );
}

function ReadinessStatus({ label, ready }: Readonly<{ label: string; ready: boolean }>) {
  return (
    <span className={`operator-state ${ready ? "operator-state-active" : ""}`}>
      {label} {ready ? "ready" : "not ready"}
    </span>
  );
}

function LatestRefreshTable({
  operations,
}: Readonly<{ operations: readonly DataRefreshOperationalStatus[] }>) {
  return (
    <section aria-labelledby="operator-latest-refreshes-heading" className="operator-dataset-subsection">
      <header>
        <h3 id="operator-latest-refreshes-heading">Latest by Refresh kind</h3>
      </header>
      <div className="operator-table-scroll">
        <table
          aria-label="Latest Data Refresh operations"
          className="operator-table operator-latest-refresh-table"
        >
          <thead><tr><th>Kind</th><th>State</th><th>Target</th><th>Updated</th></tr></thead>
          <tbody>
            {refreshKinds.map((kind) => {
              const operation = operations.find((item) => item.kind === kind);
              return (
                <tr key={kind}>
                  <th data-label="Kind" scope="row">{kindText(kind)}</th>
                  <td data-label="State">
                    {operation === undefined
                      ? <span className="operator-muted">No operation</span>
                      : <OperationState operation={operation} />}
                  </td>
                  <td data-label="Target">
                    {operation === undefined ? "—" : operationTarget(operation)}
                  </td>
                  <td data-label="Updated">
                    {operation === undefined ? "—" : timestamp(operation.updatedAt)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
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
  return (
    <section aria-labelledby="operator-operation-history-heading" className="operator-dataset-subsection">
      <header>
        <h3 id="operator-operation-history-heading">Operation history</h3>
      </header>
      {operations.length === 0 ? (
        <p className="operator-empty">
          {cursorDepth === 0
            ? "No Data Refresh operations have been accepted."
            : "This older page no longer contains retained receipts. Return to a newer page."}
        </p>
      ) : (
        <div className="operator-table-scroll">
          <table
            aria-label="Data Refresh operation history"
            className="operator-table operator-data-operation-table"
          >
            <thead>
              <tr>
                <th>Operation</th><th>Kind</th><th>State</th><th>Target</th>
                <th>Attempt / phase</th><th>Heartbeat</th><th>Created</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {operations.map((operation) => (
                <tr key={operation.idempotencyKey}>
                  <th data-label="Operation" scope="row"><code>{operation.idempotencyKey}</code></th>
                  <td data-label="Kind">{kindText(operation.kind)}</td>
                  <td data-label="State"><OperationState operation={operation} /></td>
                  <td data-label="Target"><code>{operationTarget(operation)}</code></td>
                  <td data-label="Attempt / phase">
                    <span className="operator-operation-phase">
                      <strong>{operation.attemptCount}</strong>
                      <small>{operation.phase === null ? "Not started" : phaseText(operation.phase)}</small>
                    </span>
                  </td>
                  <td data-label="Heartbeat">{timestamp(operation.lastHeartbeatAt)}</td>
                  <td data-label="Created">{timestamp(operation.createdAt)}</td>
                  <td data-label="Actions">
                    <div className="operator-row-actions">
                      <OperationActionButton onAction={onAction} operation={operation} />
                      <button
                        aria-label={`View details for ${operation.idempotencyKey}`}
                        className="operator-row-action"
                        onClick={(event) => onDetails(operation, event.currentTarget)}
                        type="button"
                      >
                        Details
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <nav aria-label="Data Refresh operation pages" className="operator-pagination">
        <button disabled={cursorDepth === 0} onClick={onPrevious} type="button">Newer</button>
        <span>Page {cursorDepth + 1}</span>
        <button disabled={nextCursor === null} onClick={onNext} type="button">Older</button>
      </nav>
    </section>
  );
}

function OperationState({ operation }: Readonly<{ operation: DataRefreshOperationalStatus }>) {
  const state = operationStateText(operation);
  return <span className={`operator-state operator-operation-state-${operation.status}`}>{state}</span>;
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
  const dialog = useRef<HTMLDialogElement | null>(null);
  useEffect(() => {
    const element = dialog.current;
    if (element === null) return;
    element.showModal();
    return () => {
      if (element.open) element.close();
    };
  }, []);
  return (
    <dialog
      aria-labelledby="operator-data-operation-drawer-title"
      className="operator-data-operation-drawer"
      onCancel={(event) => {
        event.preventDefault();
        onDismiss();
      }}
      onKeyDown={(event) => containDialogKeyboardFocus(event, dialog.current)}
      ref={dialog}
    >
      <article>
        <header>
          <div>
            <p className="eyebrow">{kindText(operation.kind)}</p>
            <h2 id="operator-data-operation-drawer-title">Operation details</h2>
          </div>
          <button aria-label="Close operation details" onClick={onDismiss} type="button">Close</button>
        </header>
        <dl className="operator-operation-details">
          <Detail label="State" value={operationStateText(operation)} />
          <Detail label="Target" code value={operationTarget(operation)} />
          <Detail label="Idempotency key" code value={operation.idempotencyKey} />
          <Detail label="Attempt" value={String(operation.attemptCount)} />
          <Detail label="Phase" value={operation.phase === null ? "Not started" : phaseText(operation.phase)} />
          <Detail label="Last heartbeat" value={operation.lastHeartbeatAt ?? "Not started"} />
          <Detail label="Created" value={operation.createdAt} />
          <Detail label="Started" value={operation.startedAt ?? "Not started"} />
          <Detail label="Finished" value={operation.finishedAt ?? "Not finished"} />
          <Detail label="Updated" value={operation.updatedAt} />
          <Detail label="Data through" value={operation.dataThroughSession ?? "Not published"} />
          <Detail label="Last refresh" value={operation.lastRefreshAt ?? "Not completed"} />
          <Detail label="Financial complete through" value={operation.financialCompleteThroughSession ?? "Not applicable"} />
          <Detail label="Matched triggers" value={countText(operation.matchedTriggerCount)} />
          <Detail label="Checked without structured change" value={countText(operation.checkedNoStructuredChangeCount)} />
          <Detail label="Accepted instruments" value={countText(operation.acceptedInstrumentCount)} />
          <Detail label="Failed instruments" value={countText(operation.failedInstrumentCount)} />
          <Detail label="Pending instruments" value={countText(operation.pendingInstrumentCount)} />
          <Detail label="Discovery gaps" value={countText(operation.discoveryGapCount)} />
          <Detail label="Outcome" value={operation.outcome === null ? "None" : outcomeText(operation.outcome)} />
          <Detail label="Failure code" code value={operation.failureCode ?? "None"} />
          <Detail label="Previous attempt failure" code value={operation.lastFailureCode ?? "None"} />
        </dl>
        <footer className="operator-operation-drawer-actions">
          <OperationActionButton onAction={onAction} operation={operation} />
        </footer>
      </article>
    </dialog>
  );
}

function OperationActionButton({
  onAction,
  operation,
}: Readonly<{
  onAction: (action: DataRefreshStatusAction, trigger: HTMLButtonElement) => void;
  operation: DataRefreshOperationalStatus;
}>) {
  const action = operation.status === "accepted"
    ? "cancel"
    : operation.status === "failed" || operation.status === "cancelled"
      ? "retry"
      : null;
  if (action === null) return null;
  const label = action === "cancel" ? "Cancel" : "Retry";
  return (
    <button
      aria-label={`${label} operation ${operation.idempotencyKey}`}
      className={`operator-row-action${action === "cancel" ? " operator-row-action-danger" : ""}`}
      onClick={(event) => onAction({ action, operation }, event.currentTarget)}
      type="button"
    >
      {label}
    </button>
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
  return [...data.latestByKind, ...data.operations].some(
    (operation) => operation.status === "accepted" || operation.status === "running",
  );
}

function operationStateText(operation: DataRefreshOperationalStatus): string {
  if (operation.status === "accepted") return "Accepted · queued";
  if (operation.status === "running") {
    return `Running · ${operation.phase === null ? "Starting" : phaseText(operation.phase)}`;
  }
  if (operation.status === "cancelled") return "Cancelled";
  if (operation.status === "failed") {
    if (operation.outcome === "business_rejected") return "Failed · business rejected";
    if (operation.outcome === "infrastructure_failed") return "Failed · infrastructure";
    return "Failed";
  }
  if (operation.outcome === "published") return "Published";
  if (operation.outcome === "no_change") return "No change";
  return "Degraded success";
}

function kindText(kind: DataRefreshKind): string {
  if (kind === "market") return "Market Refresh";
  if (kind === "financial") return "Financial Refresh";
  return "Industry Refresh";
}

function operationTarget(operation: DataRefreshOperationalStatus): string {
  return operation.asOf ?? operation.observationThroughSession ?? "Unavailable";
}

function phaseText(phase: string): string {
  const labels: Readonly<Record<string, string>> = {
    claim: "Claim",
    current_head: "Current Head",
    market: "Market collection",
    validation: "Validation",
    benchmark: "Benchmark",
    materialization: "Materialization",
    candidate_validation: "Candidate validation",
    publication: "Publication",
    financial: "Financial pipeline",
    industry: "Industry pipeline",
  };
  return labels[phase] ?? phase;
}

function financialReadinessText(
  readiness: DatasetOperationalStatus["head"]["financialResearchReadiness"],
): string {
  if (readiness === "ready") return "Financial ready";
  if (readiness === "ready_with_pending") return "Financial ready with pending";
  if (readiness === "ready_with_gaps") return "Financial ready with gaps";
  return "Financial not ready";
}

function outcomeText(outcome: NonNullable<DataRefreshOperationalStatus["outcome"]>): string {
  if (outcome === "published") return "Published";
  if (outcome === "no_change") return "No change";
  if (outcome === "degraded") return "Degraded success";
  if (outcome === "business_rejected") return "Business rejected";
  return "Infrastructure failed";
}

function timestamp(value: string | null): React.ReactNode {
  return value === null
    ? <span className="operator-muted">Not available</span>
    : <time dateTime={value}>{value}</time>;
}

function countText(value: number | null): string {
  return value === null ? "Not applicable" : String(value);
}
