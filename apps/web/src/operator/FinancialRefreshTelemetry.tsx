import type { FinancialRefreshProgress } from "./financialRefreshProgress";
import { useTranslation } from "../i18n";
import { formatNumber } from "../i18n/format";

const telemetryGrid = "m-0 grid grid-cols-3 overflow-hidden rounded-lg border border-border max-[640px]:grid-cols-2 [&>div]:min-w-0 [&>div]:border-b [&>div]:border-border [&>div]:p-3 [&_dt]:text-xs [&_dt]:text-muted-foreground [&_dd]:m-0 [&_dd]:mt-1 [&_dd]:break-all [&_dd]:text-sm [&_dd]:tabular-nums";

export function FinancialRefreshTelemetry({
  progress,
}: Readonly<{ progress: FinancialRefreshProgress | null }>) {
  const { t } = useTranslation("operator");
  if (progress === null) return null;
  const gaps = progress.discoveryGaps;
  const elapsed = progress.elapsedSeconds;
  const count = (value: number | null) => value === null ? t("data.telemetry.unknown") : formatNumber(value);
  return (
    <section aria-label={t("data.telemetry.label")} className="grid min-w-0 gap-3">
      <header aria-live="polite" role="status" className="flex flex-wrap justify-between gap-2 text-sm">
        <strong>{t(`data.telemetry.phases.${progress.phase}`)}</strong>
        <span className="font-mono text-muted-foreground">{elapsed === null ? t("data.telemetry.notStarted") : elapsed < 60
          ? t("data.telemetry.durationSeconds", { seconds: formatNumber(elapsed) }) : t("data.telemetry.durationMinutes", { minutes: formatNumber(Math.floor(elapsed / 60)), seconds: formatNumber(elapsed % 60) })}</span>
      </header>
      <p className="m-0 text-xs text-muted-foreground">{t("data.telemetry.statement")}</p>
      <dl className={telemetryGrid}>
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
      <p className="m-0 text-xs text-muted-foreground">{t("data.telemetry.indicators")}</p>
      <dl className={telemetryGrid}>
        <div><dt>{t("data.telemetry.scheduled")}</dt><dd>{count(progress.indicatorScheduledCount)}</dd></div>
        <div><dt>{t("data.telemetry.collected")}</dt><dd>{count(progress.indicatorCollectedCount)}</dd></div>
        <div><dt>{t("data.telemetry.indicatorFailed")}</dt><dd>{count(progress.indicatorFailedCount)}</dd></div>
        <div><dt>{t("data.telemetry.candidate")}</dt><dd>{t(`data.telemetry.candidates.${progress.indicatorCandidateStatus}`)}</dd></div>
      </dl>
      {progress.indicatorRetainedReason === "INDICATOR_COVERAGE_UNAVAILABLE" ? (
        <p role="status" className="m-0 text-xs text-[var(--warning)]">{t("data.telemetry.coverageUnavailable")}</p>
      ) : null}
      {progress.phase !== "finished" ? (
        <p className="m-0 text-xs text-muted-foreground">{t("data.telemetry.countsNote")}</p>
      ) : null}
      {gaps !== null && gaps.length > 0 ? (
        <div className="grid gap-2 border-l-2 border-l-[var(--warning)] pl-3 text-sm">
          <strong>{t("data.telemetry.gaps")}</strong>
          <p className="m-0 text-xs text-muted-foreground">{t("data.telemetry.gapsDescription")}</p>
          <ul className="m-0 grid list-none gap-3 p-0">
            {gaps.map((gap) => (
              <li className="grid gap-1 break-words" key={gap.reportPeriod}>
                <strong>{gap.reportPeriod}</strong>
                <span>{t("data.telemetry.gapFailure")}</span>
                <code className="text-xs text-muted-foreground">{gap.failureCode}</code>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
