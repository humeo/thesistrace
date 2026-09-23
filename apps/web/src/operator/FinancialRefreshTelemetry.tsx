import type { FinancialRefreshProgress } from "./financialRefreshProgress";
import { useTranslation } from "../i18n";
import { formatNumber } from "../i18n/format";

export function FinancialRefreshTelemetry({
  progress,
}: Readonly<{ progress: FinancialRefreshProgress | null }>) {
  const { t } = useTranslation("operator");
  if (progress === null) return null;
  const gaps = progress.discoveryGaps;
  const elapsed = progress.elapsedSeconds;
  const count = (value: number | null) => value === null ? t("data.telemetry.unknown") : formatNumber(value);
  return (
    <section aria-label={t("data.telemetry.label")} className="operator-financial-telemetry">
      <header aria-live="polite" role="status">
        <strong>{t(`data.telemetry.phases.${progress.phase}`)}</strong>
        <span>{elapsed === null ? t("data.telemetry.notStarted") : elapsed < 60
          ? t("data.telemetry.durationSeconds", { seconds: formatNumber(elapsed) }) : t("data.telemetry.durationMinutes", { minutes: formatNumber(Math.floor(elapsed / 60)), seconds: formatNumber(elapsed % 60) })}</span>
      </header>
      <p>{t("data.telemetry.statement")}</p>
      <dl>
        <div><dt>{t("data.telemetry.reports")}</dt><dd>{count(progress.disclosedReportCount)}</dd></div>
        <div><dt>{t("data.telemetry.companies")}</dt><dd>{count(progress.processedCompanyCount)}</dd></div>
        <div><dt>{t("data.telemetry.changed")}</dt><dd>{count(progress.updatedCompanyCount)}</dd></div>
        <div><dt>{t("data.telemetry.unchanged")}</dt><dd>{count(progress.unchangedCompanyCount)}</dd></div>
        <div><dt>{t("data.telemetry.failed")}</dt><dd>{count(progress.failedCompanyCount)}</dd></div>
        <div><dt>{t("data.telemetry.lastProgress")}</dt><dd>{progress.lastProgressAt === null ? t("data.telemetry.notRecorded")
          : <time dateTime={progress.lastProgressAt} title={progress.lastProgressAt}>
            {new Date(progress.lastProgressAt).toISOString().slice(0, 19).replace("T", " ")} UTC
          </time>}</dd></div>
      </dl>
      <p>{t("data.telemetry.indicators")}</p>
      <dl>
        <div><dt>{t("data.telemetry.scheduled")}</dt><dd>{count(progress.indicatorScheduledCount)}</dd></div>
        <div><dt>{t("data.telemetry.collected")}</dt><dd>{count(progress.indicatorCollectedCount)}</dd></div>
        <div><dt>{t("data.telemetry.indicatorFailed")}</dt><dd>{count(progress.indicatorFailedCount)}</dd></div>
        <div><dt>{t("data.telemetry.candidate")}</dt><dd>{t(`data.telemetry.candidates.${progress.indicatorCandidateStatus}`)}</dd></div>
      </dl>
      {progress.indicatorRetainedReason === "INDICATOR_COVERAGE_UNAVAILABLE" ? (
        <p role="status">{t("data.telemetry.coverageUnavailable")}</p>
      ) : null}
      {progress.phase !== "finished" ? (
        <p>{t("data.telemetry.countsNote")}</p>
      ) : null}
      {gaps !== null && gaps.length > 0 ? (
        <div className="operator-financial-gaps">
          <strong>{t("data.telemetry.gaps")}</strong>
          <p>{t("data.telemetry.gapsDescription")}</p>
          <ul>
            {gaps.map((gap) => (
              <li key={gap.reportPeriod}>
                <strong>{gap.reportPeriod}</strong>
                <span>{t("data.telemetry.gapFailure")}</span>
                <code>{gap.failureCode}</code>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
