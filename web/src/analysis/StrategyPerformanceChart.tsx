import { useEffect, useMemo, useRef, useState } from "react";
import {
  ColorType,
  CrosshairMode,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type LineData,
  type MouseEventParams,
  type Time,
} from "lightweight-charts";

import type { StrategyComparisonCurvePoint } from "./strategyComparison";

// TradingView Lightweight Charts™
// Copyright (с) 2025 TradingView, Inc. https://www.tradingview.com/

export type StrategyChartPoint = {
  time: string;
  strategy: number;
  benchmark: number;
  netExcess: number;
};

type VisibleRange = "1Y" | "3Y" | "5Y" | "All";

const RANGE_SESSIONS: Record<Exclude<VisibleRange, "All">, number> = {
  "1Y": 252,
  "3Y": 756,
  "5Y": 1260,
};

const STRATEGY_COLOR = "#828fff";
const BENCHMARK_COLOR = "#777b84";
const NET_EXCESS_COLOR = "#d0d6e0";

export function strategyChartPoints(
  curves: StrategyComparisonCurvePoint[],
): StrategyChartPoint[] {
  return curves.map((point) => ({
    time: point.session,
    strategy: point.net_strategy_return,
    benchmark: point.benchmark_relative_return,
    netExcess: point.net_excess_return,
  }));
}

export function StrategyPerformanceChart({
  curves,
}: {
  curves: StrategyComparisonCurvePoint[];
}) {
  const points = useMemo(() => strategyChartPoints(curves), [curves]);
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [visibleRange, setVisibleRange] = useState<VisibleRange>("All");
  const [tooltip, setTooltip] = useState<StrategyChartPoint | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (container === null || points.length === 0) return;
    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientWidth <= 768 ? 240 : 320,
      autoSize: false,
      layout: {
        background: { type: ColorType.Solid, color: "#0f1011" },
        textColor: "#8a8f98",
        fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
        fontSize: 11,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: "#18191a" },
        horzLines: { color: "#23252a" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: {
        borderColor: "#34343a",
        scaleMargins: { top: 0.1, bottom: 0.12 },
      },
      timeScale: {
        borderColor: "#34343a",
        rightOffset: 1,
        fixLeftEdge: true,
        fixRightEdge: true,
      },
      handleScroll: true,
      handleScale: true,
      localization: {
        priceFormatter: formatPercent,
      },
    });
    chartRef.current = chart;
    const strategySeries = chart.addSeries(LineSeries, {
      color: STRATEGY_COLOR,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const benchmarkSeries = chart.addSeries(LineSeries, {
      color: BENCHMARK_COLOR,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const netExcessSeries = chart.addSeries(LineSeries, {
      color: NET_EXCESS_COLOR,
      lineStyle: LineStyle.Dashed,
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
    netExcessSeries.setData(points.map((point) => ({
      time: point.time as Time,
      value: point.netExcess,
    })));
    strategySeries.createPriceLine({
      price: 0,
      color: "#62666d",
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: false,
      title: "",
    });
    chart.timeScale().fitContent();

    const onCrosshairMove = (event: MouseEventParams<Time>) => {
      if (event.time === undefined) {
        setTooltip(null);
        return;
      }
      const strategy = seriesValue(event.seriesData.get(strategySeries));
      const benchmark = seriesValue(event.seriesData.get(benchmarkSeries));
      const netExcess = seriesValue(event.seriesData.get(netExcessSeries));
      if (strategy === null || benchmark === null || netExcess === null) {
        setTooltip(null);
        return;
      }
      setTooltip({ time: timeLabel(event.time), strategy, benchmark, netExcess });
    };
    chart.subscribeCrosshairMove(onCrosshairMove);
    const observer = new ResizeObserver(([entry]) => {
      if (entry === undefined) return;
      chart.applyOptions({
        width: Math.floor(entry.contentRect.width),
        height: entry.contentRect.width <= 768 ? 240 : 320,
      });
    });
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.unsubscribeCrosshairMove(onCrosshairMove);
      chart.remove();
      chartRef.current = null;
    };
  }, [points]);

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
    return <p className="strategy-chart-empty">No comparison observations.</p>;
  }
  return (
    <figure
      className="strategy-chart"
      aria-label="Net Strategy, 沪深300, and Net Excess performance chart"
    >
      <figcaption>
        <span><i className="strategy-swatch" /> Net Strategy</span>
        <span><i className="benchmark-swatch" /> 沪深300</span>
        <span><i className="net-excess-swatch" /> Net Excess</span>
        <span className="strategy-chart-session-count">{points.length} Research Sessions</span>
      </figcaption>
      <div className="strategy-chart-toolbar" aria-label="Chart range">
        {(["1Y", "3Y", "5Y", "All"] as const).map((range) => (
          <button
            aria-pressed={visibleRange === range}
            key={range}
            onClick={() => selectRange(range)}
            type="button"
          >
            {range}
          </button>
        ))}
      </div>
      <div className="strategy-chart-canvas" ref={containerRef} />
      <div className="strategy-chart-readout" aria-live="polite">
        {tooltip === null ? (
          <span>Move across the chart to inspect a session.</span>
        ) : (
          <>
            <time dateTime={tooltip.time}>{tooltip.time}</time>
            <span>Net Strategy {formatPercent(tooltip.strategy)}</span>
            <span>沪深300 {formatPercent(tooltip.benchmark)}</span>
            <span>Net Excess {formatPercent(tooltip.netExcess)}</span>
          </>
        )}
      </div>
      <div className="strategy-chart-legal">
        <a
          className="strategy-chart-attribution"
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

function formatPercent(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(2)}%`;
}
