import { useEffect, useMemo, useRef, useState } from "react";

type CorrelationSummary = {
  mean: number | null;
  sample_deviation: number | null;
  icir: number | null;
  positive_fraction: number | null;
  valid_session_count: number;
};

type FactorHorizon = {
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

type StrategyObservation = {
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

type StrategyMetrics = {
  net_cumulative_return: number;
  benchmark_cumulative_return: number;
  annualized_excess_return: number;
  maximum_drawdown: { value: number | null };
  sharpe: number | null;
  transaction_costs: { cumulative_amount: number };
};

type ResearchResult = {
  factor: { horizons: Record<"1" | "5" | "20", FactorHorizon> };
  strategy: {
    summary: {
      alpha_checksum: string;
      initial_cash_cny: string;
      source_checksum: string;
      metrics: StrategyMetrics;
    };
    benchmark: {
      universe: string;
      methodology: "selected_universe_equal_weight";
    };
    observations: StrategyObservation[];
  };
  provenance: {
    schema_version: string;
    research_run_id: string;
    immutable_input_sha256: string;
    dataset_release_id: string;
    calculation_contracts: Record<string, unknown>;
    semantic_versions: Record<string, string>;
  };
};

type ResearchRun = {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  definition_id: string;
  definition_revision: number;
  dataset_release_id: string;
  failure_reason?: string;
  result?: ResearchResult;
};

type ResearchRunList = { items: ResearchRun[]; next_cursor: string | null };
type LoadState = "loading" | "refreshing" | null;
const FACTOR_HORIZONS = ["1", "5", "20"] as const;

export function ResearchRunsPage({ runId }: { runId?: string }) {
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [items, setItems] = useState<ResearchRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [canceling, setCanceling] = useState(false);
  const [refreshGeneration, setRefreshGeneration] = useState(0);
  const cancelRequestId = useRef<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let timeout: number | undefined;
    setError(null);
    setLoadState(refreshGeneration === 0 ? "loading" : "refreshing");
    const path = runId ? `/api/research-runs/${runId}` : "/api/research-runs";

    async function load(polling = false) {
      try {
        const response = await fetch(path, { signal: controller.signal });
        if (!response.ok) throw new Error("ResearchRun unavailable");
        if (runId) {
          const nextRun = (await response.json()) as ResearchRun;
          setRun(nextRun);
          if (nextRun.status === "queued" || nextRun.status === "running") {
            timeout = window.setTimeout(() => void load(true), 500);
          }
        } else {
          const nextItems = ((await response.json()) as ResearchRunList).items;
          setItems(nextItems);
          if (nextItems.some((item) => item.status === "queued" || item.status === "running")) {
            timeout = window.setTimeout(() => void load(true), 500);
          }
        }
        if (!polling) setLoadState(null);
      } catch (reason: unknown) {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setLoadState(null);
        setError("ResearchRun unavailable");
      }
    }

    void load();
    return () => {
      if (timeout !== undefined) window.clearTimeout(timeout);
      controller.abort();
    };
  }, [refreshGeneration, runId]);

  function refresh() {
    setRefreshGeneration((generation) => generation + 1);
  }

  async function cancel() {
    if (run === null || !["queued", "running"].includes(run.status)) return;
    setCanceling(true);
    setError(null);
    const requestId = cancelRequestId.current ?? `cancel_${crypto.randomUUID()}`;
    cancelRequestId.current = requestId;
    try {
      const response = await fetch(`/api/research-runs/${run.id}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: requestId }),
      });
      if (!response.ok) throw new Error("ResearchRun cancellation failed");
      setRun((await response.json()) as ResearchRun);
      cancelRequestId.current = null;
    } catch {
      setError("ResearchRun cancellation failed");
    } finally {
      setCanceling(false);
    }
  }

  if (error) {
    return (
      <section aria-label="Research Runs">
        <h1>ResearchRun</h1>
        <p role="alert">{error}</p>
        <button onClick={refresh}>Retry</button>
      </section>
    );
  }
  if (runId && run === null) {
    return <section aria-label="Research Runs"><p>Loading ResearchRun…</p></section>;
  }
  if (!runId && items === null) {
    return <section aria-label="Research Runs"><p>Loading Research Runs…</p></section>;
  }
  if (run) {
    return (
      <section aria-label="Research Runs" className="research-run-page">
        <header className="research-run-header">
          <div>
            <p className="eyebrow">Immutable research execution</p>
            <h1>ResearchRun</h1>
          </div>
          <div>
            {run.status === "queued" || run.status === "running" ? (
              <button disabled={canceling} onClick={() => void cancel()}>
                {canceling ? "Cancelling…" : "Cancel"}
              </button>
            ) : null}
            <button disabled={loadState !== null || canceling} onClick={refresh}>
              Refresh
            </button>
          </div>
        </header>
        {loadState === "refreshing" ? (
          <p role="status">Refreshing ResearchRun…</p>
        ) : null}
        <div className="research-run-facts">
          <p><strong>Status</strong> {run.status}</p>
          <p>
            <strong>Definition</strong>{" "}
            <a href={`/definitions/${run.definition_id}`}>
              Revision {run.definition_revision}
            </a>
          </p>
          <p><strong>Dataset Release</strong> {run.dataset_release_id}</p>
        </div>
        {run.status === "failed" && run.failure_reason ? (
          <p role="alert"><strong>Failure</strong> {run.failure_reason}</p>
        ) : null}
        {run.status === "succeeded" && run.result ? (
          <ResearchResultView result={run.result} />
        ) : null}
      </section>
    );
  }
  return (
    <section aria-label="Research Runs">
      <h1>Research Runs</h1>
      {items?.length === 0 ? <p>No Research Runs yet.</p> : null}
      <ol aria-label="Research Runs">
        {items?.map((item) => (
          <li key={item.id}>
            <a href={`/research-runs/${item.id}`}>{item.id}</a>
            <span> · {item.status}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function ResearchResultView({ result }: { result: ResearchResult }) {
  const metrics = result.strategy.summary.metrics;
  return (
    <div className="research-result">
      <section className="research-result-section">
        <div className="section-heading">
          <p className="eyebrow">Predictive evidence</p>
          <h2>Factor Evaluation</h2>
        </div>
        <div className="factor-horizons">
          {FACTOR_HORIZONS.map((name) => (
            <FactorHorizonView horizon={result.factor.horizons[name]} key={name} />
          ))}
        </div>
      </section>

      <section className="research-result-section">
        <div className="section-heading">
          <p className="eyebrow">One fill path · net is primary</p>
          <h2>Strategy / Benchmark</h2>
          <p>Selected universe {result.strategy.benchmark.universe}</p>
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
        <StrategyBenchmarkChart observations={result.strategy.observations} />
      </section>

      <section className="research-result-section research-provenance">
        <div className="section-heading">
          <p className="eyebrow">Frozen inputs and calculation contracts</p>
          <h2>Provenance</h2>
        </div>
        <dl>
          <div><dt>Dataset Release</dt><dd>{result.provenance.dataset_release_id}</dd></div>
          <div>
            <dt>Input digest</dt>
            <dd><code>{shortDigest(result.provenance.immutable_input_sha256)}</code></dd>
          </div>
          <div><dt>Result schema</dt><dd>{result.provenance.schema_version}</dd></div>
          <div>
            <dt>Kernel</dt>
            <dd>{result.provenance.semantic_versions.kernel}</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}

function FactorHorizonView({ horizon }: { horizon: FactorHorizon }) {
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

function StrategyBenchmarkChart({ observations }: { observations: StrategyObservation[] }) {
  const lines = useMemo(() => chartLines(observations), [observations]);
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
      <p>{observations[0]?.session} — {observations.at(-1)?.session}</p>
    </figure>
  );
}

function chartLines(observations: StrategyObservation[]) {
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

function shortDigest(value: string) {
  return `${value.slice(0, 12)}…${value.slice(-8)}`;
}
