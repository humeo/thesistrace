import { useMemo } from "react";

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
  benchmark_nav: string;
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
        benchmark_cumulative_return: number;
        annualized_excess_return: number;
        maximum_drawdown: { value: number | null };
        sharpe: number | null;
        transaction_costs: { cumulative_amount: number };
      };
    };
    benchmark: {
      universe: string;
      methodology: "selected_universe_equal_weight";
    };
    observations: DailyTrackStrategyObservation[];
  };
};

const FACTOR_HORIZONS = ["1", "5", "20"] as const;

export function DailyTrackAnalysisView({ analysis }: { analysis: DailyTrackAnalysis }) {
  const metrics = analysis.strategy.summary.metrics;
  return (
    <div className="research-result">
      <section className="research-result-section">
        <div className="section-heading">
          <p className="eyebrow">Predictive evidence</p>
          <h2>Factor Evaluation</h2>
        </div>
        <div className="factor-horizons">
          {FACTOR_HORIZONS.map((name) => (
            <FactorHorizonView horizon={analysis.factor.horizons[name]} key={name} />
          ))}
        </div>
      </section>

      <section className="research-result-section">
        <div className="section-heading">
          <p className="eyebrow">Fixed origin · recent chart</p>
          <h2>Cumulative Strategy</h2>
          <p>Selected universe {analysis.strategy.benchmark.universe}</p>
        </div>
        <div className="strategy-metrics">
          <Metric label="Net cumulative" value={formatPercent(metrics.net_cumulative_return)} />
          <Metric
            label="Benchmark cumulative"
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
        <StrategyBenchmarkChart observations={analysis.strategy.observations} />
      </section>
    </div>
  );
}

function FactorHorizonView({ horizon }: { horizon: DailyTrackFactorHorizon }) {
  return (
    <section aria-label={`${horizon.horizon}-session Factor`}>
      <strong>{horizon.horizon}-session</strong>
      <p>{horizon.coverage.signal_session_count} signal sessions</p>
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

function StrategyBenchmarkChart({
  observations,
}: {
  observations: DailyTrackStrategyObservation[];
}) {
  const lines = useMemo(() => chartLines(observations), [observations]);
  if (observations.length === 0) return <p>No recent Strategy observations.</p>;
  return (
    <figure className="strategy-chart">
      <figcaption>
        <span><i className="strategy-swatch" /> Net strategy</span>
        <span><i className="benchmark-swatch" /> Selected-universe benchmark</span>
        <span>{observations.length} Research Sessions</span>
      </figcaption>
      <svg
        aria-label="Strategy and benchmark NAV"
        preserveAspectRatio="none"
        role="img"
        viewBox="0 0 640 180"
      >
        <line x1="0" x2="640" y1="90" y2="90" />
        <polyline className="benchmark-line" points={lines.benchmark} />
        <polyline className="strategy-line" points={lines.strategy} />
      </svg>
      <p>{observations[0].session} — {observations.at(-1)?.session}</p>
    </figure>
  );
}

function chartLines(observations: DailyTrackStrategyObservation[]) {
  if (observations.length === 0) return { strategy: "", benchmark: "" };
  const firstStrategy = Number(observations[0].net_nav);
  const firstBenchmark = Number(observations[0].benchmark_nav);
  const strategyValues = observations.map((item) => Number(item.net_nav) / firstStrategy);
  const benchmarkValues = observations.map(
    (item) => Number(item.benchmark_nav) / firstBenchmark,
  );
  const values = [...strategyValues, ...benchmarkValues];
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const span = maximum - minimum || 1;
  const points = (series: number[]) => series.map((value, index) => {
    const x = (index / Math.max(series.length - 1, 1)) * 640;
    const y = 170 - ((value - minimum) / span) * 160;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  return { strategy: points(strategyValues), benchmark: points(benchmarkValues) };
}

function formatPercent(value: number | null) {
  return value === null ? "—" : `${(value * 100).toFixed(2)}%`;
}

function formatDecimal(value: number | null) {
  return value === null ? "—" : value.toFixed(3);
}

function formatCny(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "CNY",
    maximumFractionDigits: 0,
  }).format(value);
}
