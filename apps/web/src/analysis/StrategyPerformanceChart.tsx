import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "cn";
import {
  ColorType,
  CrosshairMode,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type LogicalRange,
  type LineData,
  type MouseEventParams,
  type Time,
} from "lightweight-charts";

import { interfaceLocale, useTranslation } from "../i18n";
import { catalogLabel } from "../i18n/catalog";
import { formatNumber, formatPercent, formatSessionDate } from "../i18n/format";
import type { StrategyComparisonCurvePoint } from "./strategyComparison";
import { chartTheme } from "./chartTheme";
import { ToggleGroup, ToggleGroupItem } from "../components/ui/toggle-group";
import { Empty, EmptyDescription } from "../components/ui/empty";

// TradingView Lightweight Charts™
// Copyright (с) 2025 TradingView, Inc. https://www.tradingview.com/

export type StrategyChartPoint = {
  time: string;
  strategy: number;
  benchmark: number;
};

type VisibleRange = "1Y" | "3Y" | "5Y" | "All";

const RANGE_SESSIONS: Record<Exclude<VisibleRange, "All">, number> = {
  "1Y": 252,
  "3Y": 756,
  "5Y": 1260,
};

export function strategyChartPoints(
  curves: StrategyComparisonCurvePoint[],
): StrategyChartPoint[] {
  return curves.map((point) => ({
    time: point.session,
    strategy: point.net_strategy_return,
    benchmark: point.benchmark_relative_return,
  }));
}

export function StrategyPerformanceChart({
  curves,
  variant = "default",
}: {
  curves: StrategyComparisonCurvePoint[];
  variant?: "default" | "result";
}) {
  const { t, i18n } = useTranslation("analysis");
  const benchmark = catalogLabel("benchmarks", "csi300-price-index-open");
  const points = useMemo(() => strategyChartPoints(curves), [curves]);
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const savedRange = useRef<LogicalRange | null>(null);
  const [visibleRange, setVisibleRange] = useState<VisibleRange>("All");
  const [tooltip, setTooltip] = useState<StrategyChartPoint | null>(null);
  const [endLabels, setEndLabels] = useState<{ x: number; strategyY: number; benchmarkY: number } | null>(null);
  const compact = variant === "result";

  useEffect(() => {
    const container = containerRef.current;
    if (container === null || points.length === 0) return;
    const theme = chartTheme(container);
    const chart = createChart(container, {
      width: container.clientWidth,
      height: compact ? 216 : container.clientWidth <= 768 ? 240 : 320,
      autoSize: false,
      layout: {
        background: { type: ColorType.Solid, color: theme.background },
        textColor: theme.text,
        fontFamily: "Inter, Noto Sans SC, -apple-system, BlinkMacSystemFont, sans-serif",
        fontSize: 12,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: theme.grid },
        horzLines: { color: theme.grid },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: {
        visible: !compact,
        borderColor: theme.border,
        scaleMargins: { top: 0.1, bottom: 0.12 },
      },
      leftPriceScale: {
        visible: compact,
        borderVisible: false,
        scaleMargins: { top: 0.1, bottom: 0.12 },
      },
      timeScale: {
        borderColor: theme.border,
        rightOffset: compact ? 0 : 1,
        fixLeftEdge: true,
        fixRightEdge: true,
      },
      handleScroll: true,
      handleScale: true,
      localization: {
        locale: interfaceLocale(),
        priceFormatter: chartPercent,
        timeFormatter: (time: Time) => formatSessionDate(timeLabel(time)),
      },
    });
    chartRef.current = chart;
    const strategySeries = chart.addSeries(LineSeries, {
      color: theme.strategy,
      priceScaleId: compact ? "left" : "right",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const benchmarkSeries = chart.addSeries(LineSeries, {
      color: theme.benchmark,
      priceScaleId: compact ? "left" : "right",
      lineStyle: compact ? LineStyle.Dashed : LineStyle.Solid,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    strategySeries.setData(points.map((point) => ({
      time: point.time as Time,
      value: point.strategy,
    })));
    benchmarkSeries.setData(points.map((point) => ({
      time: point.time as Time,
      value: point.benchmark,
    })));
    strategySeries.createPriceLine({
      price: 0,
      color: theme.zero,
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: false,
      title: "",
    });
    if (savedRange.current) chart.timeScale().setVisibleLogicalRange(savedRange.current);
    else chart.timeScale().fitContent();

    let labelFrame = 0;
    const updateEndLabels = () => {
      if (!compact) return;
      cancelAnimationFrame(labelFrame);
      labelFrame = requestAnimationFrame(() => {
        const last = points[points.length - 1];
        const range = chart.timeScale().getVisibleLogicalRange();
        const x = chart.timeScale().timeToCoordinate(last.time as Time);
        const strategyY = strategySeries.priceToCoordinate(last.strategy);
        const benchmarkY = benchmarkSeries.priceToCoordinate(last.benchmark);
        setEndLabels(range === null || range.to < points.length - 1 || range.from > points.length - 1 || x === null || strategyY === null || benchmarkY === null
          ? null : { x: x + chart.priceScale("left").width(), strategyY, benchmarkY });
      });
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(updateEndLabels);
    updateEndLabels();

    const onCrosshairMove = (event: MouseEventParams<Time>) => {
      if (event.time === undefined) {
        setTooltip(null);
        return;
      }
      const strategy = seriesValue(event.seriesData.get(strategySeries));
      const benchmark = seriesValue(event.seriesData.get(benchmarkSeries));
      if (strategy === null || benchmark === null) {
        setTooltip(null);
        return;
      }
      setTooltip({ time: timeLabel(event.time), strategy, benchmark });
    };
    chart.subscribeCrosshairMove(onCrosshairMove);
    const observer = new ResizeObserver(([entry]) => {
      if (entry === undefined || entry.contentRect.width <= 0) return;
      chart.applyOptions({
        width: Math.floor(entry.contentRect.width),
        height: compact ? 216 : entry.contentRect.width <= 768 ? 240 : 320,
      });
      updateEndLabels();
    });
    observer.observe(container);
    return () => {
      savedRange.current = chart.timeScale().getVisibleLogicalRange();
      observer.disconnect();
      cancelAnimationFrame(labelFrame);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(updateEndLabels);
      chart.unsubscribeCrosshairMove(onCrosshairMove);
      chart.remove();
      chartRef.current = null;
    };
  }, [points, compact]);

  useEffect(() => {
    chartRef.current?.applyOptions({ localization: {
      locale: interfaceLocale(),
      priceFormatter: chartPercent,
      timeFormatter: (time: Time) => formatSessionDate(timeLabel(time)),
    } });
  }, [i18n.language, points]);

  function selectRange(range: VisibleRange): void {
    setVisibleRange(range);
    const chart = chartRef.current;
    if (chart === null) return;
    if (range === "All") {
      chart.timeScale().fitContent();
      return;
    }
    const sessions = RANGE_SESSIONS[range];
    chart.timeScale().setVisibleLogicalRange({
      from: Math.max(0, points.length - sessions),
      to: Math.max(0, points.length - 1),
    });
  }

  if (points.length === 0) {
    return <Empty><EmptyDescription>{t("chart.empty")}</EmptyDescription></Empty>;
  }
  const ranges = <ToggleGroup value={[visibleRange]} onValueChange={values => { if (values[0]) selectRange(values[0] as VisibleRange); }} aria-label={t("chart.range")} className="ml-auto" variant={compact ? "chart" : "outline"}>
    {(["1Y", "3Y", "5Y", "All"] as const).map(range => <ToggleGroupItem key={range} value={range}>{t(`chart.ranges.${range}`)}</ToggleGroupItem>)}
  </ToggleGroup>;
  const attribution = <a className="shrink-0 text-xs text-muted-foreground underline-offset-4 hover:underline" href="https://www.tradingview.com/" rel="noreferrer" target="_blank">TradingView Lightweight Charts™</a>;
  const last = points[points.length - 1];
  return (
    <figure
      className={cn("strategy-chart m-0 flex min-w-0 flex-col border border-border bg-card p-4", compact ? "gap-1 rounded-md" : "gap-3 rounded-lg")}
      aria-label={t("chart.label", { benchmark })}
    >
      {compact ? <div className="flex min-h-9 items-center justify-between gap-4"><h2 className="m-0 text-xl leading-7 font-semibold">{t("chart.title")}</h2>{ranges}</div> : null}
      <figcaption className={cn("flex flex-wrap items-center gap-4 text-xs text-muted-foreground", compact && "min-h-5 justify-center")}>
        <span><i aria-hidden="true" className="mr-1 inline-block h-0.5 w-4 align-middle bg-chart-1" /> {t("chart.strategy")}</span>
        <span><i aria-hidden="true" className={cn("mr-1 inline-block w-4 align-middle", compact ? "border-t-2 border-dashed border-chart-4" : "h-0.5 bg-chart-4")} /> {benchmark}</span>
        {!compact ? <span className="ml-auto">{t("chart.sessions", { total: formatNumber(points.length) })}</span> : null}
      </figcaption>
      {!compact ? ranges : null}
      <div className={cn("relative isolate min-w-0", compact && "pr-20")}>
        <div className={cn("strategy-chart-canvas relative w-full min-w-0", compact ? "h-[216px]" : "min-h-60")} ref={containerRef} />
        {compact && endLabels ? <div aria-hidden="true" className="pointer-events-none absolute inset-0 z-10 text-xs font-medium whitespace-nowrap tabular-nums">
          <span className="absolute flex -translate-y-1/2 items-center gap-2 text-chart-1" style={{ left: endLabels.x - 3, top: endLabels.strategyY }}><i className="size-1.5 rounded-full bg-chart-1" />{chartPercent(last.strategy)}</span>
          <span className="absolute flex -translate-y-1/2 items-center gap-2 text-[var(--benchmark-foreground)]" style={{ left: endLabels.x - 3, top: endLabels.benchmarkY }}><i className="size-1.5 rounded-full bg-chart-4" />{chartPercent(last.benchmark)}</span>
        </div> : null}
      </div>
      <div className={cn("flex items-center justify-between gap-4", compact && "min-h-5")}>
      <div className={cn("strategy-chart-readout flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground", compact ? "min-h-5 tabular-nums" : "min-h-11 w-full border-t border-border pt-3 font-mono")} aria-live="polite">
        {tooltip === null ? (
          <span>{compact ? t("chart.sessions", { total: formatNumber(points.length) }) : t("chart.inspect")}</span>
        ) : (
          <>
            <time dateTime={tooltip.time}>{formatSessionDate(tooltip.time)}</time>
            <span>{t("chart.strategy")} {chartPercent(tooltip.strategy)}</span>
            <span>{benchmark} {chartPercent(tooltip.benchmark)}</span>
          </>
        )}
      </div>
      </div>
      {!compact ? <div className="flex justify-end">{attribution}</div> : null}
    </figure>
  );
}

function seriesValue(value: unknown): number | null {
  if (typeof value !== "object" || value === null || !("value" in value)) return null;
  const candidate = (value as LineData<Time>).value;
  return Number.isFinite(candidate) ? candidate : null;
}

function timeLabel(time: Time): string {
  if (typeof time === "string") return time;
  if (typeof time === "number") return new Date(time * 1000).toISOString().slice(0, 10);
  return [time.year, String(time.month).padStart(2, "0"), String(time.day).padStart(2, "0")]
    .join("-");
}

function chartPercent(value: number): string {
  return formatPercent(value, { signed: true });
}
