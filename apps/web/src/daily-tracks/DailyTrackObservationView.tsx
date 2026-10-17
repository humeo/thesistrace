import { InfoHelp } from "../components/product/InfoHelp";
import { Metric, MetricGroup } from "../components/product/MetricGroup";
import { Section } from "../components/layout/Page";
import { Input } from "../components/ui/input";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell, TableFooter } from "../components/ui/table";
import { Empty, EmptyHeader, EmptyTitle, EmptyDescription } from "../components/ui/empty";
import { chartTheme } from "../analysis/chartTheme";
import { useTranslation } from "react-i18next";
import { interfaceLocale } from "../i18n";
import { formatCurrency, formatNumber, formatSessionDate } from "../i18n/format";
import { SelectionEligibilityView } from "../research/SelectionEligibility";
import { CloseRiskFacts, type CloseRiskPosition } from "../analysis/CloseRiskFacts";
import { isBuiltinFrameworkState, strategySelection, type StrategyDecisionState } from "../research/strategyDecisionState";
import { FrameworkStateView } from "../research/FrameworkStateView";
import { useEffect, useRef, useState } from "react";
import { ColorType, LineSeries, createChart, type Time, type IChartApi, type LogicalRange } from "lightweight-charts";

export type DailyTrackObservation = {
  decision_state: StrategyDecisionState;
  session: string;
  net_asset_value_cny: string;
  close_risk_nav_cny: string;
  cash_cny: string;
  net_change_cny: string;
  net_return: number;
  maximum_drawdown: number;
  transaction_cost_cny: string;
  session_count: number;
  holdings: Array<Omit<CloseRiskPosition, "execution_shares"> & {
    shares: number; market_value_cny: string; weight: number;
  }>;
  selection_interval: number | null;
  pending_target_session: string | null;
  sessions_until_next_signal: number | null;
  returns: Array<{ session: string; net_return: number }>;
};

export function formatMoney(value: string | number) { return formatCurrency(Number(value)); }

export function formatReturn(value: number) { return formatNumber(value, { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 }); }

export function ObservationSummary({ observation, originSession }: {
  observation: DailyTrackObservation; originSession: string;
}) {
  const { t } = useTranslation("daily");
  return (
    <MetricGroup variant="observation" label={t("account")} className="grid-cols-4">
      <Metric variant="observation" label={t("returnSince")} value={formatReturn(observation.net_return)} help={<InfoHelp label={t("returnSince")}>{t("sinceDate", { date: originSession })}</InfoHelp>} />
      <Metric variant="observation" label={t("maximumDrawdown")} value={formatReturn(observation.maximum_drawdown)} help={<InfoHelp label={t("maximumDrawdown")}>{t("sinceDate", { date: originSession })}</InfoHelp>} />
      <Metric variant="observation" label={t("nav")} value={formatMoney(observation.net_asset_value_cny)} help={<InfoHelp label={t("nav")}>{t("changeSince", { amount: formatMoney(observation.net_change_cny) })}</InfoHelp>} />
      <Metric variant="observation" label={t("observedSessions")} value={formatNumber(observation.session_count)} help={<InfoHelp label={t("observedSessions")}>{t("sinceDate", { date: originSession })}</InfoHelp>} />
    </MetricGroup>
  );
}

export function CurrentHoldings({ observation }: { observation: DailyTrackObservation }) {
  const { t } = useTranslation("daily");
  const [query, setQuery] = useState("");
  const holdings = observation.holdings.filter((item) => item.instrument_id.toLowerCase().includes(query.toLowerCase()));
  const selection = strategySelection(observation.decision_state);
  return (
    <section className="flex min-w-0 flex-col gap-4" aria-label={t("holdings") }>
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div><h2 className="m-0 text-base font-semibold">{t("holdings")}</h2><p>{isBuiltinFrameworkState(observation.decision_state)
          ? t("holdingsDescription", { date: observation.session, target: formatReturn(observation.decision_state.exposure), actual: formatReturn(1 - Number(observation.cash_cny) / Number(observation.net_asset_value_cny)) })
          : t("holdingsDescriptionWithoutTarget", { date: observation.session, actual: formatReturn(1 - Number(observation.cash_cny) / Number(observation.net_asset_value_cny)) })}</p></div>
        <Input className="w-full md:w-60 md:shrink-0" aria-label={t("filterHoldings")} placeholder={t("findSymbol")} type="search"
          value={query} onChange={(event) => setQuery(event.target.value)} />
      </div>
      {selection && <SelectionEligibilityView selection={selection} />}
      <FrameworkStateView state={observation.decision_state} />
      <CloseRiskFacts session={observation.session} nav={observation.close_risk_nav_cny}
        positions={observation.holdings.map(item => ({ ...item, execution_shares: item.shares }))} />
      <Table scrollLabel={t("holdingsTable")} className="min-w-[480px]">
          <TableHeader><TableRow><TableHead scope="col">{t("symbol")} </TableHead><TableHead scope="col">{t("shares")} </TableHead><TableHead scope="col">{t("marketValue")} </TableHead><TableHead scope="col">{t("weight")} </TableHead></TableRow></TableHeader>
          <TableBody>
            {holdings.map((item) => (
              <TableRow key={item.instrument_id}>
                <TableHead scope="row" title={item.instrument_id}>{item.instrument_id.replace(/^equity:/, "")}</TableHead>
                <TableCell>{formatNumber(item.shares)}</TableCell>
                <TableCell>{formatMoney(item.market_value_cny)}</TableCell>
                <TableCell><span className="relative inline-block min-w-16"><span aria-hidden="true" className="absolute -bottom-1 right-0 h-0.5 bg-primary"
                  style={{ width: `${Math.min(100, Math.max(0, item.weight * 100))}%` }} />{formatReturn(item.weight)}</span></TableCell>
              </TableRow>
            ))}
            {holdings.length === 0 ? <TableRow><TableCell colSpan={4} className="py-8 text-center text-muted-foreground">
              {t(query ? "noSymbols" : "cashOnly")}
            </TableCell></TableRow> : null}
          </TableBody>
          <TableFooter><TableRow><TableHead scope="row">{t("cash")} </TableHead><TableCell>—</TableCell><TableCell>{formatMoney(observation.cash_cny)}</TableCell>
            <TableCell>{formatReturn(Number(observation.cash_cny) / Number(observation.net_asset_value_cny))}</TableCell></TableRow></TableFooter>
      </Table>
      <p className="m-0 text-xs text-muted-foreground">{t("holdingsNote")} </p>
    </section>
  );
}

export function SelectionSchedule({ observation, isStopped, isStopping, isBehind }: {
  observation: DailyTrackObservation; isStopped: boolean; isStopping: boolean; isBehind: boolean;
}) {
  const { t } = useTranslation("daily");
  return (
    <Section title={t("schedule")}>
      <p className="m-0 text-sm text-muted-foreground">{t(observation.selection_interval === null ? "scheduleConditionDescription" : "scheduleDescription")}</p>
      <dl className="m-0 grid gap-4 text-sm [&_dt]:text-muted-foreground [&_dd]:m-0">
        <div><dt>{t("frequency")}</dt><dd>{observation.selection_interval === null ? t("conditionDriven") : t("every", { count: observation.selection_interval })}</dd></div>
        <div><dt>{t("lastSignal")}</dt><dd>{observation.pending_target_session ?? t("noSignal")}</dd></div>
        <div><dt>{t("nextStep")}</dt><dd>{isStopped ? t("trackingStopped") : isStopping ? t("trackingStopping") : observation.pending_target_session ? t("nextOpen") : observation.selection_interval === null ? t("nextCondition") : observation.sessions_until_next_signal === null ? "—" : t("nextSignal", { count: observation.sessions_until_next_signal })}</dd></div>
      </dl>
      {isBehind && !isStopped && !isStopping ? <p className="m-0 rounded-lg border border-border bg-muted p-4 text-sm">{t("behindNote")} </p> : null}
      <div className="rounded-lg border border-dashed border-border p-4 text-sm">
        <h3>{t("ordersUnavailable")} </h3>
        <p>{t("ordersDescription")} </p>
      </div>
    </Section>
  );
}

export function TrackingReturnChart({ observation, originSession, height = 216, appearance = "dark" }: {
  observation: Pick<DailyTrackObservation, "returns">; originSession: string; height?: number; appearance?: "light" | "dark";
}) {
  const { t, i18n } = useTranslation("daily");
  const chartRef = useRef<IChartApi | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const visibleRange = useRef<LogicalRange | null>(null);
  const [selected, setSelected] = useState<{ session: string; net_return: number } | null>(null);
  useEffect(() => {
    const element = containerRef.current;
    if (!element || observation.returns.length < 2) return;
    setSelected(null);
    const theme = chartTheme(element);
    const chart = createChart(element, {
      width: element.clientWidth, height,
      layout: { background: { type: ColorType.Solid, color: theme.background }, textColor: theme.text, fontFamily: "Inter, Noto Sans SC, -apple-system, BlinkMacSystemFont, sans-serif", attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: theme.grid } },
      leftPriceScale: { visible: true, borderColor: theme.border },
      rightPriceScale: { visible: false },
      timeScale: { borderColor: theme.border, fixLeftEdge: true, fixRightEdge: true },
      localization: { locale: interfaceLocale(), priceFormatter: formatReturn },
    });
    chartRef.current = chart;
    const series = chart.addSeries(LineSeries, { priceScaleId: "left", color: theme.strategy, lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
    series.setData(observation.returns.map((point) => ({ time: point.session as Time, value: point.net_return })));
    series.createPriceLine({ price: 0, color: theme.zero, lineStyle: 2, lineWidth: 1, axisLabelVisible: false, title: "" });
    if (visibleRange.current) chart.timeScale().setVisibleLogicalRange(visibleRange.current);
    else chart.timeScale().fitContent();
    chart.subscribeCrosshairMove((event) => {
      setSelected(observation.returns.find((point) => point.session === event.time) ?? null);
    });
    const resize = new ResizeObserver(([entry]) => {
      if (entry && entry.contentRect.width > 0) chart.applyOptions({ width: Math.floor(entry.contentRect.width) });
    });
    resize.observe(element);
    return () => { visibleRange.current = chart.timeScale().getVisibleLogicalRange(); chartRef.current = null; resize.disconnect(); chart.remove(); };
  }, [observation.returns, height, appearance]);
  useEffect(() => {
    chartRef.current?.applyOptions({ localization: { locale: interfaceLocale(), priceFormatter: formatReturn } });
  }, [i18n.language, observation.returns]);
  if (observation.returns.length < 2) {
    return <Empty><EmptyHeader><EmptyTitle>{t("chartEmpty")}</EmptyTitle><EmptyDescription>{t("chartEmptyDescription", { date: originSession })}</EmptyDescription></EmptyHeader></Empty>;
  }
  return <figure className="relative m-0 min-w-0 overflow-hidden" aria-label={t("chartTitle") }>
    <figcaption className="sr-only mb-4 flex flex-wrap justify-between gap-2 text-xs text-muted-foreground"><span>{t("netReturnSince", { date: originSession })}</span><span>{t("observations", { count: observation.returns.length })}</span></figcaption>
    <div ref={containerRef} className="min-w-0" style={{ height }} />
    <div aria-live="polite" className="pointer-events-none absolute right-3 top-3 text-xs tabular-nums">
      {selected && <span className="inline-block rounded-md border border-border bg-card px-3 py-2">{formatSessionDate(selected.session)}  {formatReturn(selected.net_return)}</span>}
    </div>
  </figure>;
}
