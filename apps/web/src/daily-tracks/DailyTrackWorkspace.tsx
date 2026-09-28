import { useTranslation } from "react-i18next";
import { i18n } from "../i18n";
import { formatNumber } from "../i18n/format";
import { DailyHoldings } from "../analysis/DailyHoldings";
import { StrategyEvents } from "../analysis/StrategyEvents";
import { CommonInputObservations } from "../analysis/CommonInputObservations";
import { useState, type ReactNode } from "react";
import { CalendarBlankIcon, WarningCircleIcon } from "@phosphor-icons/react";

import type { DailyTrackDetail, DailyTrackSummary } from "./DailyTracksPage";
import { TrackingOriginView, TrackingProgressView } from "./DailyTrackFacts";
import { DailyTrackAnalysisView } from "./DailyTrackAnalysisView";
import { CurrentHoldings, ObservationSummary, SelectionSchedule, TrackingReturnChart, formatMoney } from "./DailyTrackObservationView";
import { Page, PageContent, PageHeader, Section } from "../components/layout/Page";
import { Disclosure } from "../components/layout/Disclosure";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "../components/ui/alert";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "../components/ui/toggle-group";
import { blockedReason } from "./blockedReason";

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

export function DailyTrackListPanel({ items, selectedId, loading = false, error = false, onRetry }: { items: readonly DailyTrackSummary[]; selectedId?: string; loading?: boolean; error?: boolean; onRetry?: () => void }) {
  const { t } = useTranslation("daily");
  return <aside role="region" aria-label={t("list")} className="min-w-0 self-start overflow-hidden rounded-xl border border-border bg-card">
    <div className="border-b border-border px-4 py-3 text-sm font-semibold">{t("allTracks")} <span className="font-normal text-muted-foreground">{formatNumber(items.length)}</span></div>
    {loading && !error ? <p role="status" className="m-0 px-4 py-3 text-sm text-muted-foreground">{t("loadingList")}</p> : null}
    {error ? <div role="alert" className="grid gap-2 px-4 py-3 text-sm"><span>{t("listUnavailable")}</span>{onRetry ? <Button variant="outline" onClick={onRetry}>{t("retry")}</Button> : null}</div> : null}
    <nav aria-label={t("list")} className="divide-y divide-border">
      {items.map(item => <a key={item.id} href={`/daily-tracks/${encodeURIComponent(item.id)}`} aria-current={item.id === selectedId ? "page" : undefined} aria-label={item.id} title={item.id}
        className={`block min-w-0 border-l-[3px] px-4 py-4 text-foreground no-underline hover:bg-muted ${item.id === selectedId ? "border-primary bg-muted" : "border-transparent"}`}>
        <span className="flex items-center justify-between gap-2"><strong className="truncate text-sm">{t("trackHeading")} {item.id.slice(0, 8)}</strong><Badge variant={item.status === "blocked" ? "destructive" : "secondary"}>{t(`statuses.${item.status}`)}</Badge></span>
        <span className="mt-1 block text-xs text-muted-foreground">{t("lastObservation")} <time>{item.strategy_session}</time></span>
      </a>)}
    </nav>
  </aside>;
}

export function DailyTrackWorkspace({ track, items, listError = false, onReloadList, actions, notices }: {
  track: DailyTrackDetail; items: readonly DailyTrackSummary[] | null; listError?: boolean; onReloadList?: () => void; actions: ReactNode; notices: ReactNode;
}) {
  const { t } = useTranslation("daily");
  const [view, setView] = useState<View>("performance");
  const [period, setPeriod] = useState<"tracking" | "full">("tracking");
  const selectedSummary: DailyTrackSummary = {
    id: track.id, status: track.status, seed_run_id: track.origin.seed_run_id,
    result_checksum_sha256: track.origin.result_checksum_sha256,
    origin_session: track.origin.strategy_session, strategy_session: track.strategy_session,
  };
  const visibleItems = items === null ? [selectedSummary] : items.some(item => item.id === track.id)
    ? items.map(item => item.id === track.id ? selectedSummary : item)
    : [selectedSummary, ...items];
  return (
    <Page aria-label={t("title")}><PageContent className="flex flex-col gap-6">
      <PageHeader title={t("title")} className="mb-0" />
      <div className="grid min-w-0 gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
      <DailyTrackListPanel items={visibleItems} selectedId={track.id} loading={items === null} error={listError} onRetry={onReloadList} />
      <div className="flex min-w-0 flex-col gap-6 rounded-xl border border-border bg-card p-5">
      <header className="flex flex-wrap items-start justify-between gap-4"><div className="min-w-0"><h2 className="m-0 flex flex-wrap items-center gap-3 text-xl font-semibold">{t("trackHeading")} {track.id.slice(0, 8)}<Badge variant={track.status === "blocked" ? "destructive" : "secondary"}>{trackStatusLabel(track)}</Badge></h2>
        <p className="mb-0 mt-2 text-sm text-muted-foreground">{t("strategyObservation")} <code className="[overflow-wrap:anywhere]">{track.id}</code></p></div><div className="flex flex-wrap items-center gap-2">{actions}</div></header>
      <dl className="m-0 flex flex-wrap gap-x-8 gap-y-4 text-sm [&_dd]:m-0 [&_dt]:text-muted-foreground">
        <div><dt className="flex items-center gap-2"><CalendarBlankIcon aria-hidden="true" />{t("trackingFrom")}</dt><dd><time>{track.origin.strategy_session}</time></dd></div>
        <div><dt>{t("lastObservation")}</dt><dd><time>{track.strategy_session}</time></dd></div>
        <div><dt>{t("dataThrough")}</dt><dd><time>{track.data_through_session}</time></dd></div>
      </dl>
      {notices}
      {track.status === "blocked" ? <Alert role="status"><WarningCircleIcon aria-hidden="true" /><AlertTitle>{t("needsUpdate")}</AlertTitle>
        <AlertDescription><p>{blockedReason(track.blocked_code)}</p><p>{t("blockedObservation", { date: track.strategy_session, count: track.lag_sessions })}</p></AlertDescription>
      </Alert> : track.lag_sessions > 0 && track.status === "active" && track.progress.phase === "waiting" ? (
        <Alert role="status"><AlertDescription>{t("newSessions", { count: track.lag_sessions })}</AlertDescription></Alert>
      ) : track.status === "stopped" ? <Alert role="status"><AlertDescription>{t("stoppedNotice")}</AlertDescription></Alert> : null}
      <ObservationSummary observation={track.observation} originSession={track.origin.strategy_session} />
      <Tabs value={view} onValueChange={value => setView(value as View)} className="min-w-0 gap-6">
        <TabsList variant="line" aria-label={t("viewsTitle")} className="max-w-full flex-wrap">
          {VIEWS.map(item => <TabsTrigger key={item} value={item}>{t(`views.${item}`)}{item === "holdings" ? <Badge variant="secondary">{formatNumber(track.observation.holdings.length)}</Badge> : null}</TabsTrigger>)}
        </TabsList>
        <TabsContent keepMounted value="performance" className="min-w-0">
          <Section title={t("performance")} actions={<ToggleGroup value={[period]} onValueChange={values => { if (values[0]) setPeriod(values[0] as typeof period); }} variant="outline" aria-label={t("period")}>
            <ToggleGroupItem value="tracking">{t("sinceTracking")}</ToggleGroupItem><ToggleGroupItem value="full">{t("fullStrategy")}</ToggleGroupItem>
          </ToggleGroup>}>
            <p className="m-0 text-sm text-muted-foreground">{period === "tracking" ? t("trackingDescription") : t("fullDescription", { date: track.origin.strategy_session })}</p>
            <div hidden={period !== "tracking"}>
              <TrackingReturnChart observation={track.observation} originSession={track.origin.strategy_session} />
              <div className="mt-3 flex flex-wrap justify-between gap-2 text-xs text-muted-foreground"><span>{t("sessionsObserved", { count: track.observation.session_count })}</span><span>{t("trackingCosts", { cost: formatMoney(track.observation.transaction_cost_cny) })}</span></div>
            </div>
            <div hidden={period !== "full"}><DailyTrackAnalysisView analysis={{ strategy: track.strategy }} /></div>
          </Section>
        </TabsContent>
        <TabsContent keepMounted value="holdings"><CurrentHoldings observation={track.observation} /></TabsContent>
        <TabsContent keepMounted value="rebalance"><SelectionSchedule observation={track.observation} isStopped={track.status === "stopped"} isStopping={track.status === "stopping"} isBehind={track.lag_sessions > 0} /></TabsContent>
      </Tabs>
      <div className="flex min-w-0 flex-col gap-6 border-t border-border pt-6">
        <DailyHoldings key={`holdings:${track.id}`} rerun={{ folderId: "folder_default", source: {
          kind: "daily_track", track_id: track.id, checkpoint_manifest_sha256: track.checkpoint_manifest_sha256, through_session: track.strategy_session,
        } }} endpoint={`/api/daily-tracks/${encodeURIComponent(track.id)}/holdings/query`} />
        <StrategyEvents key={`events:${track.id}`} endpoint={`/api/daily-tracks/${encodeURIComponent(track.id)}/events/query`} />
        <CommonInputObservations key={`${track.id}:${track.strategy_session}`} endpoint={`/api/daily-tracks/${encodeURIComponent(track.id)}/common-input-observations`} />
        <Disclosure title={<>{t("updateDetails")} <span>{trackStatusLabel(track)}</span></>}><TrackingProgressView progress={track.progress} /></Disclosure>
        <Disclosure title={<>{t("originDisclosure")} <span>{track.origin.strategy_session}</span></>}><TrackingOriginView origin={track.origin} /></Disclosure>
      </div>
      </div>
      </div>
    </PageContent></Page>
  );
}
