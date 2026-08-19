import { describe, expect, it } from "vitest";

import { strategyChartPoints } from "./StrategyPerformanceChart";

describe("strategyChartPoints", () => {
  it("normalizes a long strategy and benchmark history to exact percentage returns", () => {
    const observations = Array.from({ length: 4_015 }, (_, index) => ({
      session: new Date(Date.UTC(2010, 0, 4 + index)).toISOString().slice(0, 10),
      net_nav: String(10_000_000 + (index * 2_500)),
      benchmark_nav: String(1 + (index / 10_000)),
    }));

    const points = strategyChartPoints(observations);

    expect(points).toHaveLength(4_015);
    expect(points[0]).toEqual({
      time: "2010-01-04",
      strategy: 0,
      benchmark: 0,
    });
    expect(points.at(-1)?.strategy).toBeCloseTo(100.35, 10);
    expect(points.at(-1)?.benchmark).toBeCloseTo(40.14, 10);
    expect(points.every((point) => Number.isFinite(point.strategy))).toBe(true);
    expect(points.every((point) => Number.isFinite(point.benchmark))).toBe(true);
  });

  it("sorts sessions, removes duplicate dates, and excludes invalid NAV rows", () => {
    const points = strategyChartPoints([
      { session: "2026-08-03", net_nav: "100", benchmark_nav: "1" },
      { session: "2026-08-02", net_nav: "50", benchmark_nav: "0.5" },
      { session: "2026-08-03", net_nav: "75", benchmark_nav: "0.75" },
      { session: "2026-08-04", net_nav: "NaN", benchmark_nav: "0.8" },
    ]);

    expect(points).toEqual([
      { time: "2026-08-02", strategy: 0, benchmark: 0 },
      { time: "2026-08-03", strategy: 50, benchmark: 50 },
    ]);
  });
});
