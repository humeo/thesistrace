import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ColorType, LineSeries, createChart, type IChartApi, type ISeriesApi, type LogicalRange, type Time } from "lightweight-charts";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { dailyTrackDetailOptions, dailyTrackKeys } from "./queries";
import { coreFetch } from "../auth/coreFetch";
import { followCoreLink } from "../shell/navigation";
import { chartTheme } from "../analysis/chartTheme";
import { interfaceLocale } from "../i18n";
import { formatNumber } from "../i18n/format";
import { Section } from "../components/layout/Page";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Empty, EmptyHeader, EmptyTitle, EmptyDescription } from "../components/ui/empty";
import { ToggleGroup, ToggleGroupItem } from "../components/ui/toggle-group";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { AccountAllocation, HoldingsPreview } from "./DailyTrackPresentation";
import { formatMoney, formatReturn } from "./DailyTrackObservationView";
import { trackStatusLabel } from "./DailyTrackWorkspace";
import type { DailyTrackDetail, DailyTrackListItem } from "./DailyTracksPage";

type ComparisonValues = {
  status: DailyTrackDetail["status"];
  phase: DailyTrackDetail["progress"]["phase"];
  strategy_session: string;
  observation: Pick<DailyTrackDetail["observation"], "session" | "net_asset_value_cny" | "net_return" | "maximum_drawdown" | "session_count" | "returns">;
  strategy: { entry_session: string | null; net_return: number | null; maximum_drawdown: number | null;
    returns: DailyTrackDetail["observation"]["returns"] };
};
type LoadedTrack = { values: ComparisonValues | null; failed: boolean };
type Curve = { id: string; name: string; points: { session: string; value: number }[] };

export function DailyTrackComparison({ items }: { items: readonly DailyTrackListItem[] }) {
  const { t } = useTranslation("daily");
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [period, setPeriod] = useState<"tracking" | "full">("tracking");
  const queryKey = dailyTrackKeys.comparison(items.map(item => item.id));
  const comparisonQuery = useQuery({
    queryKey,
    queryFn: async ({ signal }): Promise<Record<string, LoadedTrack>> => {
      const params = new URLSearchParams(items.map(item => ["track_id", item.id]));
      const response = await coreFetch(`/api/daily-tracks/comparison?${params}`, { signal });
      if (!response.ok) throw new Error("Track comparison unavailable");
      const result = await response.json() as { items: { id: string; values: ComparisonValues | null }[] };
      const previous = queryClient.getQueryData<Record<string, LoadedTrack>>(queryKey);
      return Object.fromEntries(result.items.map(item => [item.id, {
        values: item.values ?? previous?.[item.id]?.values ?? null, failed: item.values === null,
      }]));
    },
    enabled: items.length > 0,
    staleTime: 0,
  });
  const loaded = comparisonQuery.data ?? {};
  const name = (item: DailyTrackListItem) => item.seed_name ?? `${t("trackHeading")} ${item.id.replace(/^track_/, "").slice(0, 6)}`;
  const activeId = items.some(item => item.id === selected) ? selected! : items[0]?.id;
  const activeQuery = useQuery(dailyTrackDetailOptions(activeId));
  const active = activeQuery.data;
  const curves: Curve[] = items.flatMap(item => {
    const values = loaded[item.id]?.values;
    if (!values || loaded[item.id].failed || comparisonQuery.isError) return [];
    const points = period === "tracking" ? values.observation.returns : values.strategy.returns;
    return [{ id: item.id, name: name(item), points: points.map(point => ({ session: point.session, value: point.net_return })) }];
  });
  return <div className="grid min-w-0 gap-8">
    <Section title={t("comparePerformance")} actions={<ToggleGroup variant="chart" value={[period]} onValueChange={values => { if (values[0]) setPeriod(values[0] as typeof period); }} aria-label={t("period")}><ToggleGroupItem value="tracking">{t("sinceTracking")}</ToggleGroupItem><ToggleGroupItem value="full">{t("fullStrategy")}</ToggleGroupItem></ToggleGroup>}>
      <p className="m-0 text-sm text-muted-foreground">{t(period === "tracking" ? "compareTracking" : "compareFull")}</p>
      <ComparisonChart curves={curves} period={period} loading={comparisonQuery.isPending} />
    </Section>
    <section aria-label={t("list")} className="grid min-w-0 gap-4">
      <h2 className="m-0 text-xl leading-7 font-semibold">{t("allTracks")} <span className="text-muted-foreground">{formatNumber(items.length)}</span></h2>
      <Table scrollLabel={t("comparisonTable")} className="min-w-[800px] tabular-nums [&_td:not(:first-child)]:text-right [&_th:not(:first-child)]:text-right">
        <TableHeader><TableRow><TableHead>{t("trackColumn")}</TableHead><TableHead>{t("status")}</TableHead><TableHead>{t("periodReturn")}</TableHead><TableHead>{t("maximumDrawdown")}</TableHead><TableHead>{t("nav")}</TableHead><TableHead><span className="sr-only">{t("openTrack")}</span></TableHead></TableRow></TableHeader>
        <TableBody>{items.map(item => {
          const row = loaded[item.id]; const detail = row?.values;
          const failed = comparisonQuery.isError || row?.failed;
          const returnValue = period === "tracking" ? detail?.observation.net_return : detail?.strategy.net_return;
          const drawdown = period === "tracking" ? detail?.observation.maximum_drawdown : detail?.strategy.maximum_drawdown;
          return <TableRow key={item.id} data-state={activeId === item.id ? "selected" : undefined}>
            <TableHead scope="row"><Button variant="ghost" className="h-auto min-h-11 max-w-72 justify-start whitespace-normal text-left" aria-pressed={activeId === item.id} onClick={() => setSelected(item.id)}>{name(item)}</Button><p className="m-0 text-xs text-muted-foreground">{period === "tracking" ? item.origin_session : detail?.strategy.entry_session ?? "—"} → {detail?.strategy_session ?? item.strategy_session}{detail && <> · {t("trackedSessions", { count: detail.observation.session_count })}</>}</p>{failed && <p role="status" className="m-0 text-xs text-destructive">{t(detail ? "rowStale" : "rowUnavailable")}</p>}</TableHead>
            <TableCell><Badge variant={item.status === "blocked" ? "destructive" : "secondary"}>{detail ? trackStatusLabel({ status: detail.status, progress: { phase: detail.phase } }) : t(`statuses.${item.status}`)}</Badge></TableCell>
            <TableCell>{returnValue == null ? "—" : formatReturn(returnValue)}</TableCell><TableCell>{drawdown == null ? "—" : formatReturn(drawdown)}</TableCell>
            <TableCell>{detail ? formatMoney(detail.observation.net_asset_value_cny) : "—"}</TableCell>
            <TableCell><Button variant="link" nativeButton={false} role="link" render={<a href={`/daily-tracks/${encodeURIComponent(item.id)}`} onClick={followCoreLink} />} aria-label={item.id}>{t("openTrack")}</Button></TableCell>
          </TableRow>;
        })}</TableBody>
      </Table>
    </section>
    {active ? <Section title={name(items.find(item => item.id === activeId)!)} actions={<Button variant="outline" nativeButton={false} role="link" render={<a href={`/daily-tracks/${encodeURIComponent(activeId)}`} onClick={followCoreLink} />}>{t("openTrack")}</Button>}>
      {activeQuery.isError && <p role="status" className="m-0 text-sm text-destructive">{t("rowStale")}</p>}
      <div className="grid grid-cols-[minmax(0,1fr)_248px] gap-8"><HoldingsPreview observation={active.observation} /><aside className="min-w-0 border-l border-border pl-6"><AccountAllocation observation={active.observation} /></aside></div>
    </Section> : <p role="status" className="m-0 text-sm text-muted-foreground">{t(activeQuery.isError ? "rowUnavailable" : "loading")}</p>}
  </div>;
}

function ComparisonChart({ curves, period, loading }: { curves: Curve[]; period: "tracking" | "full"; loading: boolean }) {
  const { t, i18n } = useTranslation("daily");
  const container = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const lines = useRef(new Map<string, { line: ISeriesApi<"Line">; points: Curve["points"] }>());
  const visibleRange = useRef<LogicalRange | null>(null);
  const fittedPeriod = useRef<typeof period | null>(null);
  const [chartReady, setChartReady] = useState(false);
  const [hidden, setHidden] = useState<string[]>([]);
  const [selected, setSelected] = useState<{ time: string; values: { id: string; value: number }[] } | null>(null);
  const plotted = curves.filter(curve => curve.points.length >= 2 && !hidden.includes(curve.id));
  const allHidden = plotted.length === 0 && curves.some(curve => curve.points.length >= 2);
  const hasData = curves.some(curve => curve.points.length >= 2);
  useEffect(() => { if (hasData) setChartReady(true); }, [hasData]);
  useEffect(() => {
    if (!chartReady || !container.current) return;
    const theme = chartTheme(container.current);
    const chart = createChart(container.current, { autoSize: true, height: 280, layout: { background: { type: ColorType.Solid, color: theme.background }, textColor: theme.text, attributionLogo: false }, grid: { vertLines: { color: theme.grid }, horzLines: { color: theme.grid } }, rightPriceScale: { borderColor: theme.border }, timeScale: { borderColor: theme.border }, localization: { locale: interfaceLocale(), priceFormatter: (value: number) => formatReturn(value) } });
    chartRef.current = chart;
    chart.timeScale().subscribeVisibleLogicalRangeChange(range => {
      if (range) visibleRange.current = range;
    });
    chart.subscribeCrosshairMove(event => {
      if (!event.time) { setSelected(null); return; }
      const values = [...lines.current].flatMap(([id, { line }]) => {
        if (!line.options().visible) return [];
        const row = event.seriesData.get(line);
        return row && "value" in row ? [{ id, value: row.value }] : [];
      });
      setSelected({ time: String(event.time), values });
    });
    return () => { chart.remove(); chartRef.current = null; lines.current.clear(); visibleRange.current = null; fittedPeriod.current = null; };
  }, [chartReady]);
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !container.current) return;
    const range = chart.timeScale().getVisibleLogicalRange() ?? visibleRange.current;
    const valid = curves.filter(curve => curve.points.length >= 2);
    for (const [id, entry] of lines.current) {
      if (!valid.some(curve => curve.id === id)) { chart.removeSeries(entry.line); lines.current.delete(id); }
    }
    const styles = getComputedStyle(container.current);
    const colors = Array.from({ length: 5 }, (_, index) => styles.getPropertyValue(`--chart-${index + 1}`).trim());
    for (const curve of valid) {
      let entry = lines.current.get(curve.id);
      if (!entry) {
        entry = { line: chart.addSeries(LineSeries, { lineWidth: 2, priceLineVisible: false, lastValueVisible: false }), points: [] };
        lines.current.set(curve.id, entry);
      }
      entry.line.applyOptions({ visible: !hidden.includes(curve.id), color: colors[curves.indexOf(curve) % colors.length] });
      const previous = entry.points;
      const same = (point: Curve["points"][number], index: number) => point.session === curve.points[index]?.session && point.value === curve.points[index]?.value;
      if (previous.length !== curve.points.length || !previous.every(same)) {
        // Append or revise the latest observation through the library's update API.
        // A changed period or retained window replaces this series' data in place.
        const appending = previous.length > 0 && curve.points.length >= previous.length
          && previous.slice(0, -1).every(same) && previous.at(-1)!.session === curve.points[previous.length - 1].session;
        if (appending) for (const point of curve.points.slice(previous.length - 1)) entry.line.update({ time: point.session as Time, value: point.value });
        else entry.line.setData(curve.points.map(point => ({ time: point.session as Time, value: point.value })));
        entry.points = curve.points;
      }
    }
    if (valid.some(curve => !hidden.includes(curve.id))) {
      if (fittedPeriod.current !== period) { chart.timeScale().fitContent(); fittedPeriod.current = period; }
      else if (range) chart.timeScale().setVisibleLogicalRange(range);
    }
    setSelected(null);
  }, [curves, hidden, period, chartReady]);
  useEffect(() => {
    chartRef.current?.applyOptions({ localization: {
      locale: interfaceLocale(), priceFormatter: (value: number) => formatReturn(value),
    } });
  }, [i18n.language, chartReady]);
  const readout = selected ? `${selected.time} · ${selected.values.map(({ id, value }) =>
    `${curves.find(curve => curve.id === id)?.name} ${formatReturn(value)}`).join(" · ")}` : t("comparisonHint");
  return <figure aria-label={t("comparisonChart")} className="m-0 grid min-w-0 gap-4">
    <div className="relative h-[280px] min-w-0">
      <div ref={container} aria-hidden={!plotted.length} style={{ visibility: plotted.length ? "visible" : "hidden" }} className="h-full min-w-0 overflow-hidden" />
      {!plotted.length && <Empty className="absolute inset-0"><EmptyHeader><EmptyTitle>{t(allHidden ? "curvesHidden" : "compareEmpty")}</EmptyTitle><EmptyDescription>{t(allHidden ? "showCurves" : loading ? "compareLoading" : "compareEmptyDescription")}</EmptyDescription></EmptyHeader></Empty>}
    </div>
    <ToggleGroup variant="chart" multiple value={curves.filter(curve => !hidden.includes(curve.id)).map(curve => curve.id)} onValueChange={values => setHidden(curves.filter(curve => !values.includes(curve.id)).map(curve => curve.id))} aria-label={t("visibleStrategies")} className="flex-wrap justify-start">
      {curves.map((curve, index) => <ToggleGroupItem key={curve.id} value={curve.id}><span aria-hidden="true" className="size-2 rounded-full" style={{ background: `var(--chart-${index % 5 + 1})` }} />{curve.name}</ToggleGroupItem>)}
    </ToggleGroup>
    <p aria-live="polite" className="m-0 min-h-5 text-xs text-muted-foreground">{readout}</p>
  </figure>;
}
