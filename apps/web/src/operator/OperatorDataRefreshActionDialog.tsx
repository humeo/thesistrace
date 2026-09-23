import { useEffect, useRef, useState } from "react";
import { i18n, useTranslation } from "../i18n";
import type { ParseKeys } from "i18next";

import type { DataRefreshOperationalStatus } from "./operatorDataStatusClient";
import { OperatorPageNotFoundError } from "./operatorDirectoryClient";
import { containDialogKeyboardFocus } from "./operatorDialog";
import {
  confirmDataRefreshActionProof,
  type DataRefreshActionReceipt,
  type DataRefreshActionRequest,
  isMarketRefreshIdempotencyKey,
  OperatorMutationError,
  submitDataRefreshAction,
} from "./operatorMutationClient";

export type DataRefreshStatusAction = Readonly<{
  action: "cancel" | "retry";
  operation: DataRefreshOperationalStatus;
}>;

export function OperatorDataRefreshActionDialog({
  action,
  now = () => new Date(),
  onAccessNotFound,
  onDismiss,
  onStateChanged,
  onSucceeded,
}: Readonly<{
  action: DataRefreshStatusAction;
  now?: () => Date;
  onAccessNotFound: () => void;
  onDismiss: () => void;
  onStateChanged: () => void;
  onSucceeded: (receipt: DataRefreshActionReceipt) => void;
}>) {
  const { t } = useTranslation("operator");
  const dialog = useRef<HTMLDialogElement | null>(null);
  const request = useRef<AbortController | null>(null);
  const [newKey] = useState(() => (
    action.action === "retry"
      ? suggestDataRefreshRetryKey(action.operation.kind, now())
      : ""
  ));
  const [keyError, setKeyError] = useState<"newKey" | "keyInvalid" | "retryConflict" | null>(null);
  const [error, setError] = useState<ParseKeys<"operator"> | null>(null);
  const [stale, setStale] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const element = dialog.current;
    if (element === null) return;
    element.showModal();
    return () => {
      request.current?.abort();
      request.current = null;
      if (element.open) element.close();
    };
  }, []);

  async function submit(): Promise<void> {
    if (submitting || stale) return;
    if (
      action.action === "retry"
      && (!isMarketRefreshIdempotencyKey(newKey)
        || newKey === action.operation.idempotencyKey)
    ) {
      setKeyError(
        newKey === action.operation.idempotencyKey
          ? "newKey"
          : "keyInvalid",
      );
      return;
    }
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const actionRequest = dataRefreshActionRequest(action, newKey);
    let accessNotFound = false;
    let mutationStarted = false;
    let succeeded: DataRefreshActionReceipt | null = null;
    setSubmitting(true);
    setError(null);
    setKeyError(null);
    try {
      const confirmed = await confirmDataRefreshActionProof(
        actionRequest,
        controller.signal,
      );
      mutationStarted = true;
      const receipt = await submitDataRefreshAction(
        actionRequest,
        confirmed.proof,
        controller.signal,
      );
      succeeded = receipt;
    } catch (reason) {
      if (reason instanceof OperatorPageNotFoundError) {
        accessNotFound = true;
      } else if (reason instanceof DOMException && reason.name === "AbortError") {
        if (mutationStarted) markStateUncertain();
      } else if (reason instanceof OperatorMutationError) {
        if (reason.code === "conflict" && action.action === "retry") {
          setKeyError("retryConflict");
        } else if (
          reason.code === "not-cancellable"
          || reason.code === "not-retryable"
          || reason.code === "invalid-target"
        ) {
          setStale(true);
          setError(dataRefreshStateChangedMessage(action.action, reason.code));
          onStateChanged();
        } else if (mutationStarted && reason.code === "unavailable") {
          markStateUncertain();
        } else {
          setError(dataRefreshActionMessage(action.action, reason));
        }
      } else if (mutationStarted) {
        markStateUncertain();
      } else {
        setError("data.action.confirmationUnavailable");
      }
    } finally {
      request.current = null;
      setSubmitting(false);
    }
    if (accessNotFound) onAccessNotFound();
    if (succeeded !== null) onSucceeded(succeeded);
  }

  function markStateUncertain(): void {
    setStale(true);
    setError(
      "data.action.uncertain",
    );
    onStateChanged();
  }

  const operation = action.operation;
  const retry = action.action === "retry";
  const descriptionId = "operator-data-refresh-action-description";
  const titleId = "operator-data-refresh-action-title";
  return (
    <dialog
      aria-describedby={descriptionId}
      aria-labelledby={titleId}
      aria-modal="true"
      className="operator-confirmation-dialog"
      onCancel={(event) => {
        event.preventDefault();
        if (!submitting) onDismiss();
      }}
      onKeyDown={(event) => containDialogKeyboardFocus(event, dialog.current)}
      ref={dialog}
    >
      <form
        className="operator-confirmation-content"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <header>
          <p className={retry ? "eyebrow" : "eyebrow operator-danger-eyebrow"}>
            {retry ? t("data.action.retryEyebrow") : t("data.action.cancelEyebrow")}
          </p>
          <h2 id={titleId}>
            {retry
              ? t("data.action.retryTitle", { state: operation.status === "failed" ? t("data.action.failedState") : t("data.action.cancelledState") })
              : t("data.action.cancelTitle")}
          </h2>
        </header>
        <p id={descriptionId}>
          {t("data.action.description")}
        </p>
        <dl className="operator-confirmation-target">
          <div><dt>{t("data.common.kind")}</dt><dd><strong>{kindText(operation.kind)}</strong></dd></div>
          <div><dt>{t("data.common.target")}</dt><dd><code>{operationTarget(operation)}</code></dd></div>
          <div>
            <dt>{t("data.action.sourceKey")}</dt>
            <dd><code>{operation.idempotencyKey}</code></dd>
          </div>
        </dl>
        <div className={`operator-confirmation-effect${retry ? "" : " operator-confirmation-effect-danger"}`}>
          <span>{t("data.common.effect")}</span>
          <p>
            {retry
              ? t("data.action.retryEffect", { status: operation.status === "failed" ? t("data.action.failedState") : t("data.action.cancelledState") })
              : t("data.action.cancelEffect")}
          </p>
        </div>
        {keyError === null ? null : <p role="alert">{t(`data.action.${keyError}`)}</p>}
        {error === null ? null : (
          <p className="inline-status inline-status-error" role="alert">{t(error)}</p>
        )}
        <footer className="operator-confirmation-actions">
          <button disabled={submitting} onClick={onDismiss} type="button">
            {stale ? t("data.action.close") : t("data.action.back")}
          </button>
          {stale ? null : (
            <button
              className={retry ? "button-primary" : "button-danger"}
              disabled={submitting}
              type="submit"
            >
              {submitting
                ? retry ? t("data.action.retrying") : t("data.action.cancelling")
                : retry ? t("data.action.createRetry") : t("data.action.cancelQueued")}
            </button>
          )}
        </footer>
      </form>
    </dialog>
  );
}

export function suggestDataRefreshRetryKey(
  kind: DataRefreshOperationalStatus["kind"],
  now: Date,
): string {
  const timestamp = now.toISOString().slice(0, 19).replace(/[-:]/g, "") + "Z";
  return `${kind}-retry-${timestamp}-${crypto.randomUUID()}`;
}

function dataRefreshActionRequest(
  action: DataRefreshStatusAction,
  newKey: string,
): DataRefreshActionRequest {
  const base = {
    kind: action.operation.kind,
    sourceIdempotencyKey: action.operation.idempotencyKey,
    target: operationTarget(action.operation),
  };
  return action.action === "cancel"
    ? { ...base, action: "cancel" }
    : { ...base, action: "retry", newIdempotencyKey: newKey };
}

function operationTarget(operation: DataRefreshOperationalStatus): string {
  const target = operation.asOf ?? operation.observationThroughSession;
  if (target === null) throw new Error("Data Refresh action target is unavailable");
  return target;
}

function kindText(kind: DataRefreshOperationalStatus["kind"]): string {
  if (kind === "market") return i18n.t("operator:data.market.title");
  if (kind === "financial") return i18n.t("operator:data.financial.title");
  return i18n.t("operator:data.industry.title");
}

function dataRefreshStateChangedMessage(
  action: DataRefreshStatusAction["action"],
  code: "invalid-target" | "not-cancellable" | "not-retryable",
): ParseKeys<"operator"> {
  if (code === "not-cancellable") {
    return "data.action.stateChangedCancel";
  }
  if (code === "not-retryable") {
    return "data.action.stateChangedRetry";
  }
  return `data.action.targetMismatch.${action}`;
}

function dataRefreshActionMessage(
  action: DataRefreshStatusAction["action"],
  reason: OperatorMutationError,
): ParseKeys<"operator"> {
  if (reason.code === "invalid-proof") {
    return "data.common.invalidProof";
  }
  if (reason.code === "rate-limited") {
    return "data.common.rateLimited";
  }
  if (reason.code === "request-invalid") {
    return `data.action.invalidRequest.${action}`;
  }
  return `data.action.actionUnavailable.${action}`;
}
