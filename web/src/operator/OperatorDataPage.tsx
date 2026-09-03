import { useCallback, useEffect, useRef, useState } from "react";

import { OperatorConsoleNavigation } from "./OperatorConsoleNavigation";
import { OperatorDatasetStatus } from "./OperatorDatasetStatus";
import { OperatorFinancialRefreshPanel } from "./OperatorFinancialRefreshPanel";
import { OperatorIndustryRefreshPanel } from "./OperatorIndustryRefreshPanel";
import { OperatorMarketRefreshDialog } from "./OperatorMarketRefreshDialog";
import { OperatorPageNotFoundError } from "./operatorDirectoryClient";
import {
  loadMarketRefresh,
  isMarketRefreshIdempotencyKey,
  type MarketRefreshOperation,
  type MarketRefreshRequest,
  OperatorMutationError,
} from "./operatorMutationClient";

const pollIntervalMilliseconds = 5_000;

type MarketRefreshFieldErrors = Readonly<{
  asOf: string | null;
  idempotencyKey: string | null;
}>;

type TrackedMarketRefreshRequest = Readonly<{
  generation: number;
  request: MarketRefreshRequest;
}>;

type TrackedMarketRefreshOperation = Readonly<{
  generation: number;
  operation: MarketRefreshOperation;
}>;

const noFieldErrors: MarketRefreshFieldErrors = {
  asOf: null,
  idempotencyKey: null,
};

export function OperatorDataPage() {
  const [asOf, setAsOf] = useState("");
  const [idempotencyKey, setIdempotencyKey] = useState(() =>
    suggestMarketRefreshKey(new Date())
  );
  const [confirmation, setConfirmation] = useState<TrackedMarketRefreshRequest | null>(null);
  const [pendingSubmission, setPendingSubmission] = useState<TrackedMarketRefreshRequest | null>(null);
  const [operation, setOperation] = useState<TrackedMarketRefreshOperation | null>(null);
  const [pollError, setPollError] = useState(false);
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [fieldErrors, setFieldErrors] = useState(noFieldErrors);
  const [datasetStatusReloadGeneration, setDatasetStatusReloadGeneration] = useState(0);
  const asOfInput = useRef<HTMLInputElement | null>(null);
  const idempotencyKeyInput = useRef<HTMLInputElement | null>(null);
  const pendingFieldFocus = useRef<keyof MarketRefreshFieldErrors | null>(null);
  const activeOperationGeneration = useRef(0);
  const activeSubmissionGeneration = useRef(0);
  const pendingSubmissionRef = useRef<TrackedMarketRefreshRequest | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  pendingSubmissionRef.current = pendingSubmission;
  const showNotFound = useCallback(() => setNotFound(true), []);
  const notifyOperationAccepted = useCallback(
    () => setDatasetStatusReloadGeneration((current) => current + 1),
    [],
  );

  useEffect(() => {
    if (
      confirmation !== null
      || pendingSubmission !== null
      || pendingFieldFocus.current === null
    ) return;
    const target = pendingFieldFocus.current === "asOf"
      ? asOfInput.current
      : idempotencyKeyInput.current;
    if (target === null) return;
    pendingFieldFocus.current = null;
    target.focus();
  }, [confirmation, fieldErrors, pendingSubmission]);

  useEffect(() => {
    const trackedRequest = pendingSubmission !== null
      ? { ...pendingSubmission, source: "pending" as const }
      : (operation !== null && !isTerminal(operation.operation)
        ? {
            generation: operation.generation,
            request: {
              asOf: operation.operation.asOf,
              idempotencyKey: operation.operation.idempotencyKey,
            },
            source: "operation" as const,
          }
        : null);
    if (notFound || trackedRequest === null) return;
    let disposed = false;
    let timer: number | undefined;
    let controller: AbortController | null = null;

    const stop = (): void => {
      disposed = true;
      window.clearTimeout(timer);
      controller?.abort();
      document.removeEventListener("visibilitychange", visibilityChanged);
    };

    const schedule = (delay = pollIntervalMilliseconds): void => {
      if (disposed || document.visibilityState !== "visible") return;
      window.clearTimeout(timer);
      timer = window.setTimeout(() => void poll(), delay);
    };
    const poll = async (): Promise<void> => {
      if (disposed || document.visibilityState !== "visible") return;
      controller?.abort();
      controller = new AbortController();
      try {
        const next = await loadMarketRefresh(trackedRequest.request, controller.signal);
        if (disposed || !pollGenerationIsCurrent(trackedRequest)) return;
        setPollError(false);
        if (trackedRequest.source === "pending") {
          activeSubmissionGeneration.current += 1;
          setPendingSubmission(null);
          replaceOperation(next);
          notifyOperationAccepted();
          window.requestAnimationFrame(() => trigger.current?.focus());
        } else {
          setOperation({ generation: trackedRequest.generation, operation: next });
        }
        if (!isTerminal(next)) schedule();
      } catch (reason) {
        if (disposed || (reason instanceof DOMException && reason.name === "AbortError")) {
          return;
        }
        if (!pollGenerationIsCurrent(trackedRequest)) return;
        if (reason instanceof OperatorPageNotFoundError) {
          if (trackedRequest.source === "pending") {
            setPollError(true);
            schedule();
            return;
          }
          stop();
          activeOperationGeneration.current += 1;
          setOperation(null);
          setNotFound(true);
          return;
        }
        if (
          trackedRequest.source === "pending"
          && reason instanceof OperatorMutationError
          && (reason.code === "conflict" || reason.code === "request-invalid")
        ) {
          showRejectedRequest(trackedRequest, reason.code);
          return;
        }
        setPollError(true);
        schedule();
      }
    };
    const visibilityChanged = (): void => {
      if (document.visibilityState === "visible") {
        schedule(0);
      } else {
        window.clearTimeout(timer);
        controller?.abort();
      }
    };

    document.addEventListener("visibilitychange", visibilityChanged);
    schedule();
    return stop;
  }, [notFound, notifyOperationAccepted, operation, pendingSubmission]);

  function pollGenerationIsCurrent(
    tracked: TrackedMarketRefreshRequest & Readonly<{ source: "operation" | "pending" }>,
  ): boolean {
    return marketRefreshPollGenerationIsCurrent(
      tracked.source,
      tracked.generation,
      activeSubmissionGeneration.current,
      activeOperationGeneration.current,
    );
  }

  if (notFound) {
    return (
      <section aria-label="Not found" className="page-section state-section">
        <h1>Not found</h1>
        <p>The requested resource is not available.</p>
      </section>
    );
  }

  function dismissConfirmation(generation: number): void {
    if (activeSubmissionGeneration.current !== generation) return;
    activeSubmissionGeneration.current += 1;
    setConfirmation(null);
    window.requestAnimationFrame(() => trigger.current?.focus());
  }

  function replaceOperation(next: MarketRefreshOperation): void {
    const generation = activeOperationGeneration.current + 1;
    activeOperationGeneration.current = generation;
    setOperation({ generation, operation: next });
  }

  function reviewRefresh(): void {
    const errors = marketRefreshFieldErrors(asOf, idempotencyKey);
    setFieldErrors(errors);
    const invalid = errors.asOf !== null
      ? "asOf"
      : errors.idempotencyKey !== null
        ? "idempotencyKey"
        : null;
    if (invalid !== null) {
      pendingFieldFocus.current = invalid;
      return;
    }
    setPollError(false);
    setSubmissionError(null);
    beginConfirmation({ asOf, idempotencyKey });
  }

  function beginConfirmation(request: MarketRefreshRequest): void {
    const generation = activeSubmissionGeneration.current + 1;
    activeSubmissionGeneration.current = generation;
    setConfirmation({ generation, request });
  }

  function showRejectedRequest(
    tracked: TrackedMarketRefreshRequest,
    code: "conflict" | "request-invalid",
  ): void {
    if (activeSubmissionGeneration.current !== tracked.generation) return;
    activeSubmissionGeneration.current += 1;
    setConfirmation(null);
    setPendingSubmission(null);
    setSubmissionError(null);
    if (
      code === "conflict"
      || !isMarketRefreshIdempotencyKey(tracked.request.idempotencyKey)
    ) {
      pendingFieldFocus.current = "idempotencyKey";
      setFieldErrors({
        asOf: null,
        idempotencyKey: code === "conflict"
          ? "This key is already bound to a different Market target."
          : marketRefreshKeyError,
      });
      return;
    }
    pendingFieldFocus.current = "asOf";
    setFieldErrors({
      asOf: "Enter the same explicit timezone-aware ISO timestamp accepted by the CLI.",
      idempotencyKey: null,
    });
  }

  function reconcileSubmission(tracked: TrackedMarketRefreshRequest): void {
    if (activeSubmissionGeneration.current !== tracked.generation) return;
    setConfirmation(null);
    activeOperationGeneration.current += 1;
    setOperation(null);
    setPollError(false);
    setSubmissionError(null);
    setPendingSubmission(tracked);
    window.requestAnimationFrame(() => trigger.current?.focus());
  }

  function failUncertainSubmission(tracked: TrackedMarketRefreshRequest): void {
    if (
      activeSubmissionGeneration.current !== tracked.generation
      || pendingSubmissionRef.current?.generation !== tracked.generation
    ) return;
    setPollError(true);
  }

  return (
    <>
      <section aria-label="Operator Data" className="page-section operator-page">
        <header className="page-hero">
          <div>
            <h1>Data operations</h1>
          </div>
        </header>

        <OperatorConsoleNavigation current="data" />

        <OperatorDatasetStatus
          onAccessNotFound={showNotFound}
          reloadGeneration={datasetStatusReloadGeneration}
        />

        <section aria-labelledby="operator-market-refresh-heading" className="operator-section">
          <header className="operator-section-header">
            <div>
              <h2 id="operator-market-refresh-heading">Market Refresh</h2>
            </div>
          </header>
          <form
            className="operator-refresh-form"
            onSubmit={(event) => {
              event.preventDefault();
              reviewRefresh();
            }}
          >
            <label>
              <span>As-of</span>
              <input
                aria-describedby={fieldErrors.asOf === null
                  ? "operator-market-as-of-help"
                  : "operator-market-as-of-help operator-market-as-of-error"}
                aria-invalid={fieldErrors.asOf === null ? undefined : true}
                autoComplete="off"
                disabled={confirmation !== null || pendingSubmission !== null}
                maxLength={128}
                onChange={(event) => {
                  setAsOf(event.target.value);
                  setFieldErrors((current) => ({ ...current, asOf: null }));
                }}
                placeholder="2026-08-11T18:00:00+08:00"
                required
                ref={asOfInput}
                spellCheck={false}
                type="text"
                value={asOf}
              />
              <small id="operator-market-as-of-help">
                Timezone-aware ISO timestamp. No target is selected for you.
              </small>
              {fieldErrors.asOf === null ? null : (
                <small className="operator-field-error" id="operator-market-as-of-error" role="alert">
                  {fieldErrors.asOf}
                </small>
              )}
            </label>
            <label>
              <span>Idempotency key</span>
              <input
                aria-describedby={fieldErrors.idempotencyKey === null
                  ? "operator-market-key-help"
                  : "operator-market-key-help operator-market-key-error"}
                aria-invalid={fieldErrors.idempotencyKey === null ? undefined : true}
                autoComplete="off"
                disabled={confirmation !== null || pendingSubmission !== null}
                onChange={(event) => {
                  setIdempotencyKey(event.target.value);
                  setFieldErrors((current) => ({ ...current, idempotencyKey: null }));
                }}
                required
                ref={idempotencyKeyInput}
                spellCheck={false}
                type="text"
                value={idempotencyKey}
              />
              <small id="operator-market-key-help">
                The suggestion is editable; keep it to safely replay the same request (up to 512 characters).
              </small>
              {fieldErrors.idempotencyKey === null ? null : (
                <small className="operator-field-error" id="operator-market-key-error" role="alert">
                  {fieldErrors.idempotencyKey}
                </small>
              )}
            </label>
            {submissionError === null ? null : (
              <p className="inline-status inline-status-error operator-refresh-form-error" role="alert">
                {submissionError}
              </p>
            )}
            <footer>
              <button
                className="button-primary"
                disabled={confirmation !== null || pendingSubmission !== null}
                ref={trigger}
                type="submit"
              >
                Review Refresh
              </button>
            </footer>
          </form>
        </section>

        {pendingSubmission === null ? null : (
          <MarketRefreshReconciliation
            onRetry={() => {
              setPendingSubmission(null);
              setPollError(false);
              setSubmissionError(null);
              beginConfirmation(pendingSubmission.request);
            }}
            onStop={() => {
              if (activeSubmissionGeneration.current === pendingSubmission.generation) {
                activeSubmissionGeneration.current += 1;
              }
              setPendingSubmission(null);
              setPollError(false);
              setSubmissionError(
                "Automatic receipt checks stopped. Retry with the same idempotency key to reconcile any accepted work.",
              );
              window.requestAnimationFrame(() => trigger.current?.focus());
            }}
            pollError={pollError}
            request={pendingSubmission.request}
          />
        )}
        {operation === null ? null : (
          <MarketRefreshReceipt operation={operation.operation} pollError={pollError} />
        )}

        <OperatorFinancialRefreshPanel
          onAccessNotFound={showNotFound}
          onOperationAccepted={notifyOperationAccepted}
        />
        <OperatorIndustryRefreshPanel
          onAccessNotFound={showNotFound}
          onOperationAccepted={notifyOperationAccepted}
        />
      </section>
      {confirmation === null ? null : (
        <OperatorMarketRefreshDialog
          onDismiss={() => dismissConfirmation(confirmation.generation)}
          onRequestRejected={(code) => showRejectedRequest(confirmation, code)}
          onSubmissionFailed={() => failUncertainSubmission(confirmation)}
          onSubmissionUncertain={() => reconcileSubmission(confirmation)}
          onSucceeded={(accepted) => {
            if (activeSubmissionGeneration.current !== confirmation.generation) return;
            activeSubmissionGeneration.current += 1;
            replaceOperation(accepted);
            notifyOperationAccepted();
            setConfirmation(null);
            setPendingSubmission(null);
            setPollError(false);
            setSubmissionError(null);
            window.requestAnimationFrame(() => trigger.current?.focus());
          }}
          request={confirmation.request}
        />
      )}
    </>
  );
}

function MarketRefreshReconciliation({
  onRetry,
  onStop,
  pollError,
  request,
}: Readonly<{
  onRetry: () => void;
  onStop: () => void;
  pollError: boolean;
  request: MarketRefreshRequest;
}>) {
  return (
    <section
      aria-labelledby="operator-market-refresh-reconciliation"
      className="operator-refresh-receipt operator-refresh-running"
    >
      <header aria-atomic="true" aria-live="polite" role="status">
        <div>
          <p className="eyebrow">Latest submitted operation</p>
          <h2 id="operator-market-refresh-reconciliation">Confirming submission</h2>
        </div>
        <span className="operator-state">Checking</span>
      </header>
      <p>
        Core submission had already started, but its response could not be confirmed.
        Checking the exact idempotency key until its durable receipt is available.
      </p>
      <dl>
        <div><dt>Idempotency key</dt><dd><code>{request.idempotencyKey}</code></dd></div>
        <div><dt>Requested as-of</dt><dd><time>{request.asOf}</time></dd></div>
      </dl>
      {pollError ? (
        <p className="inline-status inline-status-error" role="alert">
          The receipt is not available yet. Retrying while this page is visible.
        </p>
      ) : null}
      <footer className="operator-confirmation-actions">
        <button onClick={onStop} type="button">Stop checking</button>
        <button className="button-primary" onClick={onRetry} type="button">
          Retry exact request
        </button>
      </footer>
    </section>
  );
}

export function MarketRefreshReceipt({
  operation,
  pollError,
}: Readonly<{
  operation: MarketRefreshOperation;
  pollError: boolean;
}>) {
  const presentation = refreshPresentation(operation);
  return (
    <section
      aria-labelledby="operator-market-refresh-status"
      className={`operator-refresh-receipt operator-refresh-${presentation.tone}`}
    >
      <header aria-atomic="true" aria-live="polite" role="status">
        <div>
          <p className="eyebrow">Latest submitted operation</p>
          <h2 id="operator-market-refresh-status">{presentation.title}</h2>
        </div>
        <span className="operator-state">{presentation.label}</span>
      </header>
      <p>{presentation.description}</p>
      <dl>
        <div><dt>Idempotency key</dt><dd><code>{operation.idempotencyKey}</code></dd></div>
        <div><dt>As-of</dt><dd><time>{operation.asOf}</time></dd></div>
        <div><dt>Attempts</dt><dd>{operation.attemptCount}</dd></div>
        <div>
          <dt>Data through</dt>
          <dd>{operation.dataThroughSession ?? "Not published"}</dd>
        </div>
        <div>
          <dt>Last refresh</dt>
          <dd>{operation.lastRefreshAt ?? "Not completed"}</dd>
        </div>
        <div>
          <dt>Failure</dt>
          <dd><code>{operation.failureCode ?? operation.lastFailureCode ?? "None"}</code></dd>
        </div>
      </dl>
      {pollError ? (
        <p className="inline-status inline-status-error" role="alert">
          Status is temporarily unavailable. Showing the last known state and retrying while visible.
        </p>
      ) : null}
    </section>
  );
}

function refreshPresentation(operation: MarketRefreshOperation): Readonly<{
  description: string;
  label: string;
  title: string;
  tone: string;
}> {
  if (operation.status === "accepted") {
    return {
      description: "Accepted is queued, not published. The Data Operator Worker will claim it in FIFO order.",
      label: "Accepted",
      title: "Refresh accepted",
      tone: "pending",
    };
  }
  if (operation.status === "running") {
    return {
      description: "The Data Operator Worker is collecting and validating the requested Market target.",
      label: "Running",
      title: "Refresh running",
      tone: "running",
    };
  }
  if (operation.status === "failed") {
    return {
      description: "The operation reached a terminal failure without publishing a new Dataset.",
      label: "Failed",
      title: "Refresh failed",
      tone: "failed",
    };
  }
  if (operation.outcome === "published") {
    return {
      description: "Validation completed and a new immutable Dataset Generation was published.",
      label: "Published",
      title: "Dataset published",
      tone: "published",
    };
  }
  return {
    description: "Validation completed successfully and the canonical Dataset did not change.",
    label: "No change",
    title: "Refresh completed",
    tone: "unchanged",
  };
}

function isTerminal(operation: MarketRefreshOperation): boolean {
  return operation.status === "succeeded" || operation.status === "failed";
}

export function suggestMarketRefreshKey(now: Date): string {
  return `market-${now.toISOString().replace(/\.\d{3}Z$/, "Z").replaceAll("-", "").replaceAll(":", "")}`;
}

export function marketRefreshPollGenerationIsCurrent(
  source: "operation" | "pending",
  trackedGeneration: number,
  activeSubmissionGeneration: number,
  activeOperationGeneration: number,
): boolean {
  return source === "pending"
    ? trackedGeneration === activeSubmissionGeneration
    : trackedGeneration === activeOperationGeneration;
}

const marketRefreshKeyError = "Use 1–512 characters with no boundary whitespace, NUL, or unpaired surrogate.";

function marketRefreshFieldErrors(
  asOf: string,
  idempotencyKey: string,
): MarketRefreshFieldErrors {
  const asOfCharacters = Array.from(asOf);
  return {
    asOf: asOfCharacters.length === 0
      || asOfCharacters.length > 128
      || asOf !== asOf.trim()
      ? "Enter an explicit timezone-aware ISO timestamp of at most 128 characters."
      : null,
    idempotencyKey: isMarketRefreshIdempotencyKey(idempotencyKey)
      ? null
      : marketRefreshKeyError,
  };
}
