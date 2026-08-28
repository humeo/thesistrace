import { StrategyComparisonPanel } from "../analysis/StrategyComparisonPanel";
import type { StrategyComparison } from "../analysis/strategyComparison";
import { STRATEGY_BENCHMARK_DISPLAY_NAME } from "../benchmark";

type CorrelationSummary = {
  mean: number | null;
  sample_deviation: number | null;
  icir: number | null;
  positive_fraction: number | null;
  valid_session_count: number;
};

export type DailyTrackFactorHorizon = {
  horizon: 1 | 5 | 20;
  summary: {
    ic: CorrelationSummary;
    rank_ic: CorrelationSummary;
    quantile_returns: Record<"q1" | "q2" | "q3" | "q4" | "q5", number | null>;
    top_bottom_return: number | null;
  };
  coverage: {
    signal_session_count: number;
    ic_valid_session_count: number;
    rank_ic_valid_session_count: number;
    quantile_valid_session_count: number;
  };
};

export type DailyTrackStrategyObservation = {
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
  factor: {
    horizons: Record<"1" | "5" | "20", DailyTrackFactorHorizon>;
  };
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

const FACTOR_HORIZONS = ["1", "5", "20"] as const;

export function DailyTrackAnalysisView({ analysis }: { analysis: DailyTrackAnalysis }) {
  const metrics = analysis.strategy.summary.metrics;
  return (
    <div className="research-result">
      <section className="research-result-section">
        <div className="section-heading">
          <h2>Factor Summary</h2>
        </div>
        <div className="factor-horizons">
          {FACTOR_HORIZONS.map((name) => (
            <FactorHorizonView horizon={analysis.factor.horizons[name]} key={name} />
          ))}
        </div>
      </section>

      <section className="research-result-section">
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
        <StrategyComparisonPanel comparison={analysis.strategy.comparison} />
      </section>
    </div>
  );
}

function FactorHorizonView({ horizon }: { horizon: DailyTrackFactorHorizon }) {
  return (
    <section aria-label={`${horizon.horizon}-session Factor`}>
      <strong>{horizon.horizon}-session</strong>
      <Metric label="Rank IC" value={formatDecimal(horizon.summary.rank_ic.mean)} />
      <Metric label="Rank ICIR" value={formatDecimal(horizon.summary.rank_ic.icir)} />
      <Metric label="IC" value={formatDecimal(horizon.summary.ic.mean)} />
      <Metric label="ICIR" value={formatDecimal(horizon.summary.ic.icir)} />
      <p className="factor-coverage">
        Rank IC coverage {horizon.coverage.rank_ic_valid_session_count}/
        {horizon.coverage.signal_session_count}
      </p>
    </section>
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
