import { StrategyComparisonPanel } from "../analysis/StrategyComparisonPanel";
import type { StrategyComparison } from "../analysis/strategyComparison";
import { STRATEGY_BENCHMARK_DISPLAY_NAME } from "../benchmark";

type DailyTrackStrategyObservation = {
  session: string;
  gross_nav: string;
  net_nav: string;
  net_cash: string;
  transaction_cost_cny: string;
  holdings_count: number;
  maximum_single_name_weight: number;
  upper_limit_buy_rejections: number;
  lower_limit_sell_rejections: number;
  suspension_rejections: number;
};

export type DailyTrackAnalysis = {
  strategy: {
    summary: {
      metrics: {
        net_cumulative_return: number;
        benchmark_cumulative_return: number | null;
        benchmark_cagr: number | null;
        annualized_excess_return: number | null;
        maximum_drawdown: { value: number | null };
        sharpe: number | null;
        transaction_costs: { cumulative_amount: number };
      };
    };
    observations: DailyTrackStrategyObservation[];
    comparison: StrategyComparison;
  };
};

export function DailyTrackAnalysisView({ analysis }: { analysis: DailyTrackAnalysis }) {
  const metrics = analysis.strategy.summary.metrics;
  return (
    <div className="research-result">
      <section className="research-result-section">
        <StrategyComparisonPanel comparison={analysis.strategy.comparison} />
        <div className="section-heading">
          <h2>Strategy Summary</h2>
        </div>
        <div className="strategy-metrics">
          <Metric label="Net cumulative" value={formatPercent(metrics.net_cumulative_return)} />
          <Metric
            label={`${STRATEGY_BENCHMARK_DISPLAY_NAME} cumulative`}
            value={formatPercent(metrics.benchmark_cumulative_return)}
          />
          <Metric
            label="Annualized excess"
            value={formatPercent(metrics.annualized_excess_return)}
          />
          <Metric
            label="Maximum drawdown"
            value={formatPercent(metrics.maximum_drawdown.value)}
          />
          <Metric label="Sharpe" value={formatDecimal(metrics.sharpe)} />
          <Metric
            label="Transaction costs"
            value={formatCny(metrics.transaction_costs.cumulative_amount)}
          />
        </div>
      </section>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="result-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function formatPercent(value: number | null) {
  return value === null ? "Not available" : `${(value * 100).toFixed(2)}%`;
}

function formatDecimal(value: number | null) {
  return value === null ? "Not available" : value.toFixed(3);
}

function formatCny(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "CNY",
    maximumFractionDigits: 0,
  }).format(value);
}
