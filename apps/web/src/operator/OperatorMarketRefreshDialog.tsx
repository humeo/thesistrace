import { useEffect, useRef, useState } from "react";
import { useTranslation } from "../i18n";

import { OperatorPageNotFoundError } from "./operatorDirectoryClient";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "../components/ui/dialog";
import { Button } from "../components/ui/button";
import { Alert, AlertDescription } from "../components/ui/alert";
import { operatorDataClasses as styles } from "./operatorDataClasses";
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
  const initialFocus = useRef<HTMLButtonElement | null>(null);
  const dismissed = useRef(false);
  const mounted = useRef(true);
  const phase = useRef<"idle" | "proof" | "submission">("idle");
  const request = useRef<AbortController | null>(null);
  const [error, setError] = useState<ReturnType<typeof marketRefreshMutationMessage> | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (!dismissed.current || phase.current !== "submission") {
        request.current?.abort();
      }
      request.current = null;
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
    <Dialog open onOpenChange={(open) => { if (!open) dismiss(); }}>
      <DialogContent finalFocus={false} initialFocus={initialFocus} showCloseButton={false} className="max-h-[calc(100dvh-32px)] overflow-y-auto sm:max-w-lg">
        <form className={styles.confirmationForm} onSubmit={(event) => { event.preventDefault(); void submit(); }}>
          <DialogHeader>
            <p className={styles.eyebrow}>{t("data.common.confirmUpdate")}</p>
            <DialogTitle id="operator-market-refresh-title">{t("data.market.submitTitle")}</DialogTitle>
          </DialogHeader>
          <DialogDescription id="operator-market-refresh-description">{t("data.market.submitDescription")}</DialogDescription>
          <dl className={styles.target}>
            <div><dt>{t("data.common.kind")}</dt><dd><strong>{t("data.market.kind")}</strong></dd></div>
            <div><dt>{t("data.common.asOf")}</dt><dd><code>{refreshRequest.asOf}</code></dd></div>
            <div><dt>{t("data.common.idempotencyKey")}</dt><dd><code>{refreshRequest.idempotencyKey}</code></dd></div>
          </dl>
          <Alert role="note"><AlertDescription><strong>{t("data.common.effect")}</strong><p>{t("data.market.effect")}</p></AlertDescription></Alert>
          {error === null ? null : <Alert variant="destructive" role="alert"><AlertDescription>{t(error)}</AlertDescription></Alert>}
          <DialogFooter>
            <Button variant="outline" onClick={dismiss} ref={initialFocus} type="button">{t("data.common.cancel")}</Button>
            <Button disabled={submitting} type="submit">{submitting ? t("data.common.submitting") : t("data.common.submitRefresh")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
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
