import { useEffect, useState, type ReactNode } from "react";
import { useUrlSelection } from "../shell/useUrlSelection";
import { followCoreLink } from "../shell/navigation";
import { useTranslation } from "react-i18next";
import { CaretDownIcon, WarningCircleIcon } from "@phosphor-icons/react";
import { i18n } from "../i18n";
import { formatNumber } from "../i18n/format";
import { InfoHelp } from "../components/product/InfoHelp";
import { Page, PageContent, PageHeader, Section } from "../components/layout/Page";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "../components/ui/alert";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../components/ui/tabs";
import { ToggleGroup, ToggleGroupItem } from "../components/ui/toggle-group";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuGroup, DropdownMenuLinkItem } from "../components/ui/dropdown-menu";
import { Sheet, SheetTrigger, SheetContent, SheetHeader, SheetTitle } from "../components/ui/sheet";
import { CommonInputObservations } from "../analysis/CommonInputObservations";
import { TrackingOriginView, TrackingProgressView } from "./DailyTrackFacts";
import { DailyTrackAnalysisView } from "./DailyTrackAnalysisView";
import { CurrentHoldings, ObservationSummary, SelectionSchedule, TrackingReturnChart, formatMoney } from "./DailyTrackObservationView";
import { AccountAllocation, HoldingsPreview } from "./DailyTrackPresentation";
import { DailyTrackReview } from "./DailyTrackReview";
import { blockedReason } from "./blockedReason";
import type { DailyTrackDetail, DailyTrackListItem } from "./DailyTracksPage";

const VIEWS = ["performance", "review", "holdings", "rebalance"] as const;
type View = typeof VIEWS[number];

export function trackStatusLabel(track: Pick<DailyTrackDetail, "status"> & { progress: Pick<DailyTrackDetail["progress"], "phase"> }) {
  if (track.status === "blocked") return i18n.t("daily:statusLabels.blocked");
  if (track.status === "stopped") return i18n.t("daily:statusLabels.stopped");
  if (track.status === "stopping") return i18n.t("daily:statusLabels.stopping");
  if (track.progress.phase === "up_to_date") return i18n.t("daily:statusLabels.up_to_date");
  if (track.progress.phase === "waiting") return i18n.t("daily:statusLabels.waiting");
  return i18n.t("daily:statusLabels.updating");
}

export function DailyTrackWorkspace({ track, items, listError = false, onReloadList, actions, notices, reloadAction }: {
  track: DailyTrackDetail; items: readonly DailyTrackListItem[] | null; listError?: boolean; onReloadList?: () => void; actions: ReactNode; notices: ReactNode; reloadAction: ReactNode;
}) {
  const { t } = useTranslation("daily");
  const [view, setView] = useUrlSelection("tab", VIEWS, "performance");
  const [visited, setVisited] = useState<View[]>(["performance", "holdings", "rebalance", view]);
  useEffect(() => { setVisited(values => values.includes(view) ? values : [...values, view]); }, [view]);
  const [period, setPeriod] = useState<"tracking" | "full">("tracking");
  const visibleItems = items?.some(item => item.id === track.id) ? items : [{ id: track.id, seed_name: track.seed_name }, ...(items ?? [])];
  const title = track.seed_name ?? `${t("trackHeading")} ${track.id.replace(/^track_/, "").slice(0, 6)}`;
  return <Page className="console-workspace" aria-label={t("title")}><PageContent className="flex flex-col gap-6">
    <PageHeader variant="console" title={t("title")} className="mb-0" actions={<>
      <Button variant="link" nativeButton={false} role="link" render={<a href="/daily-tracks" onClick={followCoreLink} />}>{t("backToList")}</Button>
      <DropdownMenu><DropdownMenuTrigger render={<Button variant="ghost" />} aria-label={t("switchTrack")}>{t("switchTrack")}<CaretDownIcon data-icon="inline-end" /></DropdownMenuTrigger>
        <DropdownMenuContent className="min-w-72"><DropdownMenuGroup>
          {visibleItems.map(item => <DropdownMenuLinkItem key={item.id} href={`/daily-tracks/${encodeURIComponent(item.id)}`} onClick={followCoreLink} aria-label={item.id} aria-current={item.id === track.id ? "page" : undefined}>{item.seed_name ?? `${t("trackHeading")} ${item.id.replace(/^track_/, "").slice(0, 6)}`}</DropdownMenuLinkItem>)}
        </DropdownMenuGroup></DropdownMenuContent>
      </DropdownMenu>
      {reloadAction}
    </>} />
    {listError && <span role="status" className="text-sm text-muted-foreground">{t("listUnavailable")}<Button variant="link" onClick={onReloadList}>{t("retry")}</Button></span>}
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="grid min-w-0 gap-3"><h2 className="m-0 flex flex-wrap items-center gap-3 text-xl leading-7 font-semibold">{title}<InfoHelp label={t("strategyObservation")}><code>{track.id}</code></InfoHelp><Badge variant={track.status === "blocked" ? "destructive" : "secondary"}>{trackStatusLabel(track)}</Badge></h2>
        <p className="m-0 flex flex-wrap gap-x-5 gap-y-1 text-sm text-muted-foreground"><span>{t("trackingFrom")} <time>{track.origin.strategy_session}</time></span><span>{t("lastObservation")} <time>{track.strategy_session}</time></span><span>{t("dataThrough")} <time>{track.data_through_session}</time></span></p>
      </div><div className="flex flex-wrap gap-2">{actions}</div>
    </header>
    {notices}
    {track.status === "blocked" ? <Alert role="status"><WarningCircleIcon aria-hidden="true" /><AlertTitle>{t("needsUpdate")}</AlertTitle><AlertDescription><p>{blockedReason(track.blocked_code)}</p><p>{t("blockedObservation", { date: track.strategy_session, count: track.lag_sessions })}</p></AlertDescription></Alert>
      : track.lag_sessions > 0 && track.status === "active" && track.progress.phase === "waiting" ? <Alert role="status"><AlertDescription>{t("newSessions", { count: track.lag_sessions })}</AlertDescription></Alert>
      : track.status === "stopped" ? <Alert role="status"><AlertDescription>{t("stoppedNotice")}</AlertDescription></Alert> : null}
    <div className="border-y border-border py-6"><ObservationSummary observation={track.observation} originSession={track.origin.strategy_session} /></div>
    <Tabs value={view} onValueChange={value => { const next = value as View; setView(next); setVisited(values => values.includes(next) ? values : [...values, next]); }} className="min-w-0 gap-8">
      <TabsList variant="line" aria-label={t("viewsTitle")}>
        {VIEWS.map(item => <TabsTrigger size="lg" key={item} value={item}>{t(`views.${item}`)}{item === "holdings" && <Badge variant="secondary">{formatNumber(track.observation.holdings.length)}</Badge>}</TabsTrigger>)}
      </TabsList>
      <TabsContent keepMounted value="performance" className="min-w-0">
        <div className="grid min-w-0 gap-8">
          <Section title={<span className="flex items-center gap-2">{t("performance")}<InfoHelp label={t("performance")}>{period === "tracking" ? t("trackingDescription") : t("fullDescription", { date: track.origin.strategy_session })}</InfoHelp></span>} actions={<ToggleGroup value={[period]} onValueChange={values => { if (values[0]) setPeriod(values[0] as typeof period); }} variant="outline" size="sm" spacing={0} aria-label={t("period")}><ToggleGroupItem value="tracking">{t("sinceTracking")}</ToggleGroupItem><ToggleGroupItem value="full">{t("fullStrategy")}</ToggleGroupItem></ToggleGroup>}>
            <div className="min-w-0" hidden={period !== "tracking"}><TrackingReturnChart observation={track.observation} originSession={track.origin.strategy_session} height={340} /></div>
            <div className="min-w-0" hidden={period !== "full"}><DailyTrackAnalysisView analysis={{ strategy: track.strategy }} /></div>
          </Section>
          <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,1fr)] items-start gap-8 border-t border-border pt-8">
            <AccountAllocation observation={track.observation} />
            <Section title={t("holdings")} actions={<Button variant="ghost" onClick={() => setView("holdings")}>{t("allHoldings")}</Button>}><HoldingsPreview observation={track.observation} /><p className="m-0 text-sm text-muted-foreground">{t("largestHoldings", { count: Math.min(5, track.observation.holdings.length), total: track.observation.holdings.length })}</p></Section>
            <Section className="col-span-2" title={t("recentObservation")} actions={<Button variant="ghost" onClick={() => { setView("review"); setVisited(values => values.includes("review") ? values : [...values, "review"]); }}>{t("views.review")}</Button>}>
              <p className="m-0 text-sm text-muted-foreground">{track.observation.session_count === 0 ? t("originReview") : t("latestReview", { date: track.strategy_session })}</p>
              <dl className="m-0 grid gap-4 text-sm [&_dd]:m-0"><div className="flex justify-between gap-4"><dt>{t("sessionsObserved", { count: track.observation.session_count })}</dt><dd>{trackStatusLabel(track)}</dd></div><div className="flex justify-between gap-4"><dt>{t("changeLabel")}</dt><dd className="tabular-nums">{formatMoney(track.observation.net_change_cny)}</dd></div><div className="flex justify-between gap-4"><dt>{t("transactionCosts")}</dt><dd className="tabular-nums">{formatMoney(track.observation.transaction_cost_cny)}</dd></div></dl>
            </Section>
          </div>
        </div>
      </TabsContent>
      <TabsContent keepMounted value="review">{visited.includes("review") && <DailyTrackReview track={track} />}</TabsContent>
      <TabsContent keepMounted value="holdings"><CurrentHoldings observation={track.observation} /></TabsContent>
      <TabsContent keepMounted value="rebalance"><SelectionSchedule observation={track.observation} isStopped={track.status === "stopped"} isStopping={track.status === "stopping"} isBehind={track.lag_sessions > 0} /></TabsContent>
    </Tabs>
    <footer className="flex flex-wrap gap-2 border-t border-border pt-4">
      <DetailsSheet title={t("sourceDetails")}><TrackingOriginView origin={track.origin} /></DetailsSheet>
      <DetailsSheet title={t("updateDetails")}><TrackingProgressView progress={track.progress} /></DetailsSheet>
      <DetailsSheet title={t("inputDetails")}><CommonInputObservations key={`${track.id}:${track.strategy_session}`} endpoint={`/api/daily-tracks/${encodeURIComponent(track.id)}/common-input-observations`} embedded /></DetailsSheet>
    </footer>
  </PageContent></Page>;
}

function DetailsSheet({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return <Sheet open={open} onOpenChange={setOpen}><SheetTrigger render={<Button variant="ghost" />}>{title}</SheetTrigger><SheetContent className="overflow-y-auto data-[side=right]:sm:max-w-3xl"><SheetHeader><SheetTitle>{title}</SheetTitle></SheetHeader>{open && <div className="p-6 pt-0">{children}</div>}</SheetContent></Sheet>;
}
