import { useEffect, useRef, useState } from "react";
import type { ParseKeys } from "i18next";
import { i18n, useTranslation } from "../i18n";
import { formatNumber } from "../i18n/format";
import { CalendarDateField } from "../components/layout/CalendarDateField";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "../components/ui/dialog";

import { OperatorPageNotFoundError } from "./operatorDirectoryClient";
import { FinancialRefreshTelemetry } from "./FinancialRefreshTelemetry";
import { operatorDataClasses as styles } from "./operatorDataClasses";
import { useDataRefresh } from "./useDataRefresh";
import {
  type FinancialRefreshOperation,
  type FinancialRefreshRequest,
  isIsoResearchSession,
  isDatasetRefreshIdempotencyKey,
  OperatorMutationError,
} from "./operatorMutationClient";

export function OperatorFinancialRefreshPanel({
  onAccessNotFound,
  onOperationAccepted = ignoreAcceptedOperation,
}: Readonly<{
  onAccessNotFound: () => void;
  onOperationAccepted?: () => void;
}>) {
  const { t } = useTranslation("operator");
  const [target, setTarget] = useState("");
  const [targetError, setTargetError] = useState<ParseKeys<"operator"> | null>(null);
  const targetInput = useRef<HTMLInputElement | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const refresh = useDataRefresh("financial", { onAccessNotFound, onOperationAccepted });
  const { confirmation, pendingRequest: pending, operation, pollError, submissionFailure } = refresh;
  const wasBusy = useRef(false);
  const rejected = submissionFailure?.kind === "rejected" ? submissionFailure : null;
  const invalidTarget = rejected?.code === "request-invalid" && isDatasetRefreshIdempotencyKey(rejected.request.idempotencyKey);
  const submissionError = rejected && !invalidTarget ? "data.common.rejectedRequest"
    : submissionFailure?.kind === "stopped" ? "data.common.stopped"
    : submissionFailure?.kind === "failed" ? financialMutationMessage(submissionFailure.reason) : null;
  useEffect(() => {
    const busy = confirmation !== null || pending !== null;
    if (invalidTarget) setTargetError("data.financial.targetInvalid");
    if (wasBusy.current && !busy) {
      (invalidTarget ? targetInput.current : trigger.current)?.focus();
    }
    wasBusy.current = busy;
  }, [confirmation, pending, submissionFailure]);

  function review(): void {
    if (confirmation !== null || pending !== null) return;
    const error = isIsoResearchSession(target) ? null : "data.financial.targetInvalid";
    setTargetError(error);
    if (error) { targetInput.current?.focus(); return; }
    refresh.review({ idempotencyKey: suggestFinancialRefreshKey(new Date()), observationThroughSession: target });
  }

  return (
    <>
      <section aria-labelledby="operator-financial-refresh-heading" className={styles.section}>
        <header className={styles.sectionHeader}>
          <div>
            <h2 id="operator-financial-refresh-heading">{t("data.financial.title")}</h2>
          </div>
        </header>
        <form
          className={styles.marketForm}
          onSubmit={(event) => {
            event.preventDefault();
            review();
          }}
        >
          <CalendarDateField
            id="operator-financial-target"
            label={t("data.financial.targetLabel")}
            openLabel={t("data.common.openTargetCalendar")}
            value={target}
            minimum={null}
            maximum={null}
            error={targetError === null ? undefined : t(targetError)}
            errorId="operator-financial-target-error"
            help={t("data.financial.targetHelp")}
            helpId="operator-financial-target-help"
            disabled={confirmation !== null || pending !== null}
            inputRef={targetInput}
            required
            onChange={(value) => { setTarget(value); setTargetError(null); }}
          />
          {submissionError === null ? null : (
            <Alert variant="destructive" role="alert"><AlertDescription>{t(submissionError)}</AlertDescription></Alert>
          )}
          <footer>
            <Button
              disabled={confirmation !== null || pending !== null}
              ref={trigger}
              type="submit"
            >
              {t("data.common.reviewRefresh")}
            </Button>
          </footer>
        </form>
      </section>

      {pending === null ? null : (
        <FinancialRefreshReconciliation
          onRetry={refresh.retryExact}
          onStop={refresh.stopChecking}
          pollError={pollError}
          request={pending}
        />
      )}
      {operation === null ? null : (
        <FinancialRefreshReceipt operation={operation} pollError={pollError} />
      )}
      {confirmation === null ? null : (
        <FinancialRefreshDialog
          onDismiss={refresh.dismissConfirmation}
          onSubmit={refresh.confirm}
          submitting={confirmation.submitting}
          error={confirmation.error}
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
      className={styles.receipt} data-tone="running"
    >
      <header aria-atomic="true" aria-live="polite" role="status">
        <div>
          <p className={styles.eyebrow}>{t("data.financial.latest")}</p>
          <h2 id="operator-financial-refresh-reconciliation">{t("data.common.confirming")}</h2>
        </div>
        <Badge variant="secondary">{t("data.common.checking")}</Badge>
      </header>
      <p>
        {t("data.common.pendingDescription")}
      </p>
      <dl>
        <div><dt>{t("data.common.idempotencyKey")}</dt><dd><code>{request.idempotencyKey}</code></dd></div>
        <div><dt>{t("data.common.observationThrough")}</dt><dd>{request.observationThroughSession}</dd></div>
      </dl>
      {pollError ? (
        <Alert variant="destructive" role="alert"><AlertDescription>{t("data.financial.receiptUnavailable")}</AlertDescription></Alert>
      ) : null}
      <footer className={styles.receiptActions}>
        <Button variant="outline" onClick={onStop} type="button">{t("data.common.stopChecking")}</Button>
        <Button onClick={onRetry} type="button">
          {t("data.common.retryExact")}
        </Button>
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
    <section className={styles.receipt} data-tone={presentation.tone}>
      <header aria-atomic="true" aria-live="polite" role="status">
        <div><p className={styles.eyebrow}>{t("data.financial.latest")}</p><h2>{presentation.title}</h2></div>
        <Badge variant={presentation.tone === "failed" ? "destructive" : presentation.tone === "published" ? "default" : "secondary"} className={presentation.tone === "warning" ? "text-[var(--warning)]" : undefined}>{presentation.label}</Badge>
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
        <Alert variant="destructive" role="alert"><AlertDescription>{t("data.common.statusUnavailable")}</AlertDescription></Alert>
      ) : null}
    </section>
  );
}

function FinancialRefreshDialog({ onDismiss, onSubmit, submitting, error, request: refreshRequest }: Readonly<{
  onDismiss: () => void;
  onSubmit: () => Promise<void>;
  submitting: boolean;
  error: unknown | null;
  request: FinancialRefreshRequest;
}>) {
  const { t } = useTranslation("operator");
  const initialFocus = useRef<HTMLButtonElement | null>(null);

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onDismiss(); }}>
      <DialogContent finalFocus={false} initialFocus={initialFocus} showCloseButton={false} className="max-h-[calc(100dvh-32px)] overflow-y-auto sm:max-w-lg">
        <form className={styles.confirmationForm} onSubmit={(event) => { event.preventDefault(); void onSubmit(); }}>
          <DialogHeader>
            <p className={styles.eyebrow}>{t("data.common.confirmUpdate")}</p>
            <DialogTitle id="operator-financial-refresh-title">{t("data.financial.submitTitle")}</DialogTitle>
          </DialogHeader>
          <DialogDescription id="operator-financial-refresh-description">{t("data.financial.submitDescription")}</DialogDescription>
          <dl className={styles.target}>
            <div><dt>{t("data.common.kind")}</dt><dd><strong>{t("data.financial.kind")}</strong></dd></div>
            <div><dt>{t("data.common.observationThrough")}</dt><dd><code>{refreshRequest.observationThroughSession}</code></dd></div>
            <div><dt>{t("data.common.idempotencyKey")}</dt><dd><code>{refreshRequest.idempotencyKey}</code></dd></div>
          </dl>
          <Alert role="note"><AlertDescription><strong>{t("data.common.effect")}</strong><p>{t("data.common.queueEffect")}</p></AlertDescription></Alert>
          {error === null ? null : <Alert variant="destructive" role="alert"><AlertDescription>{t(financialMutationMessage(error))}</AlertDescription></Alert>}
          <DialogFooter>
            <Button variant="outline" onClick={onDismiss} ref={initialFocus} type="button">{t("data.common.cancel")}</Button>
            <Button disabled={submitting} type="submit">{submitting ? t("data.common.submitting") : t("data.common.submitRefresh")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
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

function financialMutationMessage(reason: unknown): ParseKeys<"operator"> {
  if (reason instanceof OperatorPageNotFoundError) return "data.common.accessLost";
  if (!(reason instanceof OperatorMutationError)) return "data.financial.submitFailed";
  if (reason.code === "invalid-otp") return "data.common.invalidOtp";
  if (reason.code === "invalid-proof") return "data.common.invalidProof";
  if (reason.code === "data-not-ready") return "data.financial.dataNotReady";
  if (reason.code === "rate-limited") return "data.common.rateLimited";
  return "data.financial.unavailable";
}

export function suggestFinancialRefreshKey(now: Date): string {
  return `financial-${now.toISOString().replace(/\.\d{3}Z$/, "Z").replaceAll("-", "").replaceAll(":", "")}-${crypto.randomUUID()}`;
}
