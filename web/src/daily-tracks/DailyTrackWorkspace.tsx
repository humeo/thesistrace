import { useState, type KeyboardEvent, type ReactNode } from "react";
import { ArrowLeftIcon, CalendarBlankIcon, WarningCircleIcon } from "@phosphor-icons/react";

import type { DailyTrackDetail } from "./DailyTracksPage";
import { TrackingOriginView, TrackingProgressView } from "./DailyTracksPage";
import { DailyTrackAnalysisView } from "./DailyTrackAnalysisView";
import { CurrentHoldings, ObservationSummary, RebalanceSchedule, TrackingReturnChart, formatMoney } from "./DailyTrackObservationView";

const VIEWS = ["Performance", "Holdings", "Rebalance"] as const;
type View = typeof VIEWS[number];

export function trackStatusLabel(track: Pick<DailyTrackDetail, "status" | "progress">) {
  if (track.status === "blocked") return "Update blocked";
  if (track.status === "stopped") return "Stopped";
  if (track.status === "stopping") return "Stopping";
  if (track.progress.phase === "up_to_date") return "Up to date";
  if (track.progress.phase === "waiting") return "Update available";
  return "Updating";
}

export function DailyTrackWorkspace({ track, actions, notices }: {
  track: DailyTrackDetail; actions: ReactNode; notices: ReactNode;
}) {
  const [view, setView] = useState<View>("Performance");
  const [period, setPeriod] = useState<"tracking" | "full">("tracking");
  function navigateViews(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const next = event.key === "ArrowRight" ? (index + 1) % VIEWS.length
      : event.key === "ArrowLeft" ? (index + VIEWS.length - 1) % VIEWS.length
      : event.key === "Home" ? 0 : event.key === "End" ? VIEWS.length - 1 : null;
    if (next === null) return;
    event.preventDefault();
    setView(VIEWS[next]);
    event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("button")[next]?.focus();
  }
  return (
    <section className="daily-track-workspace" aria-label="Daily Tracks">
      <a className="track-back" href="/daily-tracks"><ArrowLeftIcon aria-hidden="true" size={14} /> All Daily Tracks</a>
      <header className="track-header">
        <div><div className="track-title-row"><h1>Daily Track</h1>
          <span className="track-status" data-status={track.status}>{trackStatusLabel(track)}</span></div>
          <p className="track-identity">Strategy observation <code>{track.id}</code></p></div>
        <div className="track-actions">{actions}</div>
      </header>
      <div className="track-dates">
        <span><CalendarBlankIcon aria-hidden="true" size={15} /> Tracking from <time>{track.origin.strategy_session}</time></span>
        <span>Last observation <time>{track.strategy_session}</time></span>
        <span>Data available through <time>{track.data_through_session}</time></span>
      </div>
      {notices}
      {track.status === "blocked" ? <div className="track-alert" role="status">
        <WarningCircleIcon size={20} aria-hidden="true" />
        <div><strong>Tracking needs an update</strong>
          <p>{track.blocked_reason} Retry after the required data is available.</p>
          <span>Showing the last successful observation from {track.strategy_session}. {track.lag_sessions} trading sessions behind.</span></div>
      </div> : track.lag_sessions > 0 && track.status === "active" && track.progress.phase === "waiting" ? (
        <p className="track-inline-notice">{track.lag_sessions} new trading {track.lag_sessions === 1 ? "session is" : "sessions are"} available. Refresh this track to continue observing the strategy.</p>
      ) : track.status === "stopped" ? <p className="track-inline-notice">This track has stopped. Its last published holdings and performance remain available.</p> : null}

      <ObservationSummary observation={track.observation} originSession={track.origin.strategy_session} />
      <div className="track-tabs" role="tablist" aria-label="Daily Track views">
        {VIEWS.map((item, index) => <button key={item} id={`track-tab-${item}`} role="tab"
          aria-selected={view === item} aria-controls={`track-panel-${item}`} tabIndex={view === item ? 0 : -1}
          onKeyDown={(event) => navigateViews(event, index)} onClick={() => setView(item)}>
          {item}{item === "Holdings" ? <span className="track-count">{track.observation.holdings.length}</span> : null}
        </button>)}
      </div>
      <div className="track-view" id={`track-panel-${view}`} role="tabpanel" aria-labelledby={`track-tab-${view}`} tabIndex={0}>
        {view === "Performance" ? <>
          <div className="track-section-heading"><div><h2>Strategy performance</h2>
            <p>{period === "tracking" ? "Returns from the account value when this track began, after trading costs." : `Includes the original backtest. Daily tracking begins on ${track.origin.strategy_session}.`}</p></div>
            <div className="track-period" role="group" aria-label="Performance period">
              <button aria-pressed={period === "tracking"} onClick={() => setPeriod("tracking")}>Since tracking</button>
              <button aria-pressed={period === "full"} onClick={() => setPeriod("full")}>Full strategy</button>
            </div>
          </div>
          {period === "tracking" ? <>
            <TrackingReturnChart observation={track.observation} originSession={track.origin.strategy_session} />
            <div className="track-performance-footnote"><span>{track.observation.session_count} trading sessions observed</span>
              <span>{formatMoney(track.observation.transaction_cost_cny)} tracking costs</span></div>
          </> : <DailyTrackAnalysisView analysis={{ strategy: track.strategy, factor: track.factor }} />}
        </> : view === "Holdings" ? <CurrentHoldings observation={track.observation} />
          : <RebalanceSchedule observation={track.observation} isStopped={track.status === "stopped" || track.status === "stopping"} isBehind={track.lag_sessions > 0} />}
      </div>
      <div className="track-supporting">
        <details className="track-disclosure"><summary>Update details <span>{trackStatusLabel(track)}</span></summary>
          <div className="track-disclosure-content"><TrackingProgressView progress={track.progress} /></div></details>
        <details className="track-disclosure"><summary>Tracking origin <span>{track.origin.strategy_session}</span></summary>
          <TrackingOriginView origin={track.origin} /></details>
      </div>
    </section>
  );
}
