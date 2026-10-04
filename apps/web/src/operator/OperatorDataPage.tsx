import { useCallback, useEffect, useRef, useState } from "react";
import { i18n, useTranslation } from "../i18n";
import { formatNumber } from "../i18n/format";
import { CalendarDateField } from "../components/layout/CalendarDateField";
import { Page, PageContent, PageHeader } from "../components/layout/Page";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Alert, AlertDescription } from "../components/ui/alert";
import { operatorDataClasses as styles } from "./operatorDataClasses";

import { OperatorConsoleNavigation } from "./OperatorConsoleNavigation";
import { OperatorDatasetStatus } from "./OperatorDatasetStatus";
import { OperatorDatasetRefreshDialog } from "./OperatorDatasetRefreshDialog";
import { useDataRefresh } from "./useDataRefresh";
import {
  isDatasetRefreshIdempotencyKey,
  type DatasetRefreshOperation,
  type DatasetRefreshRequest,
} from "./operatorMutationClient";

type DatasetRefreshFieldErrors = Readonly<{
  asOf: string | null;
  idempotencyKey: string | null;
}>;

const noFieldErrors: DatasetRefreshFieldErrors = {
  asOf: null,
  idempotencyKey: null,
};

export function OperatorDataPage() {
  const { t } = useTranslation("operator");
  const [asOf, setAsOf] = useState("");
  const [notFound, setNotFound] = useState(false);
  const [fieldErrors, setFieldErrors] = useState(noFieldErrors);
  const [datasetStatusReloadGeneration, setDatasetStatusReloadGeneration] = useState(0);
  const asOfInput = useRef<HTMLInputElement | null>(null);
  const pendingFieldFocus = useRef<keyof DatasetRefreshFieldErrors | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const wasBusy = useRef(false);
  const attributedFailure = useRef<unknown>(null);
  const showNotFound = useCallback(() => setNotFound(true), []);
  const notifyOperationAccepted = useCallback(
    () => setDatasetStatusReloadGeneration((current) => current + 1),
    [],
  );

  const refresh = useDataRefresh("dataset", { onAccessNotFound: showNotFound, onOperationAccepted: notifyOperationAccepted });
  const { confirmation, pendingRequest: pendingSubmission, operation, pollError, submissionFailure } = refresh;
  const submissionError = submissionFailure?.kind === "rejected" && (submissionFailure.code === "conflict"
    || !isDatasetRefreshIdempotencyKey(submissionFailure.request.idempotencyKey)) ? "rejectedRequest"
    : submissionFailure?.kind === "stopped" ? "stopped" : null;
  useEffect(() => {
    const busy = confirmation !== null || pendingSubmission !== null;
    if (submissionFailure?.kind === "rejected" && attributedFailure.current !== submissionFailure) {
      attributedFailure.current = submissionFailure;
      if (submissionFailure.code === "request-invalid" && isDatasetRefreshIdempotencyKey(submissionFailure.request.idempotencyKey)) {
        setFieldErrors({ asOf: "selectedAsOfInvalid", idempotencyKey: null });
      }
      pendingFieldFocus.current = "asOf";
    }
    if (!busy && pendingFieldFocus.current !== null) {
      pendingFieldFocus.current = null;
      asOfInput.current?.focus();
    } else if (wasBusy.current && !busy) trigger.current?.focus();
    wasBusy.current = busy;
  }, [confirmation, fieldErrors, pendingSubmission, submissionFailure]);

  if (notFound) {
    return (
      <section aria-label={t("data.common.notFound")} className="page-section state-section">
        <h1>{t("data.common.notFound")}</h1>
        <p>{t("data.common.notFoundDescription")}</p>
      </section>
    );
  }

  function reviewRefresh(): void {
    if (confirmation !== null || pendingSubmission !== null) return;
    const idempotencyKey = suggestDatasetRefreshKey(new Date());
    const errors = datasetRefreshFieldErrors(asOf, idempotencyKey);
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
    refresh.review({
      asOf: datasetRefreshAsOfForDate(asOf),
      idempotencyKey,
    });
  }

  return (
    <>
      <PageContent><Page role="region" aria-label={t("data.common.pageLabel")} className={`console-workspace ${styles.page}`}>
        <PageHeader variant="console" title={t("data.common.title")} className="mb-0 max-[768px]:mb-0" />

        <OperatorConsoleNavigation current="data" />


        <section aria-labelledby="operator-market-refresh-heading" className={styles.section}>
          <header className={styles.sectionHeader}>
            <div>
              <h2 id="operator-market-refresh-heading">{t("data.dataset.title")}</h2>
            </div>
          </header>
          <form
            className={styles.marketForm}
            onSubmit={(event) => {
              event.preventDefault();
              reviewRefresh();
            }}
          >
            <CalendarDateField
              id="operator-market-as-of"
              label={t("data.common.asOf")}
              openLabel={t("data.dataset.openAsOfCalendar")}
              value={asOf}
              minimum={null}
              maximum={new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" })}
              error={fieldErrors.asOf === null ? undefined : fieldErrors.asOf === "selectedAsOfInvalid" ? t("data.dataset.selectedAsOfInvalid") : t("data.dataset.asOfInvalid")}
              errorId="operator-market-as-of-error"
              help={t("data.dataset.asOfHelp")}
              helpId="operator-market-as-of-help"
              disabled={confirmation !== null || pendingSubmission !== null}
              inputRef={asOfInput}
              required
              onChange={(value) => {
                setAsOf(value);
                setFieldErrors((current) => ({ ...current, asOf: null }));
              }}
            />
            {submissionError === null ? null : (
              <Alert variant="destructive" role="alert"><AlertDescription>{t(`data.common.${submissionError}`)}</AlertDescription></Alert>
            )}
            <footer>
              <Button disabled={confirmation !== null || pendingSubmission !== null} ref={trigger} type="submit">{t("data.common.reviewRefresh")}</Button>
            </footer>
          </form>
        </section>

        {pendingSubmission === null ? null : (
          <DatasetRefreshReconciliation
            onRetry={refresh.retryExact}
            onStop={refresh.stopChecking}
            pollError={pollError}
            request={pendingSubmission}
          />
        )}
        {operation === null ? null : (
          <DatasetRefreshReceipt operation={operation} pollError={pollError} />
        )}

        <OperatorDatasetStatus
          onAccessNotFound={showNotFound}
          reloadGeneration={datasetStatusReloadGeneration}
          onActionCompleted={(receipt) => {
            if (receipt.kind !== "dataset" || receipt.asOf === null) return;
            refresh.track({ asOf: receipt.asOf, idempotencyKey: receipt.idempotencyKey,
              kind: "dataset", status: receipt.status, phase: null, completedStages: [],
              outcome: null, attemptCount: 0, dataThroughSession: null, lastRefreshAt: null,
              failureCode: null, lastFailureCode: null });
          }}
        />
      </Page></PageContent>
      {confirmation === null ? null : (
        <OperatorDatasetRefreshDialog
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

function DatasetRefreshReconciliation({
  onRetry,
  onStop,
  pollError,
  request,
}: Readonly<{
  onRetry: () => void;
  onStop: () => void;
  pollError: boolean;
  request: DatasetRefreshRequest;
}>) {
  const { t } = useTranslation("operator");
  return (
    <section
      aria-labelledby="operator-market-refresh-reconciliation"
      className={styles.receipt} data-tone="running"
    >
      <header aria-atomic="true" aria-live="polite" role="status">
        <div>
          <p className={styles.eyebrow}>{t("data.dataset.latest")}</p>
          <h2 id="operator-market-refresh-reconciliation">{t("data.common.confirming")}</h2>
        </div>
        <Badge variant="secondary">{t("data.common.checking")}</Badge>
      </header>
      <p>
        {t("data.common.pendingDescription")}
      </p>
      <dl>
        <div><dt>{t("data.common.idempotencyKey")}</dt><dd><code>{request.idempotencyKey}</code></dd></div>
        <div><dt>{t("data.dataset.requestedAsOf")}</dt><dd><time>{request.asOf}</time></dd></div>
      </dl>
      {pollError ? (
        <Alert variant="destructive" role="alert"><AlertDescription>{t("data.common.receiptUnavailable")}</AlertDescription></Alert>
      ) : null}
      <footer className={styles.receiptActions}>
        <Button variant="outline" onClick={onStop} type="button">{t("data.common.stopChecking")}</Button>
        <Button onClick={onRetry} type="button">{t("data.common.retryExact")}</Button>
      </footer>
    </section>
  );
}

export function DatasetRefreshReceipt({
  operation,
  pollError,
}: Readonly<{
  operation: DatasetRefreshOperation;
  pollError: boolean;
}>) {
  const { t } = useTranslation("operator");
  const presentation = refreshPresentation(operation);
  return (
    <section
      aria-labelledby="operator-market-refresh-status"
      className={styles.receipt} data-tone={presentation.tone}
    >
      <header aria-atomic="true" aria-live="polite" role="status">
        <div>
          <p className={styles.eyebrow}>{t("data.dataset.latest")}</p>
          <h2 id="operator-market-refresh-status">{presentation.title}</h2>
        </div>
        <Badge variant={presentation.tone === "failed" ? "destructive" : presentation.tone === "published" ? "default" : "secondary"}>{presentation.label}</Badge>
      </header>
      <p>{presentation.description}</p>
      <ol aria-label={t("data.dataset.stages")} className="flex flex-wrap gap-4">
        {(["market", "financial", "industry", "publication"] as const).map((stage) => {
          const complete = stage === "publication" ? operation.status === "succeeded" : operation.completedStages.includes(stage);
          const active = operation.phase === stage || (stage === "market" && operation.phase === "benchmark");
          return <li key={stage} className="flex items-center gap-2">
            <span>{stage === "publication" ? t("data.dataset.publication") : t(`data.status.${stage}`)}</span>
            <Badge variant={active && operation.status === "failed" ? "destructive" : complete ? "default" : "secondary"}>
              {complete ? t(stage === "publication" ? "data.common.published" : "data.dataset.prepared")
                : active ? t(operation.status === "failed" ? "data.common.failed" : "data.common.running") : t("data.dataset.waiting")}
            </Badge>
          </li>;
        })}
      </ol>
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
        <Alert variant="destructive" role="alert"><AlertDescription>{t("data.common.statusUnavailable")}</AlertDescription></Alert>
      ) : null}
    </section>
  );
}

function refreshPresentation(operation: DatasetRefreshOperation): Readonly<{
  description: string;
  label: string;
  title: string;
  tone: string;
}> {
  if (operation.status === "cancelled") {
    return { description: i18n.t("operator:data.dataset.cancelledDescription"),
      label: i18n.t("operator:data.status.cancelled"), title: i18n.t("operator:data.status.cancelled"), tone: "unchanged" };
  }
  if (operation.status === "accepted") {
    return {
      description: i18n.t("operator:data.dataset.acceptedDescription"),
      label: i18n.t("operator:data.common.accepted"),
      title: i18n.t("operator:data.dataset.acceptedTitle"),
      tone: "pending",
    };
  }
  if (operation.status === "running") {
    return {
      description: i18n.t("operator:data.dataset.runningDescription"),
      label: i18n.t("operator:data.common.running"),
      title: i18n.t("operator:data.dataset.runningTitle"),
      tone: "running",
    };
  }
  if (operation.status === "failed") {
    return {
      description: i18n.t("operator:data.dataset.failedDescription"),
      label: i18n.t("operator:data.common.failed"),
      title: i18n.t("operator:data.dataset.failedTitle"),
      tone: "failed",
    };
  }
  if (operation.outcome === "published") {
    return {
      description: i18n.t("operator:data.dataset.publishedDescription"),
      label: i18n.t("operator:data.common.published"),
      title: i18n.t("operator:data.dataset.publishedTitle"),
      tone: "published",
    };
  }
  return {
    description: i18n.t("operator:data.dataset.unchangedDescription"),
    label: i18n.t("operator:data.common.noChange"),
    title: i18n.t("operator:data.dataset.unchangedTitle"),
    tone: "unchanged",
  };
}

function isTerminal(operation: DatasetRefreshOperation): boolean {
  return operation.status === "succeeded" || operation.status === "failed" || operation.status === "cancelled";
}

export function suggestDatasetRefreshKey(now: Date): string {
  return `dataset-${now.toISOString().replace(/\.\d{3}Z$/, "Z").replaceAll("-", "").replaceAll(":", "")}-${crypto.randomUUID()}`;
}

export function datasetRefreshAsOfForDate(date: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return "";
  const parsed = new Date(`${date}T00:00:00Z`);
  if (Number.isNaN(parsed.valueOf()) || !parsed.toISOString().startsWith(date)) return "";
  return `${date}T18:00:00+08:00`;
}



const datasetRefreshKeyError = "keyInvalid";

function datasetRefreshFieldErrors(
  asOf: string,
  idempotencyKey: string,
): DatasetRefreshFieldErrors {
  const asOfCharacters = Array.from(asOf);
  return {
    asOf: asOfCharacters.length === 0
      || datasetRefreshAsOfForDate(asOf) === ""
      ? "asOfInvalid"
      : null,
    idempotencyKey: isDatasetRefreshIdempotencyKey(idempotencyKey)
      ? null
      : datasetRefreshKeyError,
  };
}
