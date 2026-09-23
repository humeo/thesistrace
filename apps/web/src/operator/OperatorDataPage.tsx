import { useCallback, useEffect, useRef, useState } from "react";
import { i18n, useTranslation } from "../i18n";
import { formatNumber } from "../i18n/format";

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
  const { t } = useTranslation("operator");
  const [asOf, setAsOf] = useState("");
  const [confirmation, setConfirmation] = useState<TrackedMarketRefreshRequest | null>(null);
  const [pendingSubmission, setPendingSubmission] = useState<TrackedMarketRefreshRequest | null>(null);
  const [operation, setOperation] = useState<TrackedMarketRefreshOperation | null>(null);
  const [pollError, setPollError] = useState(false);
  const [submissionError, setSubmissionError] = useState<"rejectedRequest" | "stopped" | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [fieldErrors, setFieldErrors] = useState(noFieldErrors);
  const [datasetStatusReloadGeneration, setDatasetStatusReloadGeneration] = useState(0);
  const asOfInput = useRef<HTMLInputElement | null>(null);
  const pendingFieldFocus = useRef<keyof MarketRefreshFieldErrors | null>(null);
  const activeOperationGeneration = useRef(0);
  const activeSubmissionGeneration = useRef(0);
  const pendingSubmissionRef = useRef<TrackedMarketRefreshRequest | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const focusAfterCommit = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (confirmation !== null || pendingSubmission !== null) return;
    focusAfterCommit.current?.focus();
    focusAfterCommit.current = null;
  }, [confirmation, pendingSubmission]);
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
    const target = asOfInput.current;
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
          focusAfterCommit.current = trigger.current;
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
      <section aria-label={t("data.common.notFound")} className="page-section state-section">
        <h1>{t("data.common.notFound")}</h1>
        <p>{t("data.common.notFoundDescription")}</p>
      </section>
    );
  }

  function dismissConfirmation(generation: number): void {
    if (activeSubmissionGeneration.current !== generation) return;
    activeSubmissionGeneration.current += 1;
    setConfirmation(null);
    focusAfterCommit.current = trigger.current;
  }

  function replaceOperation(next: MarketRefreshOperation): void {
    const generation = activeOperationGeneration.current + 1;
    activeOperationGeneration.current = generation;
    setOperation({ generation, operation: next });
  }

  function reviewRefresh(): void {
    if (confirmation !== null || pendingSubmission !== null) return;
    const idempotencyKey = suggestMarketRefreshKey(new Date());
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
    beginConfirmation({
      asOf: marketRefreshAsOfForDate(asOf),
      idempotencyKey,
    });
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
      setSubmissionError("rejectedRequest");
      pendingFieldFocus.current = "asOf";
      return;
    }
    pendingFieldFocus.current = "asOf";
    setFieldErrors({
      asOf: "selectedAsOfInvalid",
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
    focusAfterCommit.current = trigger.current;
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
      <section aria-label={t("data.common.pageLabel")} className="page-section operator-page">
        <header className="page-hero">
          <div>
            <h1>{t("data.common.title")}</h1>
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
              <h2 id="operator-market-refresh-heading">{t("data.market.title")}</h2>
            </div>
          </header>
          <form
            className="operator-refresh-form"
            onSubmit={(event) => {
              event.preventDefault();
              reviewRefresh();
            }}
          >
            <div className="operator-refresh-field">
              <label htmlFor="operator-market-as-of">{t("data.common.asOf")}</label>
              <input
                aria-describedby={fieldErrors.asOf === null
                  ? "operator-market-as-of-help"
                  : "operator-market-as-of-help operator-market-as-of-error"}
                aria-invalid={fieldErrors.asOf === null ? undefined : true}
                autoComplete="off"
                disabled={confirmation !== null || pendingSubmission !== null}
                id="operator-market-as-of"
                onChange={(event) => {
                  setAsOf(event.target.value);
                  setFieldErrors((current) => ({ ...current, asOf: null }));
                }}
                required
                ref={asOfInput}
                type="date"
                value={asOf}
              />
              <small id="operator-market-as-of-help">
                {t("data.market.asOfHelp")}
              </small>
              {fieldErrors.asOf === null ? null : (
                <small className="operator-field-error" id="operator-market-as-of-error" role="alert">
                  {fieldErrors.asOf === "selectedAsOfInvalid" ? t("data.market.selectedAsOfInvalid") : t("data.market.asOfInvalid")}
                </small>
              )}
            </div>
            {submissionError === null ? null : (
              <p className="inline-status inline-status-error operator-refresh-form-error" role="alert">
                {t(`data.common.${submissionError}`)}
              </p>
            )}
            <footer>
              <button
                className="button-primary"
                disabled={confirmation !== null || pendingSubmission !== null}
                ref={trigger}
                type="submit"
              >
                {t("data.common.reviewRefresh")}
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
              setSubmissionError("stopped");
              focusAfterCommit.current = trigger.current;
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
            focusAfterCommit.current = trigger.current;
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
  const { t } = useTranslation("operator");
  return (
    <section
      aria-labelledby="operator-market-refresh-reconciliation"
      className="operator-refresh-receipt operator-refresh-running"
    >
      <header aria-atomic="true" aria-live="polite" role="status">
        <div>
          <p className="eyebrow">{t("data.market.latest")}</p>
          <h2 id="operator-market-refresh-reconciliation">{t("data.common.confirming")}</h2>
        </div>
        <span className="operator-state">{t("data.common.checking")}</span>
      </header>
      <p>
        {t("data.common.pendingDescription")}
      </p>
      <dl>
        <div><dt>{t("data.common.idempotencyKey")}</dt><dd><code>{request.idempotencyKey}</code></dd></div>
        <div><dt>{t("data.market.requestedAsOf")}</dt><dd><time>{request.asOf}</time></dd></div>
      </dl>
      {pollError ? (
        <p className="inline-status inline-status-error" role="alert">
          {t("data.common.receiptUnavailable")}
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

export function MarketRefreshReceipt({
  operation,
  pollError,
}: Readonly<{
  operation: MarketRefreshOperation;
  pollError: boolean;
}>) {
  const { t } = useTranslation("operator");
  const presentation = refreshPresentation(operation);
  return (
    <section
      aria-labelledby="operator-market-refresh-status"
      className={`operator-refresh-receipt operator-refresh-${presentation.tone}`}
    >
      <header aria-atomic="true" aria-live="polite" role="status">
        <div>
          <p className="eyebrow">{t("data.market.latest")}</p>
          <h2 id="operator-market-refresh-status">{presentation.title}</h2>
        </div>
        <span className="operator-state">{presentation.label}</span>
      </header>
      <p>{presentation.description}</p>
      <dl>
        <div><dt>{t("data.common.idempotencyKey")}</dt><dd><code>{operation.idempotencyKey}</code></dd></div>
        <div><dt>{t("data.common.asOf")}</dt><dd><time>{operation.asOf}</time></dd></div>
        <div><dt>{t("data.common.attempts")}</dt><dd>{formatNumber(operation.attemptCount)}</dd></div>
        <div>
          <dt>{t("data.common.dataThrough")}</dt>
          <dd>{operation.dataThroughSession ?? t("data.common.notPublished")}</dd>
        </div>
        <div>
          <dt>{t("data.common.lastRefresh")}</dt>
          <dd>{operation.lastRefreshAt ?? t("data.common.notCompleted")}</dd>
        </div>
        <div>
          <dt>{t("data.common.failure")}</dt>
          <dd><code>{operation.failureCode ?? operation.lastFailureCode ?? t("data.common.none")}</code></dd>
        </div>
      </dl>
      {pollError ? (
        <p className="inline-status inline-status-error" role="alert">
          {t("data.common.statusUnavailable")}
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
      description: i18n.t("operator:data.market.acceptedDescription"),
      label: i18n.t("operator:data.common.accepted"),
      title: i18n.t("operator:data.market.acceptedTitle"),
      tone: "pending",
    };
  }
  if (operation.status === "running") {
    return {
      description: i18n.t("operator:data.market.runningDescription"),
      label: i18n.t("operator:data.common.running"),
      title: i18n.t("operator:data.market.runningTitle"),
      tone: "running",
    };
  }
  if (operation.status === "failed") {
    return {
      description: i18n.t("operator:data.market.failedDescription"),
      label: i18n.t("operator:data.common.failed"),
      title: i18n.t("operator:data.market.failedTitle"),
      tone: "failed",
    };
  }
  if (operation.outcome === "published") {
    return {
      description: i18n.t("operator:data.market.publishedDescription"),
      label: i18n.t("operator:data.common.published"),
      title: i18n.t("operator:data.market.publishedTitle"),
      tone: "published",
    };
  }
  return {
    description: i18n.t("operator:data.market.unchangedDescription"),
    label: i18n.t("operator:data.common.noChange"),
    title: i18n.t("operator:data.market.unchangedTitle"),
    tone: "unchanged",
  };
}

function isTerminal(operation: MarketRefreshOperation): boolean {
  return operation.status === "succeeded" || operation.status === "failed";
}

export function suggestMarketRefreshKey(now: Date): string {
  return `market-${now.toISOString().replace(/\.\d{3}Z$/, "Z").replaceAll("-", "").replaceAll(":", "")}-${crypto.randomUUID()}`;
}

export function marketRefreshAsOfForDate(date: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return "";
  const parsed = new Date(`${date}T00:00:00Z`);
  if (Number.isNaN(parsed.valueOf()) || !parsed.toISOString().startsWith(date)) return "";
  return `${date}T18:00:00+08:00`;
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

const marketRefreshKeyError = "keyInvalid";

function marketRefreshFieldErrors(
  asOf: string,
  idempotencyKey: string,
): MarketRefreshFieldErrors {
  const asOfCharacters = Array.from(asOf);
  return {
    asOf: asOfCharacters.length === 0
      || marketRefreshAsOfForDate(asOf) === ""
      ? "asOfInvalid"
      : null,
    idempotencyKey: isMarketRefreshIdempotencyKey(idempotencyKey)
      ? null
      : marketRefreshKeyError,
  };
}
