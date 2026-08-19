import { useEffect, useMemo, useRef, useState } from "react";

import {
  useResearchAsDraft,
  type FrozenResearchAuthorableInput,
} from "../research/draft";

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

export type TerminalStrategyState = {
  session: string;
  gross_cash: string;
  net_cash: string;
  gross_nav: string;
  net_nav: string;
  benchmark_nav: string;
  cumulative_transaction_cost: string;
  positions: Array<{
    instrument_id: string;
    execution_shares: number;
    adjusted_units: string;
    last_adjusted_price: string;
  }>;
  rebalance_phase: {
    origin_session: string;
    report_session_count: number;
    rebalance_interval: number;
    completed_intervals: number;
  };
  pending_signal: {
    signal_session: string;
    execution: "next_research_session_open";
  } | null;
};

type ResearchResultProvenance = {
  schema_version: string;
  research_run_id: string;
  immutable_input_sha256: string;
  calculation_contracts: Record<string, unknown>;
  semantic_versions: Record<string, string>;
};

type FactorEvaluationResearchResult = {
  factor: { horizons: Record<"1" | "5" | "20", FactorHorizon> };
  provenance: ResearchResultProvenance & {
    research_kind: "factor_evaluation";
  };
};

type StrategyBacktestResearchResult = {
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
  terminal_strategy_state: TerminalStrategyState;
  provenance: ResearchResultProvenance & {
    research_kind: "strategy_backtest";
  };
};

type ResearchResult = FactorEvaluationResearchResult | StrategyBacktestResearchResult;

export type ResearchRunProgress = {
  phase: "queued" | "warmup" | "research" | "finalizing" | "succeeded";
  completed_warmup_sessions: number;
  total_warmup_sessions: number;
  completed_research_sessions: number;
  total_research_sessions: number;
  committed_chunk_count: number;
  last_completed_warmup_session: string | null;
  last_completed_research_session: string | null;
  remaining_duration_estimate_seconds: number | null;
  duration_is_estimate: boolean;
};

export type ResearchRun = {
  id: string;
  status: "queued" | "running" | "cancelling" | "succeeded" | "failed" | "cancelled";
  name: string;
  folder_id: string;
  created_at: string;
  start_date: string;
  end_date: string;
  formula_summary: string;
  research_kind: "factor_evaluation" | "strategy_backtest";
  input?: FrozenResearchAuthorableInput;
  failure_reason?: string;
  result?: ResearchResult;
  progress?: ResearchRunProgress;
};

type ResearchRunList = { items: ResearchRun[]; next_cursor: string | null };
export type ResearchFolderOption = {
  id: string;
  name: string;
  is_default: boolean;
};
type ResearchFolderList = { items: ResearchFolderOption[]; next_cursor: null };
type LoadState = "loading" | "refreshing" | null;
const FACTOR_HORIZONS = ["1", "5", "20"] as const;
const ACTIVE_TRACK_LIMIT_DETAIL = "Active DailyTrack limit of 10 reached";
const ACTIVE_TRACK_LIMIT_MESSAGE =
  "10 active or blocked DailyTracks already exist. Stop one before starting another.";

export function ResearchRunsPage({ runId }: { runId?: string }) {
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [items, setItems] = useState<ResearchRun[] | null>(null);
  const [folders, setFolders] = useState<ResearchFolderOption[]>([]);
  const [folderFilter, setFolderFilter] = useState("");
  const [folderError, setFolderError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [canceling, setCanceling] = useState(false);
  const [startingTracking, setStartingTracking] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [refreshGeneration, setRefreshGeneration] = useState(0);
  const [folderRefreshGeneration, setFolderRefreshGeneration] = useState(0);
  const loadGeneration = useRef(0);
  const cancelGeneration = useRef(0);
  const cancelController = useRef<AbortController | null>(null);
  const cancelRequest = useRef<{ runId: string; requestId: string } | null>(null);
  const trackingGeneration = useRef(0);
  const trackingController = useRef<AbortController | null>(null);
  const trackingRequest = useRef<{ runId: string; requestId: string } | null>(null);
  const deleteGeneration = useRef(0);
  const deleteController = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setFolderError(null);
    void fetch("/api/research-folders", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Research Folders unavailable");
        const payload = (await response.json()) as ResearchFolderList;
        setFolders(payload.items);
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setFolderError("Research Folders unavailable");
      });
    return () => controller.abort();
  }, [folderRefreshGeneration]);

  useEffect(() => {
    const controller = new AbortController();
    const generation = ++loadGeneration.current;
    let timeout: number | undefined;
    setError(null);
    setLoadState(refreshGeneration === 0 ? "loading" : "refreshing");
    const path = runId
      ? `/api/research-runs/${runId}`
      : folderFilter
        ? `/api/research-runs?folder_id=${encodeURIComponent(folderFilter)}`
        : "/api/research-runs";

    async function load(polling = false) {
      try {
        const response = await fetch(path, { signal: controller.signal });
        if (!response.ok) throw new Error("ResearchRun unavailable");
        if (generation !== loadGeneration.current) return;
        if (runId) {
          const nextRun = (await response.json()) as ResearchRun;
          if (generation !== loadGeneration.current) return;
          setRun(nextRun);
          if (
            nextRun.status === "queued" ||
            nextRun.status === "running" ||
            nextRun.status === "cancelling"
          ) {
            timeout = window.setTimeout(() => void load(true), 500);
          }
        } else {
          const nextItems = ((await response.json()) as ResearchRunList).items;
          if (generation !== loadGeneration.current) return;
          setItems(nextItems);
          if (
            nextItems.some(
              (item) =>
                item.status === "queued" ||
                item.status === "running" ||
                item.status === "cancelling",
            )
          ) {
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
  }, [folderFilter, refreshGeneration, runId]);

  useEffect(() => () => {
    cancelGeneration.current += 1;
    cancelController.current?.abort();
    cancelController.current = null;
    cancelRequest.current = null;
    trackingGeneration.current += 1;
    trackingController.current?.abort();
    trackingController.current = null;
    trackingRequest.current = null;
    deleteGeneration.current += 1;
    deleteController.current?.abort();
    deleteController.current = null;
  }, [runId]);

  function refresh() {
    setRefreshGeneration((generation) => generation + 1);
  }

  function refreshFolders() {
    setFolderRefreshGeneration((generation) => generation + 1);
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
      const nextRun = (await response.json()) as ResearchRun;
      setRun(nextRun);
      if (nextRun.status === "cancelling") {
        setRefreshGeneration((current) => current + 1);
      }
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

  async function startTracking() {
    if (run === null || run.status !== "succeeded" || deleting) return;
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

  async function deleteResearch(): Promise<void> {
    if (
      run === null
      || !isTerminalResearch(run.status)
      || deleting
      || startingTracking
    ) return;
    if (!window.confirm(`Permanently delete ${run.name}? DailyTracks will remain.`)) return;
    const generation = ++deleteGeneration.current;
    deleteController.current?.abort();
    const controller = new AbortController();
    deleteController.current = controller;
    setDeleting(true);
    setDeleteError(null);
    try {
      const response = await fetch(`/api/research-runs/${run.id}`, {
        method: "DELETE",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`Research deletion failed (${response.status})`);
      if (generation !== deleteGeneration.current) return;
      window.location.assign("/research-runs");
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      if (generation !== deleteGeneration.current) return;
      setDeleteError(reason instanceof Error ? reason.message : "Research deletion failed");
    } finally {
      if (generation === deleteGeneration.current) {
        deleteController.current = null;
        setDeleting(false);
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
            {run.status === "succeeded" && run.research_kind === "strategy_backtest" ? (
              <button
                disabled={startingTracking || deleting}
                onClick={() => void startTracking()}
              >
                {startingTracking ? "Starting Tracking…" : "Start Tracking"}
              </button>
            ) : null}
            {isTerminalResearch(run.status) ? (
              <button
                disabled={deleting || startingTracking}
                onClick={() => void deleteResearch()}
              >
                {deleting ? "Deleting…" : "Delete Research"}
              </button>
            ) : null}
          </div>
        </header>
        {loadState === "refreshing" ? (
          <p role="status">Refreshing ResearchRun…</p>
        ) : null}
        <div className="research-run-facts">
          <p><strong>Status</strong> {run.status}</p>
          <p><strong>Name</strong> {run.name}</p>
          <p><strong>Research type</strong> {researchKindLabel(run.research_kind)}</p>
          <p><strong>Formula</strong> <code>{run.input?.formula ?? run.formula_summary}</code></p>
          <p><strong>Research period</strong> {run.start_date} to {run.end_date}</p>
        </div>
        {run.progress ? (
          <ResearchRunProgressView
            active={run.status === "running" || run.status === "cancelling"}
            progress={run.progress}
          />
        ) : null}
        {deleteError !== null ? <p role="alert">{deleteError}</p> : null}
        {deleting ? null : folderError !== null ? (
          <ResearchFolderLoadFailure error={folderError} onRetry={refreshFolders} />
        ) : folders.length === 0 ? (
          <p role="status">Loading Research Folders…</p>
        ) : (
          <ResearchOrganizationPanel
            folders={folders}
            key={`${run.id}:${run.name}:${run.folder_id}`}
            onOrganized={(organized) => setRun((current) => current === null
              ? organized
              : { ...current, ...organized })}
            run={run}
          />
        )}
        {!deleting && folders.length > 0 && run.input !== undefined && isTerminalResearch(run.status) ? (
          <UseAsDraftPanel folders={folders} input={run.input} sourceFolderId={run.folder_id} />
        ) : null}
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
      {folderError !== null ? (
        <ResearchFolderLoadFailure error={folderError} onRetry={refreshFolders} />
      ) : folders.length === 0 ? (
        <p role="status">Loading Research Folders…</p>
      ) : (
        <label>Filter by Folder
          <select
            aria-label="Filter by Folder"
            onChange={(event) => setFolderFilter(event.target.value)}
            value={folderFilter}
          >
            <option value="">All Folders</option>
            {folders.map((folder) => (
              <option key={folder.id} value={folder.id}>{folder.name}</option>
            ))}
          </select>
        </label>
      )}
      {items?.length === 0 ? <p>No Research Runs yet.</p> : null}
      <ResearchRunHistory items={items ?? []} />
    </section>
  );
}

export function ResearchRunProgressView({
  active,
  progress,
}: {
  active: boolean;
  progress: ResearchRunProgress;
}) {
  const estimate = progress.remaining_duration_estimate_seconds;
  return (
    <section aria-label="ResearchRun progress">
      <h2>Committed progress</h2>
      <p>Warm-up {progress.completed_warmup_sessions} / {progress.total_warmup_sessions}</p>
      <p>Research {progress.completed_research_sessions} / {progress.total_research_sessions}</p>
      <p>Committed Chunks {progress.committed_chunk_count}</p>
      {active ? <p>Current work is in flight and not yet committed.</p> : null}
      {estimate !== null ? (
        <p>
          About {Math.max(1, Math.ceil(estimate / 60))} minutes remaining
          {progress.duration_is_estimate ? " (revisable estimate, not an SLA)" : ""}.
        </p>
      ) : null}
    </section>
  );
}

export function isTerminalResearch(status: ResearchRun["status"]): boolean {
  return status === "succeeded" || status === "failed" || status === "cancelled";
}

export function UseAsDraftPanel({
  folders,
  input,
  sourceFolderId,
  storage = window.localStorage,
  confirmDiscard = (message) => window.confirm(message),
  navigate = (path) => window.location.assign(path),
}: {
  folders: ResearchFolderOption[];
  input: FrozenResearchAuthorableInput;
  sourceFolderId: string;
  storage?: Pick<Storage, "getItem" | "setItem">;
  confirmDiscard?: (message: string) => boolean;
  navigate?: (path: string) => void;
}) {
  const [targetFolderId, setTargetFolderId] = useState(sourceFolderId);
  const [error, setError] = useState<string | null>(null);

  function useAsDraft(): void {
    setError(null);
    try {
      if (!useResearchAsDraft(storage, targetFolderId, input, confirmDiscard)) return;
      navigate(targetFolderId === "folder_default"
        ? "/research"
        : `/research?folder=${encodeURIComponent(targetFolderId)}`);
    } catch {
      setError("This Research could not be copied into the browser Draft.");
    }
  }

  return (
    <section aria-label="Reuse Research" className="research-use-as-draft">
      <h2>Reuse</h2>
      <p>Copy the frozen research inputs into a browser Draft to inspect or edit them.</p>
      <label>Target Folder
        <select
          aria-label="Target Folder"
          onChange={(event) => setTargetFolderId(event.target.value)}
          value={targetFolderId}
        >
          {folders.map((folder) => (
            <option key={folder.id} value={folder.id}>{folder.name}</option>
          ))}
        </select>
      </label>
      <button onClick={useAsDraft}>Use as Draft</button>
      {error !== null ? <p role="alert">{error}</p> : null}
    </section>
  );
}

export function ResearchFolderLoadFailure({
  error,
  onRetry,
}: {
  error: string;
  onRetry: () => void;
}) {
  return (
    <section aria-label="Research Folder availability">
      <p role="alert">{error}</p>
      <button onClick={onRetry}>Retry Folders</button>
    </section>
  );
}

export function ResearchOrganizationPanel({
  run,
  folders,
  onOrganized,
}: {
  run: ResearchRun;
  folders: ResearchFolderOption[];
  onOrganized: (run: ResearchRun) => void;
}) {
  const [name, setName] = useState(run.name);
  const [folderId, setFolderId] = useState(run.folder_id);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const normalizedName = name.trim();
  const nameChanged = normalizedName !== "" && normalizedName !== run.name;
  const folderChanged = folderId !== run.folder_id;

  async function organize(): Promise<void> {
    if ((!nameChanged && !folderChanged) || submitting) return;
    setSubmitting(true);
    setError(null);
    const body: { name?: string; folder_id?: string } = {};
    if (nameChanged) body.name = normalizedName;
    if (folderChanged) body.folder_id = folderId;
    try {
      const response = await fetch(`/api/research-runs/${run.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        let detail = `Research organization failed (${response.status})`;
        try {
          const payload = (await response.json()) as { detail?: unknown };
          if (typeof payload.detail === "string") detail = payload.detail;
        } catch {
          // The HTTP status remains a sufficient public failure reason.
        }
        throw new Error(detail);
      }
      onOrganized((await response.json()) as ResearchRun);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Research organization failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section aria-label="Research organization" className="research-organization">
      <h2>Organization</h2>
      <label>Research name
        <input
          aria-label="Research name"
          disabled={submitting}
          maxLength={200}
          onChange={(event) => setName(event.target.value)}
          value={name}
        />
      </label>
      <label>Research Folder
        <select
          aria-label="Research Folder"
          disabled={submitting}
          onChange={(event) => setFolderId(event.target.value)}
          value={folderId}
        >
          {folders.map((folder) => (
            <option key={folder.id} value={folder.id}>{folder.name}</option>
          ))}
        </select>
      </label>
      <button
        disabled={submitting || (!nameChanged && !folderChanged)}
        onClick={() => void organize()}
      >
        {submitting ? "Updating…" : "Update organization"}
      </button>
      {error !== null ? <p role="alert">{error}</p> : null}
    </section>
  );
}

export function ResearchRunHistory({ items }: { items: ResearchRun[] }) {
  return (
    <ol aria-label="Research Runs" className="research-run-history">
      {items.map((item) => (
        <li key={item.id}>
          <a href={`/research-runs/${item.id}`}><strong>{item.name}</strong></a>
          <dl>
            <div><dt>Run ID</dt><dd><code>{item.id}</code></dd></div>
            <div><dt>Created</dt><dd><time dateTime={item.created_at}>{item.created_at}</time></dd></div>
            <div><dt>Status</dt><dd>{item.status}</dd></div>
            <div><dt>Research type</dt><dd>{researchKindLabel(item.research_kind)}</dd></div>
            <div><dt>Formula</dt><dd><code>{item.formula_summary}</code></dd></div>
          </dl>
        </li>
      ))}
    </ol>
  );
}

export function ResearchResultView({ result }: { result: ResearchResult }) {
  const strategyResult = "strategy" in result ? result : null;
  return (
    <div className="research-result">
      <section className="research-result-section">
        <div className="section-heading">
          <p className="eyebrow">Predictive evidence</p>
          <h2>Factor Summary</h2>
        </div>
        <div className="factor-horizons">
          {FACTOR_HORIZONS.map((name) => (
            <FactorHorizonView horizon={result.factor.horizons[name]} key={name} />
          ))}
        </div>
      </section>

      {strategyResult !== null ? <section className="research-result-section">
        <div className="section-heading">
          <p className="eyebrow">One fill path · net is primary</p>
          <h2>Strategy Summary</h2>
          <p>Selected universe {strategyResult.strategy.benchmark.universe}</p>
        </div>
        <div className="strategy-metrics">
          <Metric label="Net cumulative" value={formatPercent(strategyResult.strategy.summary.metrics.net_cumulative_return)} />
          <Metric
            label="Benchmark cumulative"
            value={formatPercent(strategyResult.strategy.summary.metrics.benchmark_cumulative_return)}
          />
          <Metric
            label="Annualized excess"
            value={formatPercent(strategyResult.strategy.summary.metrics.annualized_excess_return)}
          />
          <Metric
            label="Maximum drawdown"
            value={formatPercent(strategyResult.strategy.summary.metrics.maximum_drawdown.value)}
          />
          <Metric label="Sharpe" value={formatDecimal(strategyResult.strategy.summary.metrics.sharpe)} />
          <Metric
            label="Transaction costs"
            value={formatCny(strategyResult.strategy.summary.metrics.transaction_costs.cumulative_amount)}
          />
        </div>
        <StrategyBenchmarkChart observations={strategyResult.strategy.observations} />
      </section> : null}

      {strategyResult !== null ? (
        <DailyObservationsTable observations={strategyResult.strategy.observations} />
      ) : null}
      {strategyResult !== null ? (
        <TerminalStrategyStateView state={strategyResult.terminal_strategy_state} />
      ) : null}

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

function DailyObservationsTable({ observations }: { observations: StrategyObservation[] }) {
  return (
    <section className="research-result-section">
      <div className="section-heading">
        <p className="eyebrow">Research-period account observations</p>
        <h2>Daily Observations</h2>
      </div>
      <div className="result-table-scroll">
        <table aria-label="Daily Observations">
          <thead>
            <tr>
              <th>Session</th>
              <th>Net NAV</th>
              <th>Net cash</th>
              <th>Holdings</th>
              <th>Transaction cost</th>
            </tr>
          </thead>
          <tbody>
            {observations.map((observation) => (
              <tr key={observation.session}>
                <td>{observation.session}</td>
                <td>{observation.net_nav}</td>
                <td>{observation.net_cash}</td>
                <td>{observation.holdings_count}</td>
                <td>{observation.transaction_cost_cny}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function TerminalStrategyStateView({ state }: { state: TerminalStrategyState }) {
  return (
    <section className="research-result-section" aria-label="Terminal Strategy State">
      <div className="section-heading">
        <p className="eyebrow">Retained account at the Research Period boundary</p>
        <h2>Terminal Strategy State</h2>
      </div>
      <div className="strategy-metrics">
        <Metric label="Session" value={state.session} />
        <Metric label="Net NAV" value={state.net_nav} />
        <Metric label="Net cash" value={state.net_cash} />
        <Metric label="Holdings" value={String(state.positions.length)} />
        <Metric label="Cumulative costs" value={state.cumulative_transaction_cost} />
      </div>
      {state.positions.length === 0 ? (
        <p>No terminal holdings.</p>
      ) : (
        <div className="result-table-scroll">
          <table aria-label="Terminal holdings">
            <thead>
              <tr><th>Instrument</th><th>Shares</th><th>Adjusted units</th><th>Last price</th></tr>
            </thead>
            <tbody>
              {state.positions.map((position) => (
                <tr key={position.instrument_id}>
                  <td>{position.instrument_id}</td>
                  <td>{position.execution_shares}</td>
                  <td>{position.adjusted_units}</td>
                  <td>{position.last_adjusted_price}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p>
        {state.pending_signal
          ? `Signal from ${state.pending_signal.signal_session} remains pending for the next Research Session open.`
          : "No pending signal at this boundary."}
      </p>
    </section>
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
      <p className="factor-coverage">
        IC coverage {horizon.coverage.ic_valid_session_count}/
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

function researchKindLabel(
  value: ResearchRun["research_kind"],
): "Factor Evaluation" | "Strategy Backtest" {
  return value === "factor_evaluation" ? "Factor Evaluation" : "Strategy Backtest";
}
