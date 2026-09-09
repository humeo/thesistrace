import { useEffect, useRef, useState } from "react";

import { OperatorPageNotFoundError } from "./operatorDirectoryClient";
import { containDialogKeyboardFocus } from "./operatorDialog";
import {
  confirmMarketRefreshProof,
  type MarketRefreshOperation,
  type MarketRefreshRequest,
  OperatorMutationError,
  submitMarketRefresh,
} from "./operatorMutationClient";

export function OperatorMarketRefreshDialog({
  onDismiss,
  onRequestRejected,
  onSubmissionFailed,
  onSubmissionUncertain,
  onSucceeded,
  request: refreshRequest,
}: Readonly<{
  onDismiss: () => void;
  onRequestRejected: (code: "conflict" | "request-invalid") => void;
  onSubmissionFailed: (request: MarketRefreshRequest) => void;
  onSubmissionUncertain: (request: MarketRefreshRequest) => void;
  onSucceeded: (operation: MarketRefreshOperation) => void;
  request: MarketRefreshRequest;
}>) {
  const dialog = useRef<HTMLDialogElement | null>(null);
  const dismissed = useRef(false);
  const mounted = useRef(true);
  const phase = useRef<"idle" | "proof" | "submission">("idle");
  const request = useRef<AbortController | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const element = dialog.current;
    if (element === null) return;
    mounted.current = true;
    element.showModal();
    return () => {
      mounted.current = false;
      if (!dismissed.current || phase.current !== "submission") {
        request.current?.abort();
      }
      request.current = null;
      if (element.open) element.close();
    };
  }, []);

  async function submit(): Promise<void> {
    if (submitting) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    let accepted: MarketRefreshOperation | null = null;
    let rejected: "conflict" | "request-invalid" | null = null;
    let failedAfterDismissal = false;
    let uncertainWithoutDismissal = false;
    setSubmitting(true);
    setError(null);
    try {
      phase.current = "proof";
      const confirmed = await confirmMarketRefreshProof(
        refreshRequest,
        controller.signal,
      );
      if (dismissed.current || !mounted.current) return;

      phase.current = "submission";
      accepted = await submitMarketRefresh(
        refreshRequest,
        confirmed.proof,
        controller.signal,
      );
    } catch (reason) {
      if (
        phase.current === "submission"
        && marketRefreshSubmissionFailureIsUncertain(reason)
      ) {
        if (dismissed.current) {
          failedAfterDismissal = true;
        } else if (mounted.current) {
          uncertainWithoutDismissal = true;
        }
      } else if (reason instanceof DOMException && reason.name === "AbortError") {
        // Proof confirmation is read-only. Closing it before Core submission is safe.
      } else if (
        reason instanceof OperatorMutationError
        && (reason.code === "conflict" || reason.code === "request-invalid")
      ) {
        rejected = reason.code;
      } else if (dismissed.current) {
        failedAfterDismissal = true;
      } else if (mounted.current) {
        setError(marketRefreshMutationMessage(reason));
      }
    } finally {
      phase.current = "idle";
      request.current = null;
      if (mounted.current) {
        setSubmitting(false);
      }
    }
    if (!mounted.current && !dismissed.current) return;
    if (rejected !== null) {
      onRequestRejected(rejected);
    } else if (accepted !== null) {
      onSucceeded(accepted);
    } else if (uncertainWithoutDismissal) {
      onSubmissionUncertain(refreshRequest);
    } else if (failedAfterDismissal) {
      onSubmissionFailed(refreshRequest);
    }
  }

  function dismiss(): void {
    dismissed.current = true;
    if (phase.current === "submission") {
      onSubmissionUncertain(refreshRequest);
    } else {
      request.current?.abort();
      request.current = null;
      onDismiss();
    }
  }

  return (
    <dialog
      aria-describedby="operator-market-refresh-description"
      aria-labelledby="operator-market-refresh-title"
      aria-modal="true"
      className="operator-confirmation-dialog"
      onCancel={(event) => {
        event.preventDefault();
        dismiss();
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
          <p className="eyebrow">Confirm update</p>
          <h2 id="operator-market-refresh-title">Submit Market Refresh?</h2>
        </header>
        <p id="operator-market-refresh-description">
          Review the update date before submitting.
        </p>
        <dl className="operator-confirmation-target">
          <div>
            <dt>Kind</dt>
            <dd><strong>Market</strong></dd>
          </div>
          <div>
            <dt>As-of</dt>
            <dd><code>{refreshRequest.asOf}</code></dd>
          </div>
          <div>
            <dt>Idempotency key</dt>
            <dd><code>{refreshRequest.idempotencyKey}</code></dd>
          </div>
        </dl>
        <div className="operator-confirmation-effect">
          <span>Effect</span>
          <p>
            The operation will be accepted into the durable FIFO. Publication happens
            later only if the Worker validates and publishes a changed Dataset.
          </p>
        </div>
        {error === null ? null : (
          <p className="inline-status inline-status-error" role="alert">{error}</p>
        )}
        <footer className="operator-confirmation-actions">
          <button onClick={dismiss} type="button">
            Cancel
          </button>
          <button className="button-primary" disabled={submitting} type="submit">
            {submitting ? "Submitting…" : "Submit Refresh"}
          </button>
        </footer>
      </form>
    </dialog>
  );
}

function marketRefreshMutationMessage(reason: unknown): string {
  if (reason instanceof OperatorPageNotFoundError) {
    return "Operator access is no longer available.";
  }
  if (!(reason instanceof OperatorMutationError)) {
    return "Market Refresh could not be submitted. Try again.";
  }
  if (reason.code === "invalid-otp") return "The verification code is incorrect or has expired.";
  if (reason.code === "invalid-proof") {
    return "Confirmation expired or was already used. Submit again.";
  }
  if (reason.code === "data-not-ready") {
    return "The current Dataset is not ready for a Market Refresh.";
  }
  if (reason.code === "rate-limited") {
    return "Too many confirmation attempts. Wait one minute and try again.";
  }
  return "Market Refresh service is unavailable. Try again.";
}

function marketRefreshSubmissionFailureIsUncertain(reason: unknown): boolean {
  if (reason instanceof DOMException && reason.name === "AbortError") return true;
  if (reason instanceof OperatorPageNotFoundError) return false;
  return !(reason instanceof OperatorMutationError) || reason.code === "unavailable";
}
