import { useEffect, useRef, useState } from "react";

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
  const dialog = useRef<HTMLDialogElement | null>(null);
  const request = useRef<AbortController | null>(null);
  const [password, setPassword] = useState("");
  const [newKey, setNewKey] = useState(() => (
    action.action === "retry"
      ? suggestDataRefreshRetryKey(action.operation.kind, now())
      : ""
  ));
  const [keyError, setKeyError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
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
          ? "Use a new key; Retry never reopens the source receipt."
          : "Enter a non-empty key of at most 512 characters without boundary whitespace.",
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
        password,
        controller.signal,
      );
      setPassword("");
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
          setKeyError("This key is already in use. Enter a different new key.");
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
        setError("Confirmation is temporarily unavailable. Try again.");
      }
    } finally {
      setPassword("");
      request.current = null;
      setSubmitting(false);
    }
    if (accessNotFound) onAccessNotFound();
    if (succeeded !== null) onSucceeded(succeeded);
  }

  function markStateUncertain(): void {
    setStale(true);
    setError(
      "The mutation response could not be confirmed. Dataset status was reloaded; inspect both receipts before acting again.",
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
            {retry ? "Immutable Retry" : "Queued work cancellation"}
          </p>
          <h2 id={titleId}>
            {retry
              ? `Retry ${operation.status === "failed" ? "failed" : "cancelled"} Refresh?`
              : "Cancel queued Refresh?"}
          </h2>
        </header>
        <p id={descriptionId}>
          Review the exact receipt and effect before confirming with your current password.
        </p>
        <dl className="operator-confirmation-target">
          <div><dt>Kind</dt><dd><strong>{kindText(operation.kind)}</strong></dd></div>
          <div><dt>Target</dt><dd><code>{operationTarget(operation)}</code></dd></div>
          <div>
            <dt>Source idempotency key</dt>
            <dd><code>{operation.idempotencyKey}</code></dd>
          </div>
        </dl>
        <div className={`operator-confirmation-effect${retry ? "" : " operator-confirmation-effect-danger"}`}>
          <span>Effect</span>
          <p>
            {retry
              ? `The original ${operation.status} receipt remains unchanged and inspectable. A new receipt will be accepted into the FIFO as new queued work; it is not processed or published yet.`
              : "The Worker will never claim this queued receipt. No running or terminal operation can be changed, and no Dataset publication is implied."}
          </p>
        </div>
        {retry ? (
          <label className="operator-confirmation-field">
            <span>New idempotency key</span>
            <input
              aria-describedby={keyError === null ? undefined : "operator-data-refresh-key-error"}
              aria-invalid={keyError === null ? undefined : true}
              autoComplete="off"
              disabled={submitting || stale}
              maxLength={512}
              onChange={(event) => {
                setNewKey(event.target.value);
                setKeyError(null);
              }}
              required
              spellCheck={false}
              type="text"
              value={newKey}
            />
            {keyError === null ? null : (
              <small className="operator-field-error" id="operator-data-refresh-key-error" role="alert">
                {keyError}
              </small>
            )}
          </label>
        ) : null}
        <label className="operator-confirmation-field">
          <span>Current password</span>
          <input
            autoComplete="current-password"
            autoFocus
            disabled={submitting || stale}
            maxLength={128}
            minLength={12}
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
        </label>
        {error === null ? null : (
          <p className="inline-status inline-status-error" role="alert">{error}</p>
        )}
        <footer className="operator-confirmation-actions">
          <button disabled={submitting} onClick={onDismiss} type="button">
            {stale ? "Close" : "Back"}
          </button>
          {stale ? null : (
            <button
              className={retry ? "button-primary" : "button-danger"}
              disabled={submitting}
              type="submit"
            >
              {submitting
                ? retry ? "Retrying…" : "Cancelling…"
                : retry ? "Create Retry" : "Cancel queued operation"}
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
  return `${kind}-retry-${timestamp}`;
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
  if (kind === "market") return "Market Refresh";
  if (kind === "financial") return "Financial Refresh";
  return "Industry Refresh";
}

function dataRefreshStateChangedMessage(
  action: DataRefreshStatusAction["action"],
  code: "invalid-target" | "not-cancellable" | "not-retryable",
): string {
  if (code === "not-cancellable") {
    return "The Worker claimed this operation before Cancel won. Running or terminal work was not changed; status was reloaded.";
  }
  if (code === "not-retryable") {
    return "This source receipt is no longer failed or cancelled. No Retry was created; status was reloaded.";
  }
  return `The ${action === "cancel" ? "Cancel" : "Retry"} target no longer matches this receipt. No operation was changed; status was reloaded.`;
}

function dataRefreshActionMessage(
  action: DataRefreshStatusAction["action"],
  reason: OperatorMutationError,
): string {
  if (reason.code === "invalid-password") return "Current password is incorrect.";
  if (reason.code === "invalid-proof") {
    return "Confirmation expired or was already used. Submit again.";
  }
  if (reason.code === "rate-limited") {
    return "Too many confirmation attempts. Wait one minute and try again.";
  }
  if (reason.code === "request-invalid") {
    return `The ${action === "cancel" ? "Cancel" : "Retry"} request is invalid. Reload Dataset status.`;
  }
  return `${action === "cancel" ? "Cancel" : "Retry"} is temporarily unavailable. Try again.`;
}
