import { STRATEGY_BENCHMARK_DISPLAY_NAME } from "../benchmark";
import { StrategyPerformanceChart } from "./StrategyPerformanceChart";
import type { StrategyComparison } from "./strategyComparison";

export function StrategyComparisonPanel({
  comparison,
}: {
  comparison: StrategyComparison;
}) {
  if (comparison.status === "unavailable") {
    return (
      <section
        aria-label={`${STRATEGY_BENCHMARK_DISPLAY_NAME} Strategy Comparison`}
        className="strategy-comparison-unavailable"
        role="status"
      >
        <strong>{STRATEGY_BENCHMARK_DISPLAY_NAME} comparison unavailable</strong>
        <p>
          {comparison.reason === "no_entry_open"
            ? "The account has not reached its first scheduled trading Open. No entry-period comparison is available yet."
            : "The fixed Benchmark Snapshot is unavailable. No comparison chart is shown."}
        </p>
      </section>
    );
  }

  return <StrategyPerformanceChart curves={comparison.curves} />;
}
