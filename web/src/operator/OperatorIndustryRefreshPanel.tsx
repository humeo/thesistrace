import { useEffect, useRef, useState } from "react";

import { OperatorPageNotFoundError } from "./operatorDirectoryClient";
import { containDialogKeyboardFocus } from "./operatorDialog";
import {
  confirmIndustryRefreshProof,
  type IndustryRefreshOperation,
  type IndustryRefreshRequest,
  isIsoResearchSession,
  isMarketRefreshIdempotencyKey,
  loadIndustryRefresh,
  OperatorMutationError,
  submitIndustryRefresh,
} from "./operatorMutationClient";

const pollIntervalMilliseconds = 5_000;

type TrackedRequest = Readonly<{
  generation: number;
  request: IndustryRefreshRequest;
}>;
type TrackedOperation = Readonly<{
  generation: number;
  operation: IndustryRefreshOperation;
}>;

export function OperatorIndustryRefreshPanel({
  onAccessNotFound,
  onOperationAccepted = ignoreAcceptedOperation,
}: Readonly<{
  onAccessNotFound: () => void;
  onOperationAccepted?: () => void;
}>) {
  const [target, setTarget] = useState("");
  const [idempotencyKey, setIdempotencyKey] = useState(() =>
    suggestIndustryRefreshKey(new Date())
  );
  const [confirmation, setConfirmation] = useState<TrackedRequest | null>(null);
  const [pending, setPending] = useState<TrackedRequest | null>(null);
  const [operation, setOperation] = useState<TrackedOperation | null>(null);
  const [pollError, setPollError] = useState(false);
  const [targetError, setTargetError] = useState<string | null>(null);
  const [keyError, setKeyError] = useState<string | null>(null);
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const targetInput = useRef<HTMLInputElement | null>(null);
  const keyInput = useRef<HTMLInputElement | null>(null);
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
      : operation !== null && !industryRefreshIsTerminal(operation.operation)
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
        const next = await loadIndustryRefresh(tracked.request, controller.signal);
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
        if (!industryRefreshIsTerminal(next)) schedule();
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

  function replaceOperation(next: IndustryRefreshOperation): void {
    const generation = operationGeneration.current + 1;
    operationGeneration.current = generation;
    setOperation({ generation, operation: next });
  }

  function review(): void {
    const nextTargetError = isIsoResearchSession(target)
      ? null
      : "Enter an explicit Research Session as YYYY-MM-DD, exactly as accepted by the CLI.";
    const nextKeyError = isMarketRefreshIdempotencyKey(idempotencyKey)
      ? null
      : "Use 1–512 characters with no boundary whitespace, NUL, or unpaired surrogate.";
    setTargetError(nextTargetError);
    setKeyError(nextKeyError);
    if (nextTargetError !== null) {
      window.requestAnimationFrame(() => targetInput.current?.focus());
      return;
    }
    if (nextKeyError !== null) {
      window.requestAnimationFrame(() => keyInput.current?.focus());
      return;
    }
    setPollError(false);
    setSubmissionError(null);
    const generation = submissionGeneration.current + 1;
    submissionGeneration.current = generation;
    setConfirmation({
      generation,
      request: { idempotencyKey, observationThroughSession: target },
    });
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
      setKeyError(code === "conflict"
        ? "This key is already bound to a different Data Refresh target."
        : "Use 1–512 characters with no boundary whitespace, NUL, or unpaired surrogate.");
      focusAfterCommit.current = keyInput.current;
    } else {
      setTargetError(
        "Enter an explicit Research Session as YYYY-MM-DD, exactly as accepted by the CLI.",
      );
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
    setSubmissionError(industryMutationMessage(reason));
    focusAfterCommit.current = trigger.current;
  }

  return (
    <>
      <section aria-labelledby="operator-industry-refresh-heading" className="operator-section">
        <header className="operator-section-header">
          <div>
            <h2 id="operator-industry-refresh-heading">Industry Refresh</h2>
            <span>Choose the exact Research Session through which Industry data is observed.</span>
          </div>
        </header>
        <form
          className="operator-refresh-form"
          onSubmit={(event) => {
            event.preventDefault();
            review();
          }}
        >
          <label>
            <span>Observation-through Research Session</span>
            <input
              aria-describedby={targetError === null
                ? "operator-industry-target-help"
                : "operator-industry-target-help operator-industry-target-error"}
              aria-invalid={targetError === null ? undefined : true}
              autoComplete="off"
              disabled={confirmation !== null || pending !== null}
              maxLength={10}
              onChange={(event) => {
                setTarget(event.target.value);
                setTargetError(null);
              }}
              placeholder="2026-08-14"
              ref={targetInput}
              required
              spellCheck={false}
              type="text"
              value={target}
            />
            <small id="operator-industry-target-help">
              YYYY-MM-DD Research Session, exactly as accepted by the CLI. No collection
              boundary is selected for you.
            </small>
            {targetError === null ? null : (
              <small className="operator-field-error" id="operator-industry-target-error" role="alert">
                {targetError}
              </small>
            )}
          </label>
          <label>
            <span>Idempotency key</span>
            <input
              aria-describedby={keyError === null
                ? "operator-industry-key-help"
                : "operator-industry-key-help operator-industry-key-error"}
              aria-invalid={keyError === null ? undefined : true}
              autoComplete="off"
              disabled={confirmation !== null || pending !== null}
              onChange={(event) => {
                setIdempotencyKey(event.target.value);
                setKeyError(null);
              }}
              ref={keyInput}
              required
              spellCheck={false}
              type="text"
              value={idempotencyKey}
            />
            <small id="operator-industry-key-help">
              The suggestion is editable and the exact accepted key stays visible.
            </small>
            {keyError === null ? null : (
              <small className="operator-field-error" id="operator-industry-key-error" role="alert">
                {keyError}
              </small>
            )}
          </label>
          {submissionError === null ? null : (
            <p className="inline-status inline-status-error operator-refresh-form-error" role="alert">
              {submissionError}
            </p>
          )}
          <footer>
            <p>Accepted is queued, not published.</p>
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
        <IndustryRefreshReconciliation
          onRetry={() => {
            setPending(null);
            setPollError(false);
            setSubmissionError(null);
            const generation = submissionGeneration.current + 1;
            submissionGeneration.current = generation;
            setConfirmation({ generation, request: pending.request });
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
        <IndustryRefreshReceipt operation={operation.operation} pollError={pollError} />
      )}
      {confirmation === null ? null : (
        <IndustryRefreshDialog
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

export function IndustryRefreshReconciliation({
  onRetry,
  onStop,
  pollError,
  request,
}: Readonly<{
  onRetry: () => void;
  onStop: () => void;
  pollError: boolean;
  request: IndustryRefreshRequest;
}>) {
  return (
    <section
      aria-labelledby="operator-industry-refresh-reconciliation"
      className="operator-refresh-receipt operator-refresh-running"
    >
      <header aria-atomic="true" aria-live="polite" role="status">
        <div>
          <p className="eyebrow">Latest Industry operation</p>
          <h2 id="operator-industry-refresh-reconciliation">Confirming submission</h2>
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

export function IndustryRefreshReceipt({
  operation,
  pollError,
}: Readonly<{ operation: IndustryRefreshOperation; pollError: boolean }>) {
  const presentation = industryPresentation(operation);
  return (
    <section className={`operator-refresh-receipt operator-refresh-${presentation.tone}`}>
      <header aria-atomic="true" aria-live="polite" role="status">
        <div><p className="eyebrow">Latest Industry operation</p><h2>{presentation.title}</h2></div>
        <span className="operator-state">{presentation.label}</span>
      </header>
      <p>{presentation.description}</p>
      <dl>
        <div><dt>Idempotency key</dt><dd><code>{operation.idempotencyKey}</code></dd></div>
        <div><dt>Observation through</dt><dd>{operation.observationThroughSession}</dd></div>
        <div><dt>Data through</dt><dd>{operation.dataThroughSession ?? "Not completed"}</dd></div>
        <div><dt>Attempts</dt><dd>{operation.attemptCount}</dd></div>
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

function IndustryRefreshDialog({
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
  onSucceeded: (operation: IndustryRefreshOperation) => void;
  request: IndustryRefreshRequest;
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
    let accepted: IndustryRefreshOperation | null = null;
    let rejected: "conflict" | "request-invalid" | null = null;
    let uncertain = false;
    let knownFailureAfterDismissal = false;
    let knownFailureReason: unknown;
    setSubmitting(true);
    setError(null);
    try {
      phase.current = "proof";
      const confirmed = await confirmIndustryRefreshProof(
        refreshRequest,
        password,
        controller.signal,
      );
      if (dismissed.current || !mounted.current) return;
      setPassword("");
      phase.current = "submission";
      accepted = await submitIndustryRefresh(
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
      } else if (mounted.current) {
        setError(industryMutationMessage(reason));
      }
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
      aria-describedby="operator-industry-refresh-description"
      aria-labelledby="operator-industry-refresh-title"
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
        <header><p className="eyebrow">Password confirmation</p><h2 id="operator-industry-refresh-title">Submit Industry Refresh?</h2></header>
        <p id="operator-industry-refresh-description">Confirm the exact CLI-equivalent collection boundary before queuing.</p>
        <dl className="operator-confirmation-target">
          <div><dt>Kind</dt><dd><strong>Industry</strong></dd></div>
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

function industryPresentation(operation: IndustryRefreshOperation): Readonly<{
  description: string;
  label: string;
  title: string;
  tone: string;
}> {
  if (operation.status === "accepted") return {
    description: "Accepted is queued, not published. The shared Data Operator Worker claims it in FIFO order.",
    label: "Accepted",
    title: "Industry Refresh accepted",
    tone: "pending",
  };
  if (operation.status === "running") return {
    description: "Industry collection, validation, Canonical projection, and publication are running.",
    label: "Running",
    title: "Industry Refresh running",
    tone: "running",
  };
  if (operation.outcome === "published") return {
    description: "Industry Canonical data changed and a new immutable Dataset Generation was published.",
    label: "Published",
    title: "Industry data published",
    tone: "published",
  };
  if (operation.outcome === "no_change") return {
    description: "Collection completed and the Industry Canonical data did not change.",
    label: "No change",
    title: "Industry Refresh completed",
    tone: "unchanged",
  };
  if (operation.outcome === "business_rejected") return {
    description: "The requested Industry target was rejected by Dataset business rules and will not retry.",
    label: "Rejected",
    title: "Industry Refresh rejected",
    tone: "failed",
  };
  return {
    description: operation.failureCode === "RETRY_EXHAUSTED"
      ? "Infrastructure retries were exhausted without publishing the requested Industry Refresh."
      : "An internal or infrastructure failure stopped the Industry Refresh before publication and will not retry automatically.",
    label: "Failed",
    title: "Industry Refresh failed",
    tone: "failed",
  };
}

function industryRefreshIsTerminal(operation: IndustryRefreshOperation): boolean {
  return operation.status === "succeeded" || operation.status === "failed";
}

function industryMutationMessage(reason: unknown): string {
  if (reason instanceof OperatorPageNotFoundError) return "Operator access is no longer available.";
  if (!(reason instanceof OperatorMutationError)) return "Industry Refresh could not be submitted. Try again.";
  if (reason.code === "invalid-password") return "Current password is incorrect.";
  if (reason.code === "invalid-proof") return "Confirmation expired or was already used. Submit again.";
  if (reason.code === "data-not-ready") return "The current Dataset is not ready for an Industry Refresh.";
  if (reason.code === "rate-limited") return "Too many confirmation attempts. Wait one minute and try again.";
  return "Industry Refresh service is unavailable. Try again.";
}

function submissionFailureIsUncertain(reason: unknown): boolean {
  if (reason instanceof DOMException && reason.name === "AbortError") return true;
  if (reason instanceof OperatorPageNotFoundError) return false;
  return !(reason instanceof OperatorMutationError) || reason.code === "unavailable";
}

export function suggestIndustryRefreshKey(now: Date): string {
  return `industry-${now.toISOString().replace(/\.\d{3}Z$/, "Z").replaceAll("-", "").replaceAll(":", "")}`;
}
