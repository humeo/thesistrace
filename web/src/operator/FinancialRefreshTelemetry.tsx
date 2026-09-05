import type { FinancialRefreshProgress } from "./financialRefreshProgress";

const phaseLabels: Record<FinancialRefreshProgress["phase"], string> = {
  queued: "Waiting for Worker",
  preparing: "Preparing refresh",
  discovery: "Discovering announcements",
  collection: "Collecting company statements",
  publication: "Preparing Dataset publication",
  finished: "Processing finished",
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
      <dl>
        <div><dt>Announcements discovered</dt><dd>{progress.discoveredAnnouncementCount ?? "Unknown"}</dd></div>
        <div><dt>Companies processed</dt><dd>{progress.processedCompanyCount ?? "Unknown"}</dd></div>
        <div><dt>With data changes</dt><dd>{progress.updatedCompanyCount ?? "Unknown"}</dd></div>
        <div><dt>Without data changes</dt><dd>{progress.unchangedCompanyCount ?? "Unknown"}</dd></div>
        <div><dt>Companies failed</dt><dd>{progress.failedCompanyCount ?? "Unknown"}</dd></div>
        <div><dt>Last progress</dt><dd>{progress.lastProgressAt === null ? "Not recorded"
          : <time dateTime={progress.lastProgressAt} title={progress.lastProgressAt}>
            {new Date(progress.lastProgressAt).toISOString().slice(0, 19).replace("T", " ")} UTC
          </time>}</dd></div>
      </dl>
      {progress.phase !== "finished" ? (
        <p>Company counts reflect saved processing results; not published yet. Updates every 5 seconds.</p>
      ) : null}
      {gaps !== null && gaps.length > 0 ? (
        <div className="operator-financial-gaps">
          <strong>Announcement discovery gaps</strong>
          <p>Some announcements may be missing. The full affected-company count is unknown.</p>
          <ul>
            {gaps.map((gap) => (
              <li key={`${gap.category}:${gap.startDate}:${gap.endDate}`}>
                <strong>{gap.category}</strong>
                <span>{gap.startDate} – {gap.endDate}</span>
                <span>{gap.failureCode === "CNINFO_DISCOVERY_UNAVAILABLE"
                  ? "CNINFO request unavailable" : "Invalid CNINFO response"}</span>
                <code>{gap.failureCode}</code>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
