import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { coreFetch } from "../auth/coreFetch";
import type { DailyTrackDetail } from "./DailyTracksPage";
import { formatMoney, formatReturn } from "./DailyTrackObservationView";
import { HoldingsPreview } from "./DailyTrackPresentation";
import { Metric, MetricGroup } from "../components/product/MetricGroup";
import { Section } from "../components/layout/Page";
import { Button } from "../components/ui/button";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Empty, EmptyDescription } from "../components/ui/empty";
import { ToggleGroup, ToggleGroupItem } from "../components/ui/toggle-group";
import { StrategyEventTable, eventSectionLabel, type EventRow, type EventSection, type EventScope } from "../analysis/StrategyEventDetails";
import { StrategyEvents } from "../analysis/StrategyEvents";
import { DailyHoldings } from "../analysis/DailyHoldings";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "../components/ui/sheet";

type EventPage = { status: "recorded" | "not_recorded" | "expired" | "partially_expired"; rows: EventRow[]; next_cursor: string | null };
type EventQuery = { section: EventSection; filters?: { target_id?: string; order_id?: string; child_order_id?: string }; scope?: EventScope };
const sections = ["strategy_fills", "strategy_targets", "strategy_adjustments"] as const;

export function DailyTrackReview({ track }: { track: DailyTrackDetail }) {
  const { t } = useTranslation("daily");
  const points = track.observation.returns.length ? track.observation.returns : [{ session: track.origin.strategy_session, net_return: 0 }];
  const [selected, setSelected] = useState(track.strategy_session);
  const session = points.some(point => point.session === selected) ? selected : points.at(-1)!.session;
  const index = points.findIndex(point => point.session === session);
  const point = points[index];
  const previous = points[index - 1];
  const atOrigin = session === track.origin.strategy_session;
  const latest = session === track.strategy_session;
  const dailyReturn = !atOrigin && previous ? (1 + point.net_return) / (1 + previous.net_return) - 1 : null;
  const nav = latest ? Number(track.observation.net_asset_value_cny) : Number(track.origin.terminal_account.net_nav) * (1 + point.net_return);
  const [section, setSection] = useState<EventSection>("strategy_fills");
  const [page, setPage] = useState<EventPage | null>(null);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);
  const [query, setQuery] = useState<EventQuery | null>(null);
  const [holdingsOpen, setHoldingsOpen] = useState(false);
  useEffect(() => {
    setPage(null); setError(false);
    if (atOrigin) return;
    const controller = new AbortController();
    void coreFetch(`/api/daily-tracks/${encodeURIComponent(track.id)}/events/query`, {
      method: "POST", signal: controller.signal, headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section, start_session: session, end_session: session, cursor: null, limit: 20 }),
    }).then(async response => {
      if (!response.ok) throw new Error("Daily events unavailable");
      const result = await response.json() as EventPage;
      if (!controller.signal.aborted) setPage(result);
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [track.id, track.strategy_session, session, atOrigin, section, revision]);
  return <div className="grid min-w-0 grid-cols-[164px_minmax(0,1fr)] gap-8">
    <nav aria-label={t("reviewDates")} className="flex max-h-[620px] flex-col gap-1 overflow-y-auto border-r border-border pr-4">
      <h3 className="m-0 mb-3 text-sm font-medium text-muted-foreground">{t("reviewDates")}</h3>
      {[...points].reverse().map(row => <Button key={row.session} variant={session === row.session ? "secondary" : "ghost"} className="h-auto min-h-12 justify-between gap-2" aria-current={session === row.session ? "date" : undefined} onClick={() => setSelected(row.session)}>
        <time>{row.session}</time>{row.session === track.origin.strategy_session && <span className="sr-only">{t("trackingFrom")}</span>}
      </Button>)}
    </nav>
    <div className="grid min-w-0 gap-8">
      <Section title={<time>{session}</time>} actions={<Button variant="outline" onClick={() => setHoldingsOpen(true)}>{t("historicalHoldings")}</Button>}>
        <p className="m-0 text-sm text-muted-foreground">{t(atOrigin ? "originReview" : "publishedReview")}</p>
        <MetricGroup label={t("dailyResult")} variant="observation" className="grid-cols-3">
          <Metric variant="observation" label={t("sessionReturn")} value={dailyReturn === null ? "—" : formatReturn(dailyReturn)} detail={atOrigin ? t("trackingFrom") : !previous ? t("previousUnavailable") : undefined} />
          <Metric variant="observation" label={t("returnSince")} value={formatReturn(point.net_return)} />
          <Metric variant="observation" label={t("nav")} value={formatMoney(nav)} detail={t(latest ? "simulatedCny" : "derivedNav")} />
        </MetricGroup>
      </Section>
      <Section title={t("sessionEvents")} actions={<Button variant="ghost" onClick={() => setQuery({ section })}>{t("allEvents")}</Button>}>
        <ToggleGroup variant="chart" value={[section]} onValueChange={values => { if (values[0]) setSection(values[0] as EventSection); }} aria-label={t("eventType")}>
          {sections.map(value => <ToggleGroupItem key={value} value={value}>{eventSectionLabel(value)}</ToggleGroupItem>)}
        </ToggleGroup>
        {atOrigin ? <Empty><EmptyDescription>{t("originEvents")}</EmptyDescription></Empty> : error ? <Alert variant="destructive"><AlertDescription>{t("eventsFailed")}<Button variant="outline" onClick={() => setRevision(value => value + 1)}>{t("retry")}</Button></AlertDescription></Alert>
          : page === null ? <p role="status">{t("eventsLoading")}</p>
          : page.status === "expired" || page.status === "not_recorded" ? <Empty><EmptyDescription>{t(page.status === "expired" ? "eventsExpired" : "eventsNotRecorded")}</EmptyDescription></Empty>
          : <>{page.status === "partially_expired" && <Alert><AlertDescription>{t("eventsPartial")}</AlertDescription></Alert>}
            {page.rows.length === 0 ? <Empty><EmptyDescription>{t("noSessionEvents")}</EmptyDescription></Empty> : <StrategyEventTable section={section} rows={page.rows} navigate={(next, filters, scope) => setQuery({ section: next, filters, scope })} />}
            {page.next_cursor && <Button variant="outline" className="justify-self-start" onClick={() => setQuery({ section })}>{t("moreEvents")}</Button>}
          </>}
      </Section>
      {latest && <Section title={t("holdings")}><HoldingsPreview observation={track.observation} /></Section>}
    </div>
    <Sheet open={query !== null} onOpenChange={open => { if (!open) setQuery(null); }}><SheetContent className="overflow-y-auto data-[side=right]:sm:max-w-4xl"><SheetHeader><SheetTitle>{t("allEvents")}</SheetTitle></SheetHeader>
      {query && <div className="p-6 pt-0"><StrategyEvents key={JSON.stringify(query)} embedded initialQuery={query} endpoint={`/api/daily-tracks/${encodeURIComponent(track.id)}/events/query`} /></div>}
    </SheetContent></Sheet>
    <Sheet open={holdingsOpen} onOpenChange={setHoldingsOpen}><SheetContent className="overflow-y-auto data-[side=right]:sm:max-w-4xl"><SheetHeader><SheetTitle>{t("historicalHoldings")}</SheetTitle></SheetHeader><div className="p-6 pt-0">
      {holdingsOpen && <DailyHoldings embedded endpoint={`/api/daily-tracks/${encodeURIComponent(track.id)}/holdings/query`} rerun={{ folderId: "folder_default", source: { kind: "daily_track", track_id: track.id, checkpoint_manifest_sha256: track.checkpoint_manifest_sha256, through_session: track.strategy_session } }} />}
    </div></SheetContent></Sheet>
  </div>;
}
