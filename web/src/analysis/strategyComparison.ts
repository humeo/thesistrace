export type StrategyComparisonCurvePoint = {
  session: string;
  net_strategy_return: number;
  benchmark_relative_return: number;
  net_excess_nav: number;
  net_excess_return: number;
};

export type AvailableStrategyComparison = {
  status: "available";
  benchmark: {
    id: "csi300-price-index-open";
    display_name: "沪深300";
    ts_code: "399300.SZ";
    kind: "price_index";
    coordinate: "open";
    snapshot_sha256: string;
    coverage: {
      start_session: string;
      end_session: string;
    };
    published_at: string;
  };
  entry: {
    session: string;
    benchmark_open_level: string;
    initial_cash_cny: string;
  };
  terminal: {
    session: string;
    benchmark_open_level: string;
    net_nav: string;
  };
  metrics: {
    net_strategy_cumulative_return: number;
    benchmark_cumulative_return: number;
    net_strategy_cagr: number | null;
    benchmark_cagr: number | null;
    annualized_excess_return: number | null;
  };
  curves: StrategyComparisonCurvePoint[];
};

export type UnavailableStrategyComparison = {
  status: "unavailable";
  reason: "benchmark_snapshot_unavailable";
};

export type StrategyComparison =
  | AvailableStrategyComparison
  | UnavailableStrategyComparison;
