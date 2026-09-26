import { useEffect, useMemo, useRef, useState } from "react";
import {
  ColorType,
  CrosshairMode,
  LineSeries,
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
}: {
  curves: StrategyComparisonCurvePoint[];
}) {
  const { t, i18n } = useTranslation("analysis");
  const benchmark = catalogLabel("benchmarks", "csi300-price-index-open");
  const points = useMemo(() => strategyChartPoints(curves), [curves]);
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const savedRange = useRef<LogicalRange | null>(null);
  const [visibleRange, setVisibleRange] = useState<VisibleRange>("All");
  const [tooltip, setTooltip] = useState<StrategyChartPoint | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (container === null || points.length === 0) return;
    const theme = chartTheme(container);
    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientWidth <= 768 ? 240 : 320,
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
        borderColor: theme.border,
        scaleMargins: { top: 0.1, bottom: 0.12 },
      },
      timeScale: {
        borderColor: theme.border,
        rightOffset: 1,
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
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const benchmarkSeries = chart.addSeries(LineSeries, {
      color: theme.benchmark,
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
        height: entry.contentRect.width <= 768 ? 240 : 320,
      });
    });
    observer.observe(container);
    return () => {
      savedRange.current = chart.timeScale().getVisibleLogicalRange();
      observer.disconnect();
      chart.unsubscribeCrosshairMove(onCrosshairMove);
      chart.remove();
      chartRef.current = null;
    };
  }, [points]);

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
  return (
    <figure
      className="strategy-chart m-0 flex min-w-0 flex-col gap-3 rounded-lg border border-border bg-card p-4"
      aria-label={t("chart.label", { benchmark })}
    >
      <figcaption className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
        <span><i aria-hidden="true" className="mr-1 inline-block h-0.5 w-4 align-middle bg-chart-1" /> {t("chart.strategy")}</span>
        <span><i aria-hidden="true" className="mr-1 inline-block h-0.5 w-4 align-middle bg-chart-4" /> {benchmark}</span>
        <span className="ml-auto">{t("chart.sessions", { total: formatNumber(points.length) })}</span>
      </figcaption>
      <ToggleGroup value={[visibleRange]} onValueChange={values => { if (values[0]) selectRange(values[0] as VisibleRange); }} aria-label={t("chart.range")} className="ml-auto" variant="outline">
        {(["1Y", "3Y", "5Y", "All"] as const).map(range => <ToggleGroupItem key={range} value={range}>{t(`chart.ranges.${range}`)}</ToggleGroupItem>)}
      </ToggleGroup>
      <div className="strategy-chart-canvas relative min-h-60 w-full min-w-0" ref={containerRef} />
      <div className="strategy-chart-readout flex min-h-11 flex-wrap items-center gap-x-4 gap-y-2 border-t border-border pt-3 font-mono text-xs text-muted-foreground" aria-live="polite">
        {tooltip === null ? (
          <span>{t("chart.inspect")}</span>
        ) : (
          <>
            <time dateTime={tooltip.time}>{formatSessionDate(tooltip.time)}</time>
            <span>{t("chart.strategy")} {chartPercent(tooltip.strategy)}</span>
            <span>{benchmark} {chartPercent(tooltip.benchmark)}</span>
          </>
        )}
      </div>
      <div className="flex justify-end">
        <a
          className="text-xs text-muted-foreground underline-offset-4 hover:underline"
          href="https://www.tradingview.com/"
          rel="noreferrer"
          target="_blank"
        >
          TradingView Lightweight Charts™
        </a>
      </div>
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
