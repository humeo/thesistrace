import { useEffect, useMemo, useRef, useState } from "react";
import {
  ColorType,
  CrosshairMode,
  LineSeries,
  createChart,
  type IChartApi,
  type LineData,
  type MouseEventParams,
  type Time,
} from "lightweight-charts";

// TradingView Lightweight Charts™
// Copyright (с) 2025 TradingView, Inc. https://www.tradingview.com/

export type StrategyChartObservation = {
  session: string;
  net_nav: string;
  benchmark_nav: string;
};

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

const STRATEGY_COLOR = "#828fff";
const BENCHMARK_COLOR = "#777b84";

export function strategyChartPoints(
  observations: StrategyChartObservation[],
): StrategyChartPoint[] {
  const ordered = [...new Map(
    observations
      .filter((item) => /^\d{4}-\d{2}-\d{2}$/.test(item.session))
      .map((item) => [item.session, item] as const),
  ).values()].sort((left, right) => left.session.localeCompare(right.session));
  const origin = ordered.find((item) => {
    const strategy = Number(item.net_nav);
    const benchmark = Number(item.benchmark_nav);
    return Number.isFinite(strategy) && strategy > 0
      && Number.isFinite(benchmark) && benchmark > 0;
  });
  if (origin === undefined) return [];
  const strategyOrigin = Number(origin.net_nav);
  const benchmarkOrigin = Number(origin.benchmark_nav);
  return ordered.flatMap((item) => {
    if (item.session < origin.session) return [];
    const strategy = Number(item.net_nav);
    const benchmark = Number(item.benchmark_nav);
    if (
      !Number.isFinite(strategy)
      || strategy <= 0
      || !Number.isFinite(benchmark)
      || benchmark <= 0
    ) return [];
    return [{
      time: item.session,
      strategy: ((strategy / strategyOrigin) - 1) * 100,
      benchmark: ((benchmark / benchmarkOrigin) - 1) * 100,
    }];
  });
}

export function StrategyPerformanceChart({
  observations,
}: {
  observations: StrategyChartObservation[];
}) {
  const points = useMemo(() => strategyChartPoints(observations), [observations]);
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
        priceFormatter: (value: number) => `${value.toFixed(2)}%`,
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
      if (strategy === null || benchmark === null) {
        setTooltip(null);
        return;
      }
      setTooltip({ time: timeLabel(event.time), strategy, benchmark });
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
    return <p className="strategy-chart-empty">No strategy observations.</p>;
  }
  return (
    <figure className="strategy-chart" aria-label="Strategy performance chart">
      <figcaption>
        <span><i className="strategy-swatch" /> Net strategy</span>
        <span><i className="benchmark-swatch" /> Selected-universe benchmark</span>
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
            <span>Strategy {formatPercent(tooltip.strategy)}</span>
            <span>Benchmark {formatPercent(tooltip.benchmark)}</span>
            <span>Excess {formatPercent(tooltip.strategy - tooltip.benchmark)}</span>
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
  return `${sign}${value.toFixed(2)}%`;
}
