import { useEffect, useRef, useState } from "react";

import { OperatorPageNotFoundError } from "./operatorDirectoryClient";
import { FinancialRefreshTelemetry } from "./FinancialRefreshTelemetry";
import { containDialogKeyboardFocus } from "./operatorDialog";
import {
  confirmFinancialRefreshProof,
  type FinancialRefreshOperation,
  type FinancialRefreshRequest,
  isIsoResearchSession,
  isMarketRefreshIdempotencyKey,
  loadFinancialRefresh,
  OperatorMutationError,
  submitFinancialRefresh,
} from "./operatorMutationClient";

const pollIntervalMilliseconds = 5_000;

type TrackedRequest = Readonly<{ generation: number; request: FinancialRefreshRequest }>;
type TrackedOperation = Readonly<{ generation: number; operation: FinancialRefreshOperation }>;

export function OperatorFinancialRefreshPanel({
  onAccessNotFound,
  onOperationAccepted = ignoreAcceptedOperation,
}: Readonly<{
  onAccessNotFound: () => void;
  onOperationAccepted?: () => void;
}>) {
  const [target, setTarget] = useState("");
  const [confirmation, setConfirmation] = useState<TrackedRequest | null>(null);
  const [pending, setPending] = useState<TrackedRequest | null>(null);
  const [operation, setOperation] = useState<TrackedOperation | null>(null);
  const [pollError, setPollError] = useState(false);
  const [targetError, setTargetError] = useState<string | null>(null);
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const targetInput = useRef<HTMLInputElement | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const submissionGeneration = useRef(0);
  const operationGeneration = useRef(0);
  const focusAfterCommit = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (confirmation !== null || pending !== null) return;
    // A frame may run before React removes disabled or closes the dialog.
    focusAfterCommit.current?.focus();
    focusAfterCommit.current = null;
  }, [confirmation, pending]);

  useEffect(() => {
    const tracked = pending !== null
      ? { ...pending, source: "pending" as const }
      : operation !== null && !financialRefreshIsTerminal(operation.operation)
        ? {
            generation: operation.generation,
            request: {
              idempotencyKey: operation.operation.idempotencyKey,
              observationThroughSession: operation.operation.observationThroughSession,
            },
            source: "operation" as const,
          }
        : null;
    if (tracked === null) return;
    let disposed = false;
    let timer: number | undefined;
    let controller: AbortController | null = null;

    const stop = (): void => {
      disposed = true;
      window.clearTimeout(timer);
      controller?.abort();
      document.removeEventListener("visibilitychange", visibilityChanged);
    };
    const current = (): boolean => tracked.source === "pending"
      ? tracked.generation === submissionGeneration.current
      : tracked.generation === operationGeneration.current;
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
        const next = await loadFinancialRefresh(tracked.request, controller.signal);
        if (disposed || !current()) return;
        setPollError(false);
        if (tracked.source === "pending") {
          submissionGeneration.current += 1;
          setPending(null);
          replaceOperation(next);
          onOperationAccepted();
          focusAfterCommit.current = trigger.current;
        } else {
          setOperation({ generation: tracked.generation, operation: next });
        }
        if (!financialRefreshIsTerminal(next)) schedule();
      } catch (reason) {
        if (disposed || (reason instanceof DOMException && reason.name === "AbortError")) {
          return;
        }
        if (!current()) return;
        if (reason instanceof OperatorPageNotFoundError) {
          if (tracked.source === "pending") {
            setPollError(true);
            schedule();
            return;
          }
          stop();
          operationGeneration.current += 1;
          setOperation(null);
          onAccessNotFound();
          return;
        }
        if (
          tracked.source === "pending"
          && reason instanceof OperatorMutationError
          && (reason.code === "conflict" || reason.code === "request-invalid")
        ) {
          rejectRequest(tracked, reason.code);
          return;
        }
        setPollError(true);
        schedule();
      }
    };
    const visibilityChanged = (): void => {
      if (document.visibilityState === "visible") schedule(0);
      else {
        window.clearTimeout(timer);
        controller?.abort();
      }
    };

    document.addEventListener("visibilitychange", visibilityChanged);
    schedule();
    return stop;
  }, [onAccessNotFound, onOperationAccepted, operation, pending]);

  function replaceOperation(next: FinancialRefreshOperation): void {
    const generation = operationGeneration.current + 1;
    operationGeneration.current = generation;
    setOperation({ generation, operation: next });
  }

  function review(): void {
    if (confirmation !== null || pending !== null) return;
    const idempotencyKey = suggestFinancialRefreshKey(new Date());
    const nextTargetError = isIsoResearchSession(target)
      ? null
      : "Choose a valid Research Session date.";
    setTargetError(nextTargetError);
    if (nextTargetError !== null) {
      window.requestAnimationFrame(() => targetInput.current?.focus());
      return;
    }
    setPollError(false);
    setSubmissionError(null);
    beginConfirmation({ idempotencyKey, observationThroughSession: target });
  }

  function beginConfirmation(request: FinancialRefreshRequest): void {
    const generation = submissionGeneration.current + 1;
    submissionGeneration.current = generation;
    setConfirmation({ generation, request });
  }

  function rejectRequest(
    tracked: TrackedRequest,
    code: "conflict" | "request-invalid",
  ): void {
    if (tracked.generation !== submissionGeneration.current) return;
    submissionGeneration.current += 1;
    setConfirmation(null);
    setPending(null);
    setSubmissionError(null);
    if (code === "conflict" || !isMarketRefreshIdempotencyKey(tracked.request.idempotencyKey)) {
      setSubmissionError("Unable to create this refresh. Review the request again to start a new submission.");
      focusAfterCommit.current = trigger.current;
    } else {
      setTargetError("Choose a valid Research Session date.");
      focusAfterCommit.current = targetInput.current;
    }
  }

  function reconcileSubmission(tracked: TrackedRequest): void {
    if (tracked.generation !== submissionGeneration.current) return;
    setConfirmation(null);
    operationGeneration.current += 1;
    setOperation(null);
    setPollError(false);
    setSubmissionError(null);
    setPending(tracked);
    focusAfterCommit.current = trigger.current;
  }

  function failKnownSubmission(tracked: TrackedRequest, reason: unknown): void {
    if (tracked.generation !== submissionGeneration.current) return;
    submissionGeneration.current += 1;
    setConfirmation(null);
    setPending(null);
    setPollError(false);
    setSubmissionError(financialMutationMessage(reason));
    focusAfterCommit.current = trigger.current;
  }

  return (
    <>
      <section aria-labelledby="operator-financial-refresh-heading" className="operator-section">
        <header className="operator-section-header">
          <div>
            <h2 id="operator-financial-refresh-heading">Financial Refresh</h2>
          </div>
        </header>
        <form
          className="operator-refresh-form"
          onSubmit={(event) => {
            event.preventDefault();
            review();
          }}
        >
          <div className="operator-refresh-field">
            <label htmlFor="operator-financial-target">
              Observation-through Research Session
            </label>
            <input
              aria-describedby={targetError === null
                ? "operator-financial-target-help"
                : "operator-financial-target-help operator-financial-target-error"}
              aria-invalid={targetError === null ? undefined : true}
              autoComplete="off"
              disabled={confirmation !== null || pending !== null}
              id="operator-financial-target"
              onChange={(event) => {
                setTarget(event.target.value);
                setTargetError(null);
              }}
              ref={targetInput}
              required
              type="date"
              value={target}
            />
            <small id="operator-financial-target-help">
              Select the observation-through Research Session.
            </small>
            {targetError === null ? null : (
              <small className="operator-field-error" id="operator-financial-target-error" role="alert">
                {targetError}
              </small>
            )}
          </div>
          {submissionError === null ? null : (
            <p className="inline-status inline-status-error operator-refresh-form-error" role="alert">
              {submissionError}
            </p>
          )}
          <footer>
            <button
              className="button-primary"
              disabled={confirmation !== null || pending !== null}
              ref={trigger}
              type="submit"
            >
              Review Refresh
            </button>
          </footer>
        </form>
      </section>

      {pending === null ? null : (
        <FinancialRefreshReconciliation
          onRetry={() => {
            setPending(null);
            setPollError(false);
            setSubmissionError(null);
            beginConfirmation(pending.request);
          }}
          onStop={() => {
            if (submissionGeneration.current === pending.generation) {
              submissionGeneration.current += 1;
            }
            setPending(null);
            setPollError(false);
            setSubmissionError(
              "Automatic receipt checks stopped. Retry with the same idempotency key to reconcile any accepted work.",
            );
            focusAfterCommit.current = trigger.current;
          }}
          pollError={pollError}
          request={pending.request}
        />
      )}
      {operation === null ? null : (
        <FinancialRefreshReceipt operation={operation.operation} pollError={pollError} />
      )}
      {confirmation === null ? null : (
        <FinancialRefreshDialog
          onDismiss={() => {
            if (confirmation.generation !== submissionGeneration.current) return;
            submissionGeneration.current += 1;
            setConfirmation(null);
            focusAfterCommit.current = trigger.current;
          }}
          onRejected={(code) => rejectRequest(confirmation, code)}
          onSubmissionFailed={(reason) => failKnownSubmission(confirmation, reason)}
          onSubmissionUncertain={() => reconcileSubmission(confirmation)}
          onSucceeded={(accepted) => {
            if (confirmation.generation !== submissionGeneration.current) return;
            submissionGeneration.current += 1;
            replaceOperation(accepted);
            onOperationAccepted();
            setConfirmation(null);
            setPending(null);
            setPollError(false);
            setSubmissionError(null);
            focusAfterCommit.current = trigger.current;
          }}
          request={confirmation.request}
        />
      )}
    </>
  );
}

function ignoreAcceptedOperation(): void {
  // This panel can be rendered alone in focused tests and previews.
}

export function FinancialRefreshReconciliation({
  onRetry,
  onStop,
  pollError,
  request,
}: Readonly<{
  onRetry: () => void;
  onStop: () => void;
  pollError: boolean;
  request: FinancialRefreshRequest;
}>) {
  return (
    <section
      aria-labelledby="operator-financial-refresh-reconciliation"
      className="operator-refresh-receipt operator-refresh-running"
    >
      <header aria-atomic="true" aria-live="polite" role="status">
        <div>
          <p className="eyebrow">Latest Financial operation</p>
          <h2 id="operator-financial-refresh-reconciliation">Confirming submission</h2>
        </div>
        <span className="operator-state">Checking</span>
      </header>
      <p>
        Core submission had already started, but its response could not be confirmed.
        Checking the exact idempotency key until its durable receipt is available.
      </p>
      <dl>
        <div><dt>Idempotency key</dt><dd><code>{request.idempotencyKey}</code></dd></div>
        <div><dt>Observation through</dt><dd>{request.observationThroughSession}</dd></div>
      </dl>
      {pollError ? (
        <p className="inline-status inline-status-error" role="alert">
          Receipt unavailable; retrying while visible.
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

export function FinancialRefreshReceipt({
  operation,
  pollError,
}: Readonly<{ operation: FinancialRefreshOperation; pollError: boolean }>) {
  const presentation = financialPresentation(operation);
  const unknownDiagnostic = operation.status === "failed" ? "Unavailable" : "Pending";
  return (
    <section className={`operator-refresh-receipt operator-refresh-${presentation.tone}`}>
      <header aria-atomic="true" aria-live="polite" role="status">
        <div><p className="eyebrow">Latest Financial operation</p><h2>{presentation.title}</h2></div>
        <span className="operator-state">{presentation.label}</span>
      </header>
      <p>{presentation.description}</p>
      <FinancialRefreshTelemetry progress={operation.progress} />
      <dl>
        <div><dt>Idempotency key</dt><dd><code>{operation.idempotencyKey}</code></dd></div>
        <div><dt>Observation through</dt><dd>{operation.observationThroughSession}</dd></div>
        <div><dt>Complete through</dt><dd>{operation.financialCompleteThroughSession ?? "Not completed"}</dd></div>
        <div><dt>Attempts</dt><dd>{operation.attemptCount}</dd></div>
        <div><dt>Matched triggers</dt><dd>{operation.matchedTriggerCount ?? unknownDiagnostic}</dd></div>
        <div><dt>Checked, no structured change</dt><dd>{operation.checkedNoStructuredChangeCount ?? unknownDiagnostic}</dd></div>
        <div><dt>Pending instruments</dt><dd>{operation.pendingInstrumentCount ?? unknownDiagnostic}</dd></div>
        <div><dt>Discovery gaps</dt><dd>{operation.discoveryGapCount ?? unknownDiagnostic}</dd></div>
        <div><dt>Failure</dt><dd><code>{operation.failureCode ?? operation.lastFailureCode ?? "None"}</code></dd></div>
      </dl>
      {pollError ? (
        <p className="inline-status inline-status-error" role="alert">
          Status is temporarily unavailable. Showing the last known state and retrying while visible.
        </p>
      ) : null}
    </section>
  );
}

function FinancialRefreshDialog({
  onDismiss,
  onRejected,
  onSubmissionFailed,
  onSubmissionUncertain,
  onSucceeded,
  request: refreshRequest,
}: Readonly<{
  onDismiss: () => void;
  onRejected: (code: "conflict" | "request-invalid") => void;
  onSubmissionFailed: (reason: unknown) => void;
  onSubmissionUncertain: () => void;
  onSucceeded: (operation: FinancialRefreshOperation) => void;
  request: FinancialRefreshRequest;
}>) {
  const dialog = useRef<HTMLDialogElement | null>(null);
  const dismissed = useRef(false);
  const mounted = useRef(true);
  const phase = useRef<"idle" | "proof" | "submission">("idle");
  const activeRequest = useRef<AbortController | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const element = dialog.current;
    if (element === null) return;
    mounted.current = true;
    element.showModal();
    return () => {
      mounted.current = false;
      if (!dismissed.current || phase.current !== "submission") activeRequest.current?.abort();
      activeRequest.current = null;
      if (element.open) element.close();
    };
  }, []);

  async function submit(): Promise<void> {
    if (submitting) return;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    let accepted: FinancialRefreshOperation | null = null;
    let rejected: "conflict" | "request-invalid" | null = null;
    let uncertain = false;
    let knownFailureAfterDismissal = false;
    let knownFailureReason: unknown;
    setSubmitting(true);
    setError(null);
    try {
      phase.current = "proof";
      const confirmed = await confirmFinancialRefreshProof(
        refreshRequest,
        password,
        controller.signal,
      );
      if (dismissed.current || !mounted.current) return;
      setPassword("");
      phase.current = "submission";
      accepted = await submitFinancialRefresh(
        refreshRequest,
        confirmed.proof,
        controller.signal,
      );
    } catch (reason) {
      if (phase.current === "submission" && submissionFailureIsUncertain(reason)) {
        if (!dismissed.current && mounted.current) uncertain = true;
      } else if (reason instanceof DOMException && reason.name === "AbortError") {
        // Closing password confirmation before Core submission has no mutation side effect.
      } else if (
        reason instanceof OperatorMutationError
        && (reason.code === "conflict" || reason.code === "request-invalid")
      ) {
        rejected = reason.code;
      } else if (dismissed.current) {
        knownFailureAfterDismissal = true;
        knownFailureReason = reason;
      }
      else if (mounted.current) setError(financialMutationMessage(reason));
    } finally {
      phase.current = "idle";
      activeRequest.current = null;
      if (mounted.current) {
        setPassword("");
        setSubmitting(false);
      }
    }
    if (rejected !== null) onRejected(rejected);
    else if (accepted !== null) onSucceeded(accepted);
    else if (uncertain) onSubmissionUncertain();
    else if (knownFailureAfterDismissal) onSubmissionFailed(knownFailureReason);
  }

  function dismiss(): void {
    dismissed.current = true;
    if (phase.current === "submission") onSubmissionUncertain();
    else {
      activeRequest.current?.abort();
      activeRequest.current = null;
      onDismiss();
    }
  }

  return (
    <dialog
      aria-describedby="operator-financial-refresh-description"
      aria-labelledby="operator-financial-refresh-title"
      aria-modal="true"
      className="operator-confirmation-dialog"
      onCancel={(event) => {
        event.preventDefault();
        dismiss();
      }}
      onKeyDown={(event) => containDialogKeyboardFocus(event, dialog.current)}
      ref={dialog}
    >
      <form className="operator-confirmation-content" onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}>
        <header><p className="eyebrow">Password confirmation</p><h2 id="operator-financial-refresh-title">Submit Financial Refresh?</h2></header>
        <p id="operator-financial-refresh-description">Confirm the exact CLI-equivalent collection boundary before queuing.</p>
        <dl className="operator-confirmation-target">
          <div><dt>Kind</dt><dd><strong>Financial</strong></dd></div>
          <div><dt>Observation through</dt><dd><code>{refreshRequest.observationThroughSession}</code></dd></div>
          <div><dt>Idempotency key</dt><dd><code>{refreshRequest.idempotencyKey}</code></dd></div>
        </dl>
        <div className="operator-confirmation-effect">
          <span>Effect</span>
          <p>The operation enters the shared durable FIFO. Collection and publication happen later in the Data Operator Worker.</p>
        </div>
        <label className="operator-confirmation-field">
          <span>Current password</span>
          <input
            autoComplete="current-password"
            autoFocus
            disabled={submitting}
            maxLength={128}
            minLength={12}
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
        </label>
        {error === null ? null : <p className="inline-status inline-status-error" role="alert">{error}</p>}
        <footer className="operator-confirmation-actions">
          <button onClick={dismiss} type="button">Cancel</button>
          <button className="button-primary" disabled={submitting} type="submit">{submitting ? "Submitting…" : "Submit Refresh"}</button>
        </footer>
      </form>
    </dialog>
  );
}

function financialPresentation(operation: FinancialRefreshOperation): Readonly<{
  description: string;
  label: string;
  title: string;
  tone: string;
}> {
  if (operation.status === "accepted") return {
    description: "Accepted is queued, not published. The shared Data Operator Worker claims it in FIFO order.",
    label: "Accepted",
    title: "Financial Refresh accepted",
    tone: "pending",
  };
  if (operation.status === "running") return {
    description: "Financial discovery, collection, Canonical projection, and publication are running.",
    label: "Running",
    title: "Financial Refresh running",
    tone: "running",
  };
  if (operation.outcome === "degraded") return {
    description: operation.discoveryGapCount !== null && operation.discoveryGapCount > 0
      ? "A usable Dataset was published, but discovery gaps remain; complete-through may lag the requested Session."
      : "A usable Dataset was published, but some instruments remain pending and may require a later Refresh.",
    label: "Degraded success",
    title: "Financial data published with unresolved coverage",
    tone: "unchanged",
  };
  if (operation.outcome === "published") return {
    description: "Financial Canonical data changed and a new immutable Dataset Generation was published.",
    label: "Published",
    title: "Financial data published",
    tone: "published",
  };
  if (operation.outcome === "no_change") return {
    description: "Discovery completed and the Financial Canonical data did not change.",
    label: "No change",
    title: "Financial Refresh completed",
    tone: "unchanged",
  };
  if (operation.outcome === "business_rejected") return {
    description: "The requested Financial target was rejected by Dataset business rules and will not retry.",
    label: "Rejected",
    title: "Financial Refresh rejected",
    tone: "failed",
  };
  return {
    description: operation.failureCode === "RETRY_EXHAUSTED"
      ? "Infrastructure retries were exhausted without publishing the requested Financial Refresh."
      : "An internal or infrastructure failure stopped the Financial Refresh before publication and will not retry automatically.",
    label: "Failed",
    title: "Financial Refresh failed",
    tone: "failed",
  };
}

function financialRefreshIsTerminal(operation: FinancialRefreshOperation): boolean {
  return operation.status === "succeeded" || operation.status === "failed";
}

function financialMutationMessage(reason: unknown): string {
  if (reason instanceof OperatorPageNotFoundError) return "Operator access is no longer available.";
  if (!(reason instanceof OperatorMutationError)) return "Financial Refresh could not be submitted. Try again.";
  if (reason.code === "invalid-password") return "Current password is incorrect.";
  if (reason.code === "invalid-proof") return "Confirmation expired or was already used. Submit again.";
  if (reason.code === "data-not-ready") return "The current Dataset is not ready for a Financial Refresh.";
  if (reason.code === "rate-limited") return "Too many confirmation attempts. Wait one minute and try again.";
  return "Financial Refresh service is unavailable. Try again.";
}

function submissionFailureIsUncertain(reason: unknown): boolean {
  if (reason instanceof DOMException && reason.name === "AbortError") return true;
  if (reason instanceof OperatorPageNotFoundError) return false;
  return !(reason instanceof OperatorMutationError) || reason.code === "unavailable";
}

export function suggestFinancialRefreshKey(now: Date): string {
  return `financial-${now.toISOString().replace(/\.\d{3}Z$/, "Z").replaceAll("-", "").replaceAll(":", "")}-${crypto.randomUUID()}`;
}
