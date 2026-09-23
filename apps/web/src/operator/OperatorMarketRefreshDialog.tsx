import { useEffect, useRef, useState } from "react";
import { useTranslation } from "../i18n";

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
  const { t } = useTranslation("operator");
  const dialog = useRef<HTMLDialogElement | null>(null);
  const dismissed = useRef(false);
  const mounted = useRef(true);
  const phase = useRef<"idle" | "proof" | "submission">("idle");
  const request = useRef<AbortController | null>(null);
  const [error, setError] = useState<ReturnType<typeof marketRefreshMutationMessage> | null>(null);
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
          <p className="eyebrow">{t("data.common.confirmUpdate")}</p>
          <h2 id="operator-market-refresh-title">{t("data.market.submitTitle")}</h2>
        </header>
        <p id="operator-market-refresh-description">
          {t("data.market.submitDescription")}
        </p>
        <dl className="operator-confirmation-target">
          <div>
            <dt>{t("data.common.kind")}</dt>
            <dd><strong>{t("data.market.kind")}</strong></dd>
          </div>
          <div>
            <dt>{t("data.common.asOf")}</dt>
            <dd><code>{refreshRequest.asOf}</code></dd>
          </div>
          <div>
            <dt>{t("data.common.idempotencyKey")}</dt>
            <dd><code>{refreshRequest.idempotencyKey}</code></dd>
          </div>
        </dl>
        <div className="operator-confirmation-effect">
          <span>{t("data.common.effect")}</span>
          <p>{t("data.market.effect")}</p>
        </div>
        {error === null ? null : (
          <p className="inline-status inline-status-error" role="alert">{t(error)}</p>
        )}
        <footer className="operator-confirmation-actions">
          <button onClick={dismiss} type="button">
            {t("data.common.cancel")}
          </button>
          <button className="button-primary" disabled={submitting} type="submit">
            {submitting ? t("data.common.submitting") : t("data.common.submitRefresh")}
          </button>
        </footer>
      </form>
    </dialog>
  );
}

function marketRefreshMutationMessage(reason: unknown) {
  if (reason instanceof OperatorPageNotFoundError) {
    return "data.common.accessLost";
  }
  if (!(reason instanceof OperatorMutationError)) {
    return "data.market.submitFailed";
  }
  if (reason.code === "invalid-otp") return "data.common.invalidOtp";
  if (reason.code === "invalid-proof") {
    return "data.common.invalidProof";
  }
  if (reason.code === "data-not-ready") {
    return "data.market.dataNotReady";
  }
  if (reason.code === "rate-limited") {
    return "data.common.rateLimited";
  }
  return "data.market.unavailable";
}

function marketRefreshSubmissionFailureIsUncertain(reason: unknown): boolean {
  if (reason instanceof DOMException && reason.name === "AbortError") return true;
  if (reason instanceof OperatorPageNotFoundError) return false;
  return !(reason instanceof OperatorMutationError) || reason.code === "unavailable";
}
