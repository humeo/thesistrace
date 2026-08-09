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
    calculation_contracts: Record<string, unknown>;
    semantic_versions: Record<string, string>;
  };
};

type ResearchRun = {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  definition_id: string;
  definition_revision: number;
  start_date: string;
  end_date: string;
  rerun_of_id?: string;
  failure_reason?: string;
  result?: ResearchResult;
};

type ResearchRunList = { items: ResearchRun[]; next_cursor: string | null };
type LoadState = "loading" | "refreshing" | null;
const FACTOR_HORIZONS = ["1", "5", "20"] as const;
const ACTIVE_TRACK_LIMIT_DETAIL = "Active DailyTrack limit of 10 reached";
const ACTIVE_TRACK_LIMIT_MESSAGE =
  "10 active or blocked DailyTracks already exist. Stop one before starting another.";

export function ResearchRunsPage({ runId }: { runId?: string }) {
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [items, setItems] = useState<ResearchRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [canceling, setCanceling] = useState(false);
  const [rerunning, setRerunning] = useState(false);
  const [startingTracking, setStartingTracking] = useState(false);
  const [refreshGeneration, setRefreshGeneration] = useState(0);
  const loadGeneration = useRef(0);
  const cancelGeneration = useRef(0);
  const cancelController = useRef<AbortController | null>(null);
  const cancelRequest = useRef<{ runId: string; requestId: string } | null>(null);
  const rerunGeneration = useRef(0);
  const rerunController = useRef<AbortController | null>(null);
  const rerunRequest = useRef<{ runId: string; requestId: string } | null>(null);
  const trackingGeneration = useRef(0);
  const trackingController = useRef<AbortController | null>(null);
  const trackingRequest = useRef<{ runId: string; requestId: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const generation = ++loadGeneration.current;
    let timeout: number | undefined;
    setError(null);
    setLoadState(refreshGeneration === 0 ? "loading" : "refreshing");
    const path = runId ? `/api/research-runs/${runId}` : "/api/research-runs";

    async function load(polling = false) {
      try {
        const response = await fetch(path, { signal: controller.signal });
        if (!response.ok) throw new Error("ResearchRun unavailable");
        if (generation !== loadGeneration.current) return;
        if (runId) {
          const nextRun = (await response.json()) as ResearchRun;
          if (generation !== loadGeneration.current) return;
          setRun(nextRun);
          if (nextRun.status === "queued" || nextRun.status === "running") {
            timeout = window.setTimeout(() => void load(true), 500);
          }
        } else {
          const nextItems = ((await response.json()) as ResearchRunList).items;
          if (generation !== loadGeneration.current) return;
          setItems(nextItems);
          if (nextItems.some((item) => item.status === "queued" || item.status === "running")) {
            timeout = window.setTimeout(() => void load(true), 500);
          }
        }
        if (!polling) setLoadState(null);
      } catch (reason: unknown) {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        if (generation !== loadGeneration.current) return;
        setLoadState(null);
        setError("ResearchRun unavailable");
      }
    }

    void load();
    return () => {
      if (generation === loadGeneration.current) loadGeneration.current += 1;
      if (timeout !== undefined) window.clearTimeout(timeout);
      controller.abort();
    };
  }, [refreshGeneration, runId]);

  useEffect(() => () => {
    cancelGeneration.current += 1;
    cancelController.current?.abort();
    cancelController.current = null;
    cancelRequest.current = null;
    rerunGeneration.current += 1;
    rerunController.current?.abort();
    rerunController.current = null;
    rerunRequest.current = null;
    trackingGeneration.current += 1;
    trackingController.current?.abort();
    trackingController.current = null;
    trackingRequest.current = null;
  }, [runId]);

  function refresh() {
    setRefreshGeneration((generation) => generation + 1);
  }

  async function cancel() {
    if (run === null || !["queued", "running"].includes(run.status)) return;
    const targetRun = run;
    const generation = ++cancelGeneration.current;
    loadGeneration.current += 1;
    setLoadState(null);
    cancelController.current?.abort();
    const controller = new AbortController();
    cancelController.current = controller;
    setCanceling(true);
    setError(null);
    const pending = cancelRequest.current;
    const requestId = pending?.runId === targetRun.id
      ? pending.requestId
      : `cancel_${crypto.randomUUID()}`;
    cancelRequest.current = { runId: targetRun.id, requestId };
    try {
      const response = await fetch(`/api/research-runs/${targetRun.id}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: requestId }),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("ResearchRun cancellation failed");
      if (generation !== cancelGeneration.current) return;
      setRun((await response.json()) as ResearchRun);
      cancelRequest.current = null;
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      if (generation !== cancelGeneration.current) return;
      setError("ResearchRun cancellation failed");
    } finally {
      if (generation === cancelGeneration.current) {
        cancelController.current = null;
        setCanceling(false);
      }
    }
  }

  async function rerunSelected() {
    if (run === null || !["succeeded", "failed", "cancelled"].includes(run.status)) return;
    const targetRun = run;
    const generation = ++rerunGeneration.current;
    loadGeneration.current += 1;
    setLoadState(null);
    rerunController.current?.abort();
    const controller = new AbortController();
    rerunController.current = controller;
    setRerunning(true);
    setError(null);
    const pending = rerunRequest.current;
    const requestId = pending?.runId === targetRun.id
      ? pending.requestId
      : `rerun_${crypto.randomUUID()}`;
    rerunRequest.current = { runId: targetRun.id, requestId };
    try {
      const response = await fetch(`/api/research-runs/${targetRun.id}/rerun`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: requestId }),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("ResearchRun rerun failed");
      const nextRun = (await response.json()) as ResearchRun;
      if (generation !== rerunGeneration.current) return;
      rerunRequest.current = null;
      window.location.assign(`/research-runs/${nextRun.id}`);
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      if (generation !== rerunGeneration.current) return;
      setError("ResearchRun rerun failed");
    } finally {
      if (generation === rerunGeneration.current) {
        rerunController.current = null;
        setRerunning(false);
      }
    }
  }

  async function startTracking() {
    if (run === null || run.status !== "succeeded") return;
    const targetRun = run;
    const generation = ++trackingGeneration.current;
    loadGeneration.current += 1;
    setLoadState(null);
    trackingController.current?.abort();
    const controller = new AbortController();
    trackingController.current = controller;
    setStartingTracking(true);
    setError(null);
    const pending = trackingRequest.current;
    const requestId = pending?.runId === targetRun.id
      ? pending.requestId
      : `track_${crypto.randomUUID()}`;
    trackingRequest.current = { runId: targetRun.id, requestId };
    try {
      const response = await fetch(`/api/research-runs/${targetRun.id}/daily-tracks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: requestId }),
        signal: controller.signal,
      });
      if (!response.ok) {
        if (response.status === 409) {
          const body = (await response.json()) as { detail?: unknown };
          if (body.detail === ACTIVE_TRACK_LIMIT_DETAIL) {
            throw new Error(ACTIVE_TRACK_LIMIT_MESSAGE);
          }
        }
        throw new Error("Start Tracking failed");
      }
      const track = (await response.json()) as { id: string };
      if (generation !== trackingGeneration.current) return;
      trackingRequest.current = null;
      window.location.assign(`/daily-tracks/${track.id}`);
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      if (generation !== trackingGeneration.current) return;
      setError(
        reason instanceof Error && reason.message === ACTIVE_TRACK_LIMIT_MESSAGE
          ? ACTIVE_TRACK_LIMIT_MESSAGE
          : "Start Tracking failed",
      );
    } finally {
      if (generation === trackingGeneration.current) {
        trackingController.current = null;
        setStartingTracking(false);
      }
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
            {["succeeded", "failed", "cancelled"].includes(run.status) ? (
              <button
                disabled={rerunning || startingTracking}
                onClick={() => void rerunSelected()}
              >
                {rerunning ? "Rerunning on current data…" : "Rerun on current data"}
              </button>
            ) : null}
            {run.status === "succeeded" ? (
              <button
                disabled={rerunning || startingTracking}
                onClick={() => void startTracking()}
              >
                {startingTracking ? "Starting Tracking…" : "Start Tracking"}
              </button>
            ) : null}
            <button
              disabled={loadState !== null || canceling || rerunning || startingTracking}
              onClick={refresh}
            >
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
          <p><strong>Research period</strong> {run.start_date} to {run.end_date}</p>
          {run.rerun_of_id ? (
            <p>
              <strong>Rerun of</strong>{" "}
              <a href={`/research-runs/${run.rerun_of_id}`}>{run.rerun_of_id}</a>
            </p>
          ) : null}
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
            <span> · {item.status} · {item.start_date} to {item.end_date}</span>
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
          <p className="eyebrow">Run inputs and calculation contracts</p>
          <h2>Provenance</h2>
        </div>
        <dl>
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
