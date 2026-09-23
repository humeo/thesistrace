import { useEffect, useRef, useState } from "react";
import type { ParseKeys } from "i18next";
import { i18n, useTranslation } from "../i18n";
import { formatNumber } from "../i18n/format";

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
  const { t } = useTranslation("operator");
  const [target, setTarget] = useState("");
  const [confirmation, setConfirmation] = useState<TrackedRequest | null>(null);
  const [pending, setPending] = useState<TrackedRequest | null>(null);
  const [operation, setOperation] = useState<TrackedOperation | null>(null);
  const [pollError, setPollError] = useState(false);
  const [targetError, setTargetError] = useState<ParseKeys<"operator"> | null>(null);
  const [submissionError, setSubmissionError] = useState<ParseKeys<"operator"> | null>(null);
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
      : "data.financial.targetInvalid";
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
      setSubmissionError("data.common.rejectedRequest");
      focusAfterCommit.current = trigger.current;
    } else {
      setTargetError("data.financial.targetInvalid");
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
            <h2 id="operator-financial-refresh-heading">{t("data.financial.title")}</h2>
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
              {t("data.financial.targetLabel")}
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
              {t("data.financial.targetHelp")}
            </small>
            {targetError === null ? null : (
              <small className="operator-field-error" id="operator-financial-target-error" role="alert">
                {t(targetError)}
              </small>
            )}
          </div>
          {submissionError === null ? null : (
            <p className="inline-status inline-status-error operator-refresh-form-error" role="alert">
              {t(submissionError)}
            </p>
          )}
          <footer>
            <button
              className="button-primary"
              disabled={confirmation !== null || pending !== null}
              ref={trigger}
              type="submit"
            >
              {t("data.common.reviewRefresh")}
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
              "data.common.stopped",
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
  const { t } = useTranslation("operator");
  return (
    <section
      aria-labelledby="operator-financial-refresh-reconciliation"
      className="operator-refresh-receipt operator-refresh-running"
    >
      <header aria-atomic="true" aria-live="polite" role="status">
        <div>
          <p className="eyebrow">{t("data.financial.latest")}</p>
          <h2 id="operator-financial-refresh-reconciliation">{t("data.common.confirming")}</h2>
        </div>
        <span className="operator-state">{t("data.common.checking")}</span>
      </header>
      <p>
        {t("data.common.pendingDescription")}
      </p>
      <dl>
        <div><dt>{t("data.common.idempotencyKey")}</dt><dd><code>{request.idempotencyKey}</code></dd></div>
        <div><dt>{t("data.common.observationThrough")}</dt><dd>{request.observationThroughSession}</dd></div>
      </dl>
      {pollError ? (
        <p className="inline-status inline-status-error" role="alert">
          {t("data.financial.receiptUnavailable")}
        </p>
      ) : null}
      <footer className="operator-confirmation-actions">
        <button onClick={onStop} type="button">{t("data.common.stopChecking")}</button>
        <button className="button-primary" onClick={onRetry} type="button">
          {t("data.common.retryExact")}
        </button>
      </footer>
    </section>
  );
}

export function FinancialRefreshReceipt({
  operation,
  pollError,
}: Readonly<{ operation: FinancialRefreshOperation; pollError: boolean }>) {
  const { t } = useTranslation("operator");
  const presentation = financialPresentation(operation);
  const unknownDiagnostic = operation.status === "failed" ? t("data.common.unavailable") : t("data.common.pending");
  return (
    <section className={`operator-refresh-receipt operator-refresh-${presentation.tone}`}>
      <header aria-atomic="true" aria-live="polite" role="status">
        <div><p className="eyebrow">{t("data.financial.latest")}</p><h2>{presentation.title}</h2></div>
        <span className="operator-state">{presentation.label}</span>
      </header>
      <p>{presentation.description}</p>
      <FinancialRefreshTelemetry progress={operation.progress} />
      <dl>
        <div><dt>{t("data.common.idempotencyKey")}</dt><dd><code>{operation.idempotencyKey}</code></dd></div>
        <div><dt>{t("data.common.observationThrough")}</dt><dd>{operation.observationThroughSession}</dd></div>
        <div><dt>{t("data.financial.completeThrough")}</dt><dd>{operation.financialCompleteThroughSession ?? t("data.common.notCompleted")}</dd></div>
        <div><dt>{t("data.common.attempts")}</dt><dd>{formatNumber(operation.attemptCount)}</dd></div>
        <div><dt>{t("data.financial.matchedTriggers")}</dt><dd>{operation.matchedTriggerCount === null ? unknownDiagnostic : formatNumber(operation.matchedTriggerCount)}</dd></div>
        <div><dt>{t("data.financial.checkedNoChange")}</dt><dd>{operation.checkedNoStructuredChangeCount === null ? unknownDiagnostic : formatNumber(operation.checkedNoStructuredChangeCount)}</dd></div>
        <div><dt>{t("data.financial.pendingInstruments")}</dt><dd>{operation.pendingInstrumentCount === null ? unknownDiagnostic : formatNumber(operation.pendingInstrumentCount)}</dd></div>
        <div><dt>{t("data.financial.discoveryGaps")}</dt><dd>{operation.discoveryGapCount === null ? unknownDiagnostic : formatNumber(operation.discoveryGapCount)}</dd></div>
        <div><dt>{t("data.common.failure")}</dt><dd><code>{operation.failureCode ?? operation.lastFailureCode ?? t("data.common.none")}</code></dd></div>
      </dl>
      {pollError ? (
        <p className="inline-status inline-status-error" role="alert">
          {t("data.common.statusUnavailable")}
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
  const { t } = useTranslation("operator");
  const dialog = useRef<HTMLDialogElement | null>(null);
  const dismissed = useRef(false);
  const mounted = useRef(true);
  const phase = useRef<"idle" | "proof" | "submission">("idle");
  const activeRequest = useRef<AbortController | null>(null);
  const [error, setError] = useState<ParseKeys<"operator"> | null>(null);
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
        controller.signal,
      );
      if (dismissed.current || !mounted.current) return;

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
        // Closing request confirmation before Core submission has no mutation side effect.
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
        <header><p className="eyebrow">{t("data.common.confirmUpdate")}</p><h2 id="operator-financial-refresh-title">{t("data.financial.submitTitle")}</h2></header>
        <p id="operator-financial-refresh-description">{t("data.financial.submitDescription")}</p>
        <dl className="operator-confirmation-target">
          <div><dt>{t("data.common.kind")}</dt><dd><strong>{t("data.financial.kind")}</strong></dd></div>
          <div><dt>{t("data.common.observationThrough")}</dt><dd><code>{refreshRequest.observationThroughSession}</code></dd></div>
          <div><dt>{t("data.common.idempotencyKey")}</dt><dd><code>{refreshRequest.idempotencyKey}</code></dd></div>
        </dl>
        <div className="operator-confirmation-effect">
          <span>{t("data.common.effect")}</span>
          <p>{t("data.common.queueEffect")}</p>
        </div>
        {error === null ? null : <p className="inline-status inline-status-error" role="alert">{t(error)}</p>}
        <footer className="operator-confirmation-actions">
          <button onClick={dismiss} type="button">{t("data.common.cancel")}</button>
          <button className="button-primary" disabled={submitting} type="submit">{submitting ? t("data.common.submitting") : t("data.common.submitRefresh")}</button>
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
    description: i18n.t("operator:data.financial.acceptedDescription"),
    label: i18n.t("operator:data.common.accepted"),
    title: i18n.t("operator:data.financial.acceptedTitle"),
    tone: "pending",
  };
  if (operation.status === "running") return {
    description: i18n.t("operator:data.financial.runningDescription"),
    label: i18n.t("operator:data.common.running"),
    title: i18n.t("operator:data.financial.runningTitle"),
    tone: "running",
  };
  if (operation.outcome === "degraded") return {
    description: operation.discoveryGapCount !== null && operation.discoveryGapCount > 0
      ? i18n.t("operator:data.financial.degradedGapsDescription")
      : i18n.t("operator:data.financial.degradedPendingDescription"),
    label: i18n.t("operator:data.financial.degradedLabel"),
    title: i18n.t("operator:data.financial.degradedTitle"),
    tone: "warning",
  };
  if (operation.outcome === "published") return {
    description: i18n.t("operator:data.financial.publishedDescription"),
    label: i18n.t("operator:data.common.published"),
    title: i18n.t("operator:data.financial.publishedTitle"),
    tone: "published",
  };
  if (operation.outcome === "no_change") return {
    description: i18n.t("operator:data.financial.unchangedDescription"),
    label: i18n.t("operator:data.common.noChange"),
    title: i18n.t("operator:data.financial.unchangedTitle"),
    tone: "unchanged",
  };
  if (operation.outcome === "business_rejected") return {
    description: i18n.t("operator:data.financial.rejectedDescription"),
    label: i18n.t("operator:data.common.rejected"),
    title: i18n.t("operator:data.financial.rejectedTitle"),
    tone: "failed",
  };
  return {
    description: operation.failureCode === "RETRY_EXHAUSTED"
      ? i18n.t("operator:data.financial.retryExhaustedDescription")
      : i18n.t("operator:data.financial.failedDescription"),
    label: i18n.t("operator:data.common.failed"),
    title: i18n.t("operator:data.financial.failedTitle"),
    tone: "failed",
  };
}

function financialRefreshIsTerminal(operation: FinancialRefreshOperation): boolean {
  return operation.status === "succeeded" || operation.status === "failed";
}

function financialMutationMessage(reason: unknown): ParseKeys<"operator"> {
  if (reason instanceof OperatorPageNotFoundError) return "data.common.accessLost";
  if (!(reason instanceof OperatorMutationError)) return "data.financial.submitFailed";
  if (reason.code === "invalid-otp") return "data.common.invalidOtp";
  if (reason.code === "invalid-proof") return "data.common.invalidProof";
  if (reason.code === "data-not-ready") return "data.financial.dataNotReady";
  if (reason.code === "rate-limited") return "data.common.rateLimited";
  return "data.financial.unavailable";
}

function submissionFailureIsUncertain(reason: unknown): boolean {
  if (reason instanceof DOMException && reason.name === "AbortError") return true;
  if (reason instanceof OperatorPageNotFoundError) return false;
  return !(reason instanceof OperatorMutationError) || reason.code === "unavailable";
}

export function suggestFinancialRefreshKey(now: Date): string {
  return `financial-${now.toISOString().replace(/\.\d{3}Z$/, "Z").replaceAll("-", "").replaceAll(":", "")}-${crypto.randomUUID()}`;
}
