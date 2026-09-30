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
import { operatorDataClasses as styles } from "./operatorDataClasses";
import { useDataRefresh } from "./useDataRefresh";
import {
  type IndustryRefreshOperation,
  type IndustryRefreshRequest,
  isIsoResearchSession,
  isMarketRefreshIdempotencyKey,
  OperatorMutationError,
} from "./operatorMutationClient";

export function OperatorIndustryRefreshPanel({
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
  const refresh = useDataRefresh("industry", { onAccessNotFound, onOperationAccepted });
  const { confirmation, pendingRequest: pending, operation, pollError, submissionFailure } = refresh;
  const wasBusy = useRef(false);
  const rejected = submissionFailure?.kind === "rejected" ? submissionFailure : null;
  const invalidTarget = rejected?.code === "request-invalid" && isMarketRefreshIdempotencyKey(rejected.request.idempotencyKey);
  const submissionError = rejected && !invalidTarget ? "data.common.rejectedRequest"
    : submissionFailure?.kind === "stopped" ? "data.common.stopped"
    : submissionFailure?.kind === "failed" ? industryMutationMessage(submissionFailure.reason) : null;
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
    refresh.review({ idempotencyKey: suggestIndustryRefreshKey(new Date()), observationThroughSession: target });
  }

  return (
    <>
      <section aria-labelledby="operator-industry-refresh-heading" className={styles.section}>
        <header className={styles.sectionHeader}>
          <div>
            <h2 id="operator-industry-refresh-heading">{t("data.industry.title")}</h2>
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
            id="operator-industry-target"
            label={t("data.financial.targetLabel")}
            openLabel={t("data.common.openTargetCalendar")}
            value={target}
            minimum={null}
            maximum={null}
            error={targetError === null ? undefined : t(targetError)}
            errorId="operator-industry-target-error"
            help={t("data.financial.targetHelp")}
            helpId="operator-industry-target-help"
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
        <IndustryRefreshReconciliation
          onRetry={refresh.retryExact}
          onStop={refresh.stopChecking}
          pollError={pollError}
          request={pending}
        />
      )}
      {operation === null ? null : (
        <IndustryRefreshReceipt operation={operation} pollError={pollError} />
      )}
      {confirmation === null ? null : (
        <IndustryRefreshDialog
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
  const { t } = useTranslation("operator");
  return (
    <section
      aria-labelledby="operator-industry-refresh-reconciliation"
      className={styles.receipt} data-tone="running"
    >
      <header aria-atomic="true" aria-live="polite" role="status">
        <div>
          <p className={styles.eyebrow}>{t("data.industry.latest")}</p>
          <h2 id="operator-industry-refresh-reconciliation">{t("data.common.confirming")}</h2>
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
        <Alert variant="destructive" role="alert"><AlertDescription>{t("data.industry.receiptUnavailable")}</AlertDescription></Alert>
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

export function IndustryRefreshReceipt({
  operation,
  pollError,
}: Readonly<{ operation: IndustryRefreshOperation; pollError: boolean }>) {
  const { t } = useTranslation("operator");
  const presentation = industryPresentation(operation);
  return (
    <section className={styles.receipt} data-tone={presentation.tone}>
      <header aria-atomic="true" aria-live="polite" role="status">
        <div><p className={styles.eyebrow}>{t("data.industry.latest")}</p><h2>{presentation.title}</h2></div>
        <Badge variant={presentation.tone === "failed" ? "destructive" : presentation.tone === "published" ? "default" : "secondary"} className={presentation.tone === "warning" ? "text-[var(--warning)]" : undefined}>{presentation.label}</Badge>
      </header>
      <p>{presentation.description}</p>
      <dl>
        <div><dt>{t("data.common.idempotencyKey")}</dt><dd><code>{operation.idempotencyKey}</code></dd></div>
        <div><dt>{t("data.common.observationThrough")}</dt><dd>{operation.observationThroughSession}</dd></div>
        <div><dt>{t("data.common.dataThrough")}</dt><dd>{operation.dataThroughSession ?? t("data.common.notCompleted")}</dd></div>
        <div><dt>{t("data.common.attempts")}</dt><dd>{formatNumber(operation.attemptCount)}</dd></div>
        <div><dt>{t("data.common.failure")}</dt><dd><code>{operation.failureCode ?? operation.lastFailureCode ?? t("data.common.none")}</code></dd></div>
      </dl>
      {pollError ? (
        <Alert variant="destructive" role="alert"><AlertDescription>{t("data.common.statusUnavailable")}</AlertDescription></Alert>
      ) : null}
    </section>
  );
}

function IndustryRefreshDialog({ onDismiss, onSubmit, submitting, error, request: refreshRequest }: Readonly<{
  onDismiss: () => void;
  onSubmit: () => Promise<void>;
  submitting: boolean;
  error: unknown | null;
  request: IndustryRefreshRequest;
}>) {
  const { t } = useTranslation("operator");
  const initialFocus = useRef<HTMLButtonElement | null>(null);

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onDismiss(); }}>
      <DialogContent finalFocus={false} initialFocus={initialFocus} showCloseButton={false} className="max-h-[calc(100dvh-32px)] overflow-y-auto sm:max-w-lg">
        <form className={styles.confirmationForm} onSubmit={(event) => { event.preventDefault(); void onSubmit(); }}>
          <DialogHeader>
            <p className={styles.eyebrow}>{t("data.common.confirmUpdate")}</p>
            <DialogTitle id="operator-industry-refresh-title">{t("data.industry.submitTitle")}</DialogTitle>
          </DialogHeader>
          <DialogDescription id="operator-industry-refresh-description">{t("data.industry.submitDescription")}</DialogDescription>
          <dl className={styles.target}>
            <div><dt>{t("data.common.kind")}</dt><dd><strong>{t("data.industry.kind")}</strong></dd></div>
            <div><dt>{t("data.common.observationThrough")}</dt><dd><code>{refreshRequest.observationThroughSession}</code></dd></div>
            <div><dt>{t("data.common.idempotencyKey")}</dt><dd><code>{refreshRequest.idempotencyKey}</code></dd></div>
          </dl>
          <Alert role="note"><AlertDescription><strong>{t("data.common.effect")}</strong><p>{t("data.common.queueEffect")}</p></AlertDescription></Alert>
          {error === null ? null : <Alert variant="destructive" role="alert"><AlertDescription>{t(industryMutationMessage(error))}</AlertDescription></Alert>}
          <DialogFooter>
            <Button variant="outline" onClick={onDismiss} ref={initialFocus} type="button">{t("data.common.cancel")}</Button>
            <Button disabled={submitting} type="submit">{submitting ? t("data.common.submitting") : t("data.common.submitRefresh")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function industryPresentation(operation: IndustryRefreshOperation): Readonly<{
  description: string;
  label: string;
  title: string;
  tone: string;
}> {
  if (operation.status === "accepted") return {
    description: i18n.t("operator:data.industry.acceptedDescription"),
    label: i18n.t("operator:data.common.accepted"),
    title: i18n.t("operator:data.industry.acceptedTitle"),
    tone: "pending",
  };
  if (operation.status === "running") return {
    description: i18n.t("operator:data.industry.runningDescription"),
    label: i18n.t("operator:data.common.running"),
    title: i18n.t("operator:data.industry.runningTitle"),
    tone: "running",
  };
  if (operation.outcome === "published") return {
    description: i18n.t("operator:data.industry.publishedDescription"),
    label: i18n.t("operator:data.common.published"),
    title: i18n.t("operator:data.industry.publishedTitle"),
    tone: "published",
  };
  if (operation.outcome === "no_change") return {
    description: i18n.t("operator:data.industry.unchangedDescription"),
    label: i18n.t("operator:data.common.noChange"),
    title: i18n.t("operator:data.industry.unchangedTitle"),
    tone: "unchanged",
  };
  if (operation.outcome === "business_rejected") return {
    description: i18n.t("operator:data.industry.rejectedDescription"),
    label: i18n.t("operator:data.common.rejected"),
    title: i18n.t("operator:data.industry.rejectedTitle"),
    tone: "failed",
  };
  return {
    description: operation.failureCode === "RETRY_EXHAUSTED"
      ? i18n.t("operator:data.industry.retryExhaustedDescription")
      : i18n.t("operator:data.industry.failedDescription"),
    label: i18n.t("operator:data.common.failed"),
    title: i18n.t("operator:data.industry.failedTitle"),
    tone: "failed",
  };
}

function industryMutationMessage(reason: unknown): ParseKeys<"operator"> {
  if (reason instanceof OperatorPageNotFoundError) return "data.common.accessLost";
  if (!(reason instanceof OperatorMutationError)) return "data.industry.submitFailed";
  if (reason.code === "invalid-otp") return "data.common.invalidOtp";
  if (reason.code === "invalid-proof") return "data.common.invalidProof";
  if (reason.code === "data-not-ready") return "data.industry.dataNotReady";
  if (reason.code === "rate-limited") return "data.common.rateLimited";
  return "data.industry.unavailable";
}

export function suggestIndustryRefreshKey(now: Date): string {
  return `industry-${now.toISOString().replace(/\.\d{3}Z$/, "Z").replaceAll("-", "").replaceAll(":", "")}-${crypto.randomUUID()}`;
}
