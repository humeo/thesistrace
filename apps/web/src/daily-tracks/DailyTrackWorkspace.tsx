import { useTranslation } from "react-i18next";
import { i18n } from "../i18n";
import { formatNumber } from "../i18n/format";
import { DailyHoldings } from "../analysis/DailyHoldings";
import { StrategyEvents } from "../analysis/StrategyEvents";
import { CommonInputObservations } from "../analysis/CommonInputObservations";
import { useState, type KeyboardEvent, type ReactNode } from "react";
import { ArrowLeftIcon, CalendarBlankIcon, WarningCircleIcon } from "@phosphor-icons/react";

import type { DailyTrackDetail } from "./DailyTracksPage";
import { TrackingOriginView, TrackingProgressView } from "./DailyTracksPage";
import { DailyTrackAnalysisView } from "./DailyTrackAnalysisView";
import { CurrentHoldings, ObservationSummary, SelectionSchedule, TrackingReturnChart, formatMoney } from "./DailyTrackObservationView";

const VIEWS = ["performance", "holdings", "rebalance"] as const;
type View = typeof VIEWS[number];

export function trackStatusLabel(track: Pick<DailyTrackDetail, "status" | "progress">) {
  if (track.status === "blocked") return i18n.t("daily:statusLabels.blocked");
  if (track.status === "stopped") return i18n.t("daily:statusLabels.stopped");
  if (track.status === "stopping") return i18n.t("daily:statusLabels.stopping");
  if (track.progress.phase === "up_to_date") return i18n.t("daily:statusLabels.up_to_date");
  if (track.progress.phase === "waiting") return i18n.t("daily:statusLabels.waiting");
  return i18n.t("daily:statusLabels.updating");
}

export function DailyTrackWorkspace({ track, actions, notices }: {
  track: DailyTrackDetail; actions: ReactNode; notices: ReactNode;
}) {
  const { t } = useTranslation("daily");
  const [view, setView] = useState<View>("performance");
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
    <section className="daily-track-workspace" aria-label={t("title") }>
      <a className="track-back" href="/daily-tracks"><ArrowLeftIcon aria-hidden="true" size={14} />{t("allTracks")} </a>
      <header className="track-header">
        <div><div className="track-title-row"><h1>{t("trackHeading")} </h1>
          <span className="track-status" data-status={track.status}>{trackStatusLabel(track)}</span></div>
          <p className="track-identity">{t("strategyObservation")} <code>{track.id}</code></p></div>
        <div className="track-actions">{actions}</div>
      </header>
      <div className="track-dates">
        <span><CalendarBlankIcon aria-hidden="true" size={15} />{t("trackingFrom")} <time>{track.origin.strategy_session}</time></span>
        <span>{t("lastObservation")} <time>{track.strategy_session}</time></span>
        <span>{t("dataThrough")} <time>{track.data_through_session}</time></span>
      </div>
      {notices}
      {track.status === "blocked" ? <div className="track-alert" role="status">
        <WarningCircleIcon size={20} aria-hidden="true" />
        <div><strong>{t("needsUpdate")} </strong>
          <p>{blockedReason(track.blocked_code)}</p>
          <span>{t("blockedObservation", { date: track.strategy_session, count: track.lag_sessions })}</span></div>
      </div> : track.lag_sessions > 0 && track.status === "active" && track.progress.phase === "waiting" ? (
        <p className="track-inline-notice">{t("newSessions", { count: track.lag_sessions })}</p>
      ) : track.status === "stopped" ? <p className="track-inline-notice">{t("stoppedNotice")} </p> : null}

      <ObservationSummary observation={track.observation} originSession={track.origin.strategy_session} />
      <div className="track-tabs" role="tablist" aria-label={t("viewsTitle") }>
        {VIEWS.map((item, index) => <button key={item} id={`track-tab-${item}`} role="tab"
          aria-selected={view === item} aria-controls={`track-panel-${item}`} tabIndex={view === item ? 0 : -1}
          onKeyDown={(event) => navigateViews(event, index)} onClick={() => setView(item)}>
          {t(`views.${item}`)}{item === "holdings" ? <span className="track-count">{formatNumber(track.observation.holdings.length)}</span> : null}
        </button>)}
      </div>
      <div className="track-view" id={`track-panel-${view}`} role="tabpanel" aria-labelledby={`track-tab-${view}`} tabIndex={0}>
        {view === "performance" ? <>
          <div className="track-section-heading"><div><h2>{t("performance")} </h2>
            <p>{period === "tracking" ? t("trackingDescription") : t("fullDescription", { date: track.origin.strategy_session })}</p></div>
            <div className="track-period" role="group" aria-label={t("period") }>
              <button aria-pressed={period === "tracking"} onClick={() => setPeriod("tracking")}>{t("sinceTracking")} </button>
              <button aria-pressed={period === "full"} onClick={() => setPeriod("full")}>{t("fullStrategy")} </button>
            </div>
          </div>
          {period === "tracking" ? <>
            <TrackingReturnChart observation={track.observation} originSession={track.origin.strategy_session} />
            <div className="track-performance-footnote"><span>{t("sessionsObserved", { count: track.observation.session_count })}</span>
              <span>{t("trackingCosts", { cost: formatMoney(track.observation.transaction_cost_cny) })}</span></div>
          </> : <DailyTrackAnalysisView analysis={{ strategy: track.strategy }} />}
        </> : view === "holdings" ? <CurrentHoldings observation={track.observation} />
          : <SelectionSchedule observation={track.observation} isStopped={track.status === "stopped" || track.status === "stopping"} isBehind={track.lag_sessions > 0} />}
      </div>
      <div className="track-supporting">
        <DailyHoldings key={`holdings:${track.id}`} rerun={{ folderId: "folder_default", source: {
          kind: "daily_track", track_id: track.id,
          checkpoint_manifest_sha256: track.checkpoint_manifest_sha256,
          through_session: track.strategy_session,
        } }} endpoint={`/api/daily-tracks/${encodeURIComponent(track.id)}/holdings/query`} />
        <StrategyEvents key={`events:${track.id}`} endpoint={`/api/daily-tracks/${encodeURIComponent(track.id)}/events/query`} />
        <CommonInputObservations key={`${track.id}:${track.strategy_session}`} endpoint={`/api/daily-tracks/${encodeURIComponent(track.id)}/common-input-observations`} />
        <details className="track-disclosure"><summary>{t("updateDetails")} <span>{trackStatusLabel(track)}</span></summary>
          <div className="track-disclosure-content"><TrackingProgressView progress={track.progress} /></div></details>
        <details className="track-disclosure"><summary>{t("originDisclosure")} <span>{track.origin.strategy_session}</span></summary>
          <TrackingOriginView origin={track.origin} /></details>
      </div>
    </section>
  );
}

const blockedCodes = {
  "DATA_FAMILY_COVERAGE_UNAVAILABLE": "blockedReasons.DATA_FAMILY_COVERAGE_UNAVAILABLE",
  "FINANCIAL_COVERAGE_UNAVAILABLE": "blockedReasons.FINANCIAL_COVERAGE_UNAVAILABLE",
  "INDUSTRY_COVERAGE_UNAVAILABLE": "blockedReasons.INDUSTRY_COVERAGE_UNAVAILABLE",
  "CAPACITY_EXCEEDED": "blockedReasons.CAPACITY_EXCEEDED",
  "INFRASTRUCTURE_RETRIES_EXHAUSTED": "blockedReasons.INFRASTRUCTURE_RETRIES_EXHAUSTED",
  "WORKER_LOST": "blockedReasons.WORKER_LOST",
  "PUBLICATION_PREPARATION_ERROR": "blockedReasons.PUBLICATION_PREPARATION_ERROR",
  "TRACKING_EXECUTION_ERROR": "blockedReasons.TRACKING_EXECUTION_ERROR",
  "NUMERIC_CONTRACT_ERROR": "blockedReasons.NUMERIC_CONTRACT_ERROR",
  "USER_STOPPED": "blockedReasons.USER_STOPPED"
} as const;

export function blockedReason(code: string | null): string {
  return code !== null && Object.hasOwn(blockedCodes, code) ? i18n.t(`daily:${blockedCodes[code as keyof typeof blockedCodes]}`) : i18n.t("daily:blockedUnknown");
}
