import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ColorType, LineSeries, createChart, type Time } from "lightweight-charts";
import { coreFetch } from "../auth/coreFetch";
import { chartTheme } from "../analysis/chartTheme";
import { interfaceLocale } from "../i18n";
import { formatNumber } from "../i18n/format";
import { Section } from "../components/layout/Page";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Empty, EmptyHeader, EmptyTitle, EmptyDescription } from "../components/ui/empty";
import { ToggleGroup, ToggleGroupItem } from "../components/ui/toggle-group";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { AccountAllocation, HoldingsPreview, useTrackNames } from "./DailyTrackPresentation";
import { formatMoney, formatReturn } from "./DailyTrackObservationView";
import { trackStatusLabel } from "./DailyTrackWorkspace";
import type { DailyTrackDetail, DailyTrackSummary } from "./DailyTracksPage";

type LoadedTrack = { detail: DailyTrackDetail | null; failed: boolean };
type Curve = { id: string; name: string; points: { session: string; value: number }[] };

export function DailyTrackComparison({ items, revision }: { items: readonly DailyTrackSummary[]; revision: number }) {
  const { t } = useTranslation("daily");
  const [loaded, setLoaded] = useState<Record<string, LoadedTrack>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [period, setPeriod] = useState<"tracking" | "full">("tracking");
  const names = useTrackNames(items.map(item => item.seed_run_id));
  const ids = JSON.stringify(items.map(item => item.id));
  useEffect(() => {
    const controller = new AbortController();
    void Promise.allSettled((JSON.parse(ids) as string[]).map(async id => {
      try {
        const response = await coreFetch(`/api/daily-tracks/${encodeURIComponent(id)}`, { signal: controller.signal });
        if (!response.ok) throw new Error("Track observation unavailable");
        const detail = await response.json() as DailyTrackDetail;
        if (!controller.signal.aborted) setLoaded(value => ({ ...value, [id]: { detail, failed: false } }));
      } catch {
        if (!controller.signal.aborted) setLoaded(value => ({ ...value, [id]: { detail: value[id]?.detail ?? null, failed: true } }));
      }
    }));
    return () => controller.abort();
  }, [ids, revision]);
  const name = (item: DailyTrackSummary) => names[item.seed_run_id] ?? `${t("trackHeading")} ${item.id.replace(/^track_/, "").slice(0, 6)}`;
  const activeId = items.some(item => item.id === selected) ? selected! : items[0]?.id;
  const active = loaded[activeId]?.detail;
  const curves: Curve[] = items.flatMap(item => {
    const detail = loaded[item.id]?.detail;
    if (!detail || loaded[item.id].failed) return [];
    return [{ id: item.id, name: name(item), points: period === "tracking"
      ? detail.observation.returns.map(point => ({ session: point.session, value: point.net_return }))
      : detail.strategy.comparison.status === "available" ? detail.strategy.comparison.curves.map(point => ({ session: point.session, value: point.net_strategy_return })) : [] }];
  });
  return <div className="grid min-w-0 gap-8">
    <Section title={t("comparePerformance")} actions={<ToggleGroup variant="chart" value={[period]} onValueChange={values => { if (values[0]) setPeriod(values[0] as typeof period); }} aria-label={t("period")}><ToggleGroupItem value="tracking">{t("sinceTracking")}</ToggleGroupItem><ToggleGroupItem value="full">{t("fullStrategy")}</ToggleGroupItem></ToggleGroup>}>
      <p className="m-0 text-sm text-muted-foreground">{t(period === "tracking" ? "compareTracking" : "compareFull")}</p>
      <ComparisonChart curves={curves} loading={items.some(item => !loaded[item.id])} />
    </Section>
    <section aria-label={t("list")} className="grid min-w-0 gap-4">
      <h2 className="m-0 text-xl leading-7 font-semibold">{t("allTracks")} <span className="text-muted-foreground">{formatNumber(items.length)}</span></h2>
      <Table scrollLabel={t("comparisonTable")} className="min-w-[800px] tabular-nums [&_td:not(:first-child)]:text-right [&_th:not(:first-child)]:text-right">
        <TableHeader><TableRow><TableHead>{t("trackColumn")}</TableHead><TableHead>{t("status")}</TableHead><TableHead>{t("periodReturn")}</TableHead><TableHead>{t("maximumDrawdown")}</TableHead><TableHead>{t("nav")}</TableHead><TableHead><span className="sr-only">{t("openTrack")}</span></TableHead></TableRow></TableHeader>
        <TableBody>{items.map(item => {
          const row = loaded[item.id]; const detail = row?.detail;
          const metrics = detail?.strategy.summary.metrics;
          const returnValue = period === "tracking" ? detail?.observation.net_return : metrics?.net_cumulative_return;
          const drawdown = period === "tracking" ? detail?.observation.maximum_drawdown : metrics?.maximum_drawdown.value;
          return <TableRow key={item.id} data-state={activeId === item.id ? "selected" : undefined}>
            <TableHead scope="row"><Button variant="ghost" className="h-auto min-h-11 max-w-72 justify-start whitespace-normal text-left" aria-pressed={activeId === item.id} onClick={() => setSelected(item.id)}>{name(item)}</Button><p className="m-0 text-xs text-muted-foreground">{period === "tracking" ? item.origin_session : detail?.strategy.comparison.status === "available" ? detail.strategy.comparison.entry.session : "—"} → {detail?.strategy_session ?? item.strategy_session}{detail && <> · {t("trackedSessions", { count: detail.observation.session_count })}</>}</p>{row?.failed && <p role="status" className="m-0 text-xs text-destructive">{t(detail ? "rowStale" : "rowUnavailable")}</p>}</TableHead>
            <TableCell><Badge variant={item.status === "blocked" ? "destructive" : "secondary"}>{detail ? trackStatusLabel(detail) : t(`statuses.${item.status}`)}</Badge></TableCell>
            <TableCell>{returnValue == null ? "—" : formatReturn(returnValue)}</TableCell><TableCell>{drawdown == null ? "—" : formatReturn(drawdown)}</TableCell>
            <TableCell>{detail ? formatMoney(detail.observation.net_asset_value_cny) : "—"}</TableCell>
            <TableCell><Button variant="link" nativeButton={false} role="link" render={<a href={`/daily-tracks/${encodeURIComponent(item.id)}`} />} aria-label={item.id}>{t("openTrack")}</Button></TableCell>
          </TableRow>;
        })}</TableBody>
      </Table>
    </section>
    {active ? <Section title={name(items.find(item => item.id === activeId)!)} actions={<Button variant="outline" nativeButton={false} role="link" render={<a href={`/daily-tracks/${encodeURIComponent(activeId)}`} />}>{t("openTrack")}</Button>}>
      <div className="grid grid-cols-[minmax(0,1fr)_248px] gap-8"><HoldingsPreview observation={active.observation} /><aside className="min-w-0 border-l border-border pl-6"><AccountAllocation observation={active.observation} /></aside></div>
    </Section> : <p role="status" className="m-0 text-sm text-muted-foreground">{t(loaded[activeId]?.failed ? "rowUnavailable" : "loading")}</p>}
  </div>;
}

function ComparisonChart({ curves, loading }: { curves: Curve[]; loading: boolean }) {
  const { t, i18n } = useTranslation("daily");
  const container = useRef<HTMLDivElement>(null);
  const [hidden, setHidden] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const plotted = curves.filter(curve => curve.points.length >= 2 && !hidden.includes(curve.id));
  const allHidden = plotted.length === 0 && curves.some(curve => curve.points.length >= 2);
  const signature = JSON.stringify(plotted);
  useEffect(() => {
    setSelected(null);
    if (!container.current || !plotted.length) return;
    const theme = chartTheme(container.current);
    const chart = createChart(container.current, { autoSize: true, height: 280, layout: { background: { type: ColorType.Solid, color: theme.background }, textColor: theme.text, attributionLogo: false }, grid: { vertLines: { color: theme.grid }, horzLines: { color: theme.grid } }, rightPriceScale: { borderColor: theme.border }, timeScale: { borderColor: theme.border }, localization: { locale: interfaceLocale(), priceFormatter: (value: number) => formatReturn(value) } });
    const styles = getComputedStyle(container.current);
    const colors = Array.from({ length: 5 }, (_, index) => styles.getPropertyValue(`--chart-${index + 1}`).trim());
    const lines = plotted.map(curve => {
      const colorIndex = curves.findIndex(value => value.id === curve.id);
      const line = chart.addSeries(LineSeries, { color: colors[colorIndex % colors.length], lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
      line.setData(curve.points.map(point => ({ time: point.session as Time, value: point.value })));
      return { line, name: curve.name };
    });
    chart.timeScale().fitContent();
    chart.subscribeCrosshairMove(event => {
      if (!event.time) { setSelected(null); return; }
      const values = lines.flatMap(({ line, name }) => {
        const row = event.seriesData.get(line);
        return row && "value" in row ? [`${name} ${formatReturn(row.value)}`] : [];
      });
      setSelected(`${event.time} · ${values.join(" · ")}`);
    });
    return () => chart.remove();
  // The serialized curves keep the canvas stable across unrelated state updates.
  }, [signature, i18n.language]);
  return <figure aria-label={t("comparisonChart")} className="m-0 grid min-w-0 gap-4">
    {plotted.length ? <div ref={container} className="min-w-0 overflow-hidden" /> : <Empty><EmptyHeader><EmptyTitle>{t(allHidden ? "curvesHidden" : "compareEmpty")}</EmptyTitle><EmptyDescription>{t(allHidden ? "showCurves" : loading ? "compareLoading" : "compareEmptyDescription")}</EmptyDescription></EmptyHeader></Empty>}
    <ToggleGroup variant="chart" multiple value={curves.filter(curve => !hidden.includes(curve.id)).map(curve => curve.id)} onValueChange={values => setHidden(curves.filter(curve => !values.includes(curve.id)).map(curve => curve.id))} aria-label={t("visibleStrategies")} className="flex-wrap justify-start">
      {curves.map((curve, index) => <ToggleGroupItem key={curve.id} value={curve.id}><span aria-hidden="true" className="size-2 rounded-full" style={{ background: `var(--chart-${index % 5 + 1})` }} />{curve.name}</ToggleGroupItem>)}
    </ToggleGroup>
    <p aria-live="polite" className="m-0 min-h-5 text-xs text-muted-foreground">{selected ?? t("comparisonHint")}</p>
  </figure>;
}
