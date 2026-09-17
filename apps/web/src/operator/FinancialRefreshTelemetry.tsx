import type { FinancialRefreshProgress } from "./financialRefreshProgress";

const phaseLabels: Record<FinancialRefreshProgress["phase"], string> = {
  queued: "Waiting for Worker",
  preparing: "Preparing refresh",
  discovery: "Checking disclosure lists",
  indicator_collection: "Collecting financial indicators",
  indicator_candidate: "Preparing financial indicator candidate",
  collection: "Collecting company statements",
  publication: "Preparing Dataset publication",
  finished: "Processing finished",
};

const candidateLabels: Record<FinancialRefreshProgress["indicatorCandidateStatus"], string> = {
  not_started: "Not started", building: "Preparing", ready: "Prepared",
  retained: "Previous version retained; no new candidate prepared",
};

export function FinancialRefreshTelemetry({
  progress,
}: Readonly<{ progress: FinancialRefreshProgress | null }>) {
  if (progress === null) return null;
  const gaps = progress.discoveryGaps;
  const elapsed = progress.elapsedSeconds;
  return (
    <section aria-label="Financial refresh telemetry" className="operator-financial-telemetry">
      <header aria-live="polite" role="status">
        <strong>{phaseLabels[progress.phase]}</strong>
        <span>{elapsed === null ? "Not started" : elapsed < 60
          ? `${elapsed}s` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`}</span>
      </header>
      <p>Statement processing</p>
      <dl>
        <div><dt>Reports disclosed</dt><dd>{progress.disclosedReportCount ?? "Unknown"}</dd></div>
        <div><dt>Companies processed</dt><dd>{progress.processedCompanyCount ?? "Unknown"}</dd></div>
        <div><dt>With data changes</dt><dd>{progress.updatedCompanyCount ?? "Unknown"}</dd></div>
        <div><dt>Without data changes</dt><dd>{progress.unchangedCompanyCount ?? "Unknown"}</dd></div>
        <div><dt>Companies failed</dt><dd>{progress.failedCompanyCount ?? "Unknown"}</dd></div>
        <div><dt>Last progress</dt><dd>{progress.lastProgressAt === null ? "Not recorded"
          : <time dateTime={progress.lastProgressAt} title={progress.lastProgressAt}>
            {new Date(progress.lastProgressAt).toISOString().slice(0, 19).replace("T", " ")} UTC
          </time>}</dd></div>
      </dl>
      <p>Financial indicators</p>
      <dl>
        <div><dt>Indicator companies scheduled</dt><dd>{progress.indicatorScheduledCount ?? "Unknown"}</dd></div>
        <div><dt>Indicator companies collected</dt><dd>{progress.indicatorCollectedCount ?? "Unknown"}</dd></div>
        <div><dt>Indicator companies failed</dt><dd>{progress.indicatorFailedCount ?? "Unknown"}</dd></div>
        <div><dt>Indicator candidate</dt><dd>{candidateLabels[progress.indicatorCandidateStatus]}</dd></div>
      </dl>
      {progress.indicatorRetainedReason === "INDICATOR_COVERAGE_UNAVAILABLE" ? (
        <p role="status">Indicator coverage could not reach a publishable date. The previous version was retained.</p>
      ) : null}
      {progress.phase !== "finished" ? (
        <p>Company counts reflect saved processing results; not published yet. Updates every 5 seconds.</p>
      ) : null}
      {gaps !== null && gaps.length > 0 ? (
        <div className="operator-financial-gaps">
          <strong>Disclosure list check gaps</strong>
          <p>The disclosure list could not be checked for these report periods.</p>
          <ul>
            {gaps.map((gap) => (
              <li key={gap.reportPeriod}>
                <strong>{gap.reportPeriod}</strong>
                <span>TuShare disclosure list unavailable or incomplete</span>
                <code>{gap.failureCode}</code>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
