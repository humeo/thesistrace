import { describe, expect, it } from "vitest";

import { strategyChartPoints } from "./StrategyPerformanceChart";

describe("strategyChartPoints", () => {
  it("passes through backend-aligned Strategy, 沪深300, and Net Excess returns", () => {
    const points = strategyChartPoints([
      {
        session: "2026-08-04",
        net_strategy_return: -0.001,
        benchmark_relative_return: 0.0125,
        net_excess_nav: 0.9861728395,
        net_excess_return: -0.0138271605,
      },
      {
        session: "2026-08-05",
        net_strategy_return: 0.01,
        benchmark_relative_return: 0.02,
        net_excess_nav: 0.9901960784,
        net_excess_return: -0.0098039216,
      },
    ]);

    expect(points).toEqual([
      {
        time: "2026-08-04",
        strategy: -0.001,
        benchmark: 0.0125,
        netExcess: -0.0138271605,
      },
      {
        time: "2026-08-05",
        strategy: 0.01,
        benchmark: 0.02,
        netExcess: -0.0098039216,
      },
    ]);
  });

  it("keeps a 504-point DailyTrack window on the seed-relative backend baseline", () => {
    const curves = Array.from({ length: 504 }, (_, index) => ({
      session: new Date(Date.UTC(2024, 0, 1 + index)).toISOString().slice(0, 10),
      net_strategy_return: 0.25 + (index / 10_000),
      benchmark_relative_return: 0.2 + (index / 20_000),
      net_excess_nav: 1.0416666667 + (index / 100_000),
      net_excess_return: 0.0416666667 + (index / 100_000),
    }));

    const points = strategyChartPoints(curves);

    expect(points).toHaveLength(504);
    expect(points[0]).toEqual({
      time: curves[0]?.session,
      strategy: 0.25,
      benchmark: 0.2,
      netExcess: 0.0416666667,
    });
    expect(points[0]?.strategy).not.toBe(0);
    expect(points[0]?.benchmark).not.toBe(0);
  });
});
