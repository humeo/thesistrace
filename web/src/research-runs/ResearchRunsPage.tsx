import {
  CaretDown,
  CaretLeft,
  CaretRight,
  CaretUp,
  CaretUpDown,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { StrategyPerformanceChart } from "../analysis/StrategyPerformanceChart";
import { coreFetch } from "../auth/coreFetch";
import {
  useResearchAsDraft,
  type FrozenResearchAuthorableInput,
} from "../research/draft";
import { followCoreLink } from "../shell/navigation";

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

export type ResearchRunExecutionTiming = {
  started_at: string | null;
  finished_at: string | null;
  elapsed_seconds: number | null;
  is_final: boolean;
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
  key_metrics?: FactorEvaluationKeyMetrics | StrategyBacktestKeyMetrics;
  input?: FrozenResearchAuthorableInput;
  failure_reason?: string;
  result?: ResearchResult;
  progress?: ResearchRunProgress;
  execution_timing?: ResearchRunExecutionTiming;
};

type FactorEvaluationKeyMetrics = {
  research_kind: "factor_evaluation";
  one_session_rank_ic: number | null;
  five_session_rank_ic: number | null;
  twenty_session_rank_ic: number | null;
};

type StrategyBacktestKeyMetrics = {
  research_kind: "strategy_backtest";
  annualized_excess_return: number | null;
  sharpe: number | null;
  maximum_drawdown: number;
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
const RESEARCH_RUN_PAGE_SIZE = 20;
type ResearchKindFilter = "" | ResearchRun["research_kind"];

export function ResearchRunsPage({ researcherId, runId }: {
  researcherId: string;
  runId?: string;
}) {
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [items, setItems] = useState<ResearchRun[] | null>(null);
  const [folders, setFolders] = useState<ResearchFolderOption[]>([]);
  const [folderFilter, setFolderFilter] = useState("");
  const [researchKindFilter, setResearchKindFilter] = useState<ResearchKindFilter>("");
  const [pageIndex, setPageIndex] = useState(0);
  const [pageCursors, setPageCursors] = useState<Array<string | null>>([null]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
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
  const currentPageCursor = pageCursors[pageIndex] ?? null;

  useEffect(() => {
    const controller = new AbortController();
    setFolderError(null);
    void coreFetch("/api/research-folders", { signal: controller.signal })
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
    setLoadState(run === null && items === null ? "loading" : "refreshing");
    const path = runId
      ? `/api/research-runs/${runId}`
      : researchRunListPath({
          cursor: currentPageCursor,
          folderId: folderFilter,
          researchKind: researchKindFilter,
        });

    async function load(polling = false) {
      try {
        const response = await coreFetch(path, { signal: controller.signal });
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
          const payload = (await response.json()) as ResearchRunList;
          const nextItems = payload.items;
          if (generation !== loadGeneration.current) return;
          setItems(nextItems);
          setNextCursor(payload.next_cursor);
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
  }, [currentPageCursor, folderFilter, refreshGeneration, researchKindFilter, runId]);

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

  function resetListPage(): void {
    setItems([]);
    setLoadState("refreshing");
    setPageIndex(0);
    setPageCursors([null]);
    setNextCursor(null);
  }

  function changeFolderFilter(value: string): void {
    setFolderFilter(value);
    resetListPage();
  }

  function changeResearchKindFilter(value: ResearchKindFilter): void {
    setResearchKindFilter(value);
    resetListPage();
  }

  function showPreviousPage(): void {
    if (pageIndex === 0) return;
    setItems([]);
    setLoadState("refreshing");
    setNextCursor(null);
    setPageIndex((current) => current - 1);
  }

  function showNextPage(): void {
    if (nextCursor === null) return;
    setItems([]);
    setLoadState("refreshing");
    setPageCursors((current) => [
      ...current.slice(0, pageIndex + 1),
      nextCursor,
    ]);
    setNextCursor(null);
    setPageIndex((current) => current + 1);
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
      const response = await coreFetch(`/api/research-runs/${targetRun.id}/cancel`, {
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
      const response = await coreFetch(`/api/research-runs/${targetRun.id}/daily-tracks`, {
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
      const response = await coreFetch(`/api/research-runs/${run.id}`, {
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
      <section aria-label="Research Runs" className="state-section">
        <h1>ResearchRun</h1>
        <p role="alert">{error}</p>
        <button onClick={refresh}>Retry</button>
      </section>
    );
  }
  if (runId && run?.id !== runId) {
    return <section aria-label="Research Runs" className="state-section"><p>Loading ResearchRun…</p></section>;
  }
  if (!runId && items === null) {
    return <section aria-label="Research Runs" className="state-section"><p>Loading Research Runs…</p></section>;
  }
  if (runId && run?.id === runId) {
    const terminal = isTerminalResearch(run.status);
    const progressView = run.progress ? (
      <ResearchRunProgressView
        progress={run.progress}
        status={run.status}
        timing={run.execution_timing}
      />
    ) : null;
    return (
      <section aria-label="Research Runs" className="research-run-page">
        <header className="research-run-header">
          <div>
            <p className="eyebrow">Immutable research execution</p>
            <h1>ResearchRun</h1>
          </div>
          <div>
            <ResearchRunBackLink />
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
        <ResearchRunFacts run={run} />
        {!terminal ? progressView : null}
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
        {run.status === "failed" && run.failure_reason ? (
          <p role="alert"><strong>Failure</strong> {run.failure_reason}</p>
        ) : null}
        {run.status === "succeeded" && run.result ? (
          <ResearchResultView result={run.result} />
        ) : null}
        {terminal ? progressView : null}
        {!deleting && folders.length > 0 && run.input !== undefined ? (
          <UseAsDraftPanel
            folders={folders}
            input={run.input}
            researcherId={researcherId}
            sourceFolderId={run.folder_id}
          />
        ) : null}
      </section>
    );
  }
  return (
    <section aria-label="Research Runs" className="research-runs-list-page">
      <header className="page-header">
        <h1>Research Runs</h1>
      </header>
      <div className="research-run-list-toolbar">
        <div className="research-run-filters">
          {folderError !== null ? (
            <ResearchFolderLoadFailure error={folderError} onRetry={refreshFolders} />
          ) : folders.length === 0 ? (
            <p role="status">Loading Research Folders…</p>
          ) : (
            <label>Folder
              <select
                aria-label="Filter by Folder"
                onChange={(event) => changeFolderFilter(event.target.value)}
                value={folderFilter}
              >
                <option value="">All Folders</option>
                {folders.map((folder) => (
                  <option key={folder.id} value={folder.id}>{folder.name}</option>
                ))}
              </select>
            </label>
          )}
          <label>Type
            <select
              aria-label="Filter by Type"
              onChange={(event) => changeResearchKindFilter(
                event.target.value as ResearchKindFilter,
              )}
              value={researchKindFilter}
            >
              <option value="">All Types</option>
              <option value="factor_evaluation">Factor Evaluation</option>
              <option value="strategy_backtest">Strategy Backtest</option>
            </select>
          </label>
        </div>
      </div>
      {loadState === "refreshing" ? (
        <p className="research-run-list-status" role="status">Loading Research Runs…</p>
      ) : null}
      {loadState === null && items?.length === 0 ? (
        <p className="research-run-list-empty">No Research Runs match these filters.</p>
      ) : null}
      <ResearchRunHistory
        items={items ?? []}
        key={researchKindFilter || "all"}
        researchKind={researchKindFilter}
      />
      <ResearchRunPagination
        hasNextPage={nextCursor !== null}
        onNextPage={showNextPage}
        onPreviousPage={showPreviousPage}
        pageIndex={pageIndex}
      />
    </section>
  );
}

export function ResearchRunBackLink() {
  return (
    <a className="button button-quiet" href="/research-runs" onClick={followCoreLink}>
      <CaretLeft aria-hidden="true" size={13} weight="bold" />
      Back to Research Runs
    </a>
  );
}

export function researchRunListPath({
  cursor,
  folderId,
  researchKind,
}: {
  cursor: string | null;
  folderId: string;
  researchKind: ResearchKindFilter;
}): string {
  const parameters = new URLSearchParams({ limit: String(RESEARCH_RUN_PAGE_SIZE) });
  if (folderId !== "") parameters.set("folder_id", folderId);
  if (researchKind !== "") parameters.set("research_kind", researchKind);
  if (cursor !== null) parameters.set("cursor", cursor);
  return `/api/research-runs?${parameters.toString()}`;
}

export function ResearchRunPagination({
  hasNextPage,
  onNextPage,
  onPreviousPage,
  pageIndex,
}: {
  hasNextPage: boolean;
  onNextPage: () => void;
  onPreviousPage: () => void;
  pageIndex: number;
}) {
  return (
    <nav aria-label="Research Runs pages" className="research-run-pagination">
      <button disabled={pageIndex === 0} onClick={onPreviousPage} type="button">
        <CaretLeft aria-hidden="true" size={13} weight="bold" />
        Previous
      </button>
      <span>Page {pageIndex + 1}</span>
      <button disabled={!hasNextPage} onClick={onNextPage} type="button">
        Next
        <CaretRight aria-hidden="true" size={13} weight="bold" />
      </button>
    </nav>
  );
}

export function ResearchRunProgressView({
  progress,
  status,
  timing,
}: {
  progress: ResearchRunProgress;
  status: ResearchRun["status"];
  timing?: ResearchRunExecutionTiming;
}) {
  const estimate = progress.remaining_duration_estimate_seconds;
  const completed = progress.completed_warmup_sessions + progress.completed_research_sessions;
  const total = progress.total_warmup_sessions + progress.total_research_sessions;
  const active = status === "running" || status === "cancelling";
  const progressPercentage = total === 0 ? 0 : Math.round((completed / total) * 100);
  return (
    <section aria-label="ResearchRun progress" className="research-run-progress">
      <header className="research-run-progress-heading">
        <div className="research-run-progress-title">
          <h2>Execution progress</h2>
          <span className="research-run-progress-state" data-status={status}>
            {progressLabel(status, progress.phase)}
          </span>
        </div>
        <dl className="research-run-duration">
          <div>
            <dt>{timing?.is_final ? "Execution time" : "Elapsed"}</dt>
            <dd>{formatDuration(timing?.elapsed_seconds ?? null)}</dd>
          </div>
        </dl>
      </header>
      <div className="research-run-progress-track">
        <progress
          aria-label="Research execution progress"
          max={Math.max(total, 1)}
          value={completed}
        />
        <span aria-hidden="true">{progressPercentage}%</span>
      </div>
      <div className="research-run-progress-ledger">
        <dl className="research-run-progress-stats">
          <div>
            <dt>Research sessions</dt>
            <dd>{progress.completed_research_sessions} / {progress.total_research_sessions}</dd>
          </div>
        </dl>
        <dl className="research-run-timing">
          <div>
            <dt>Started</dt>
            <dd><ExecutionTimestamp value={timing?.started_at ?? null} /></dd>
          </div>
          <div>
            <dt>Finished</dt>
            <dd><ExecutionTimestamp value={timing?.finished_at ?? null} /></dd>
          </div>
        </dl>
      </div>
      {active && estimate !== null ? (
        <p className="research-run-progress-note">
          About {formatDuration(estimate)} remaining
          {progress.duration_is_estimate ? " (estimate may change)" : ""}
        </p>
      ) : null}
    </section>
  );
}

export function ResearchRunFacts({ run }: { run: ResearchRun }) {
  const input = run.input;
  const factorConditionClass = input?.research_kind === "factor_evaluation"
    ? "research-run-fact-half"
    : undefined;
  return (
    <div
      aria-label="Research execution conditions"
      className="research-run-facts research-run-execution-facts"
      role="group"
    >
      <p><strong>Status</strong> {run.status}</p>
      <p><strong>Research type</strong> {researchKindLabel(run.research_kind)}</p>
      <p className="research-run-fact-name"><strong>Name</strong> {run.name}</p>
      <p className="research-run-fact-formula">
        <strong>Formula</strong> <code>{input?.formula ?? run.formula_summary}</code>
      </p>
      <p className="research-run-fact-period">
        <strong>Research period</strong> {run.start_date} to {run.end_date}
      </p>
      {input !== undefined ? (
        <>
          <p className={factorConditionClass}>
            <strong>Universe</strong> {universeLabel(input.universe)}
          </p>
          <p className={factorConditionClass}>
            <strong>Neutralization</strong> {neutralizationLabel(input.neutralization)}
          </p>
          {input.research_kind === "strategy_backtest" ? (
            <>
              <p><strong>Holdings count</strong> {input.holdings_count}</p>
              <p>
                <strong>Rebalance</strong>{" "}
                {rebalanceLabel(input.rebalance_every_sessions)}
              </p>
            </>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function progressLabel(
  status: ResearchRun["status"],
  phase: ResearchRunProgress["phase"],
): string {
  if (status === "queued") return "Waiting for a Research Worker";
  if (status === "cancelling") return "Cancelling execution";
  if (status === "cancelled") return "Execution cancelled";
  if (status === "failed") return "Execution failed";
  if (status === "succeeded") return "Execution complete";
  return phase === "finalizing" ? "Finalizing result" : `Running ${phase}`;
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "Not started";
  const rounded = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const remainder = rounded % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${remainder}s`;
  if (minutes > 0) return `${minutes}m ${remainder}s`;
  return `${remainder}s`;
}

function ExecutionTimestamp({ value }: { value: string | null }) {
  if (value === null) return <>Not available</>;
  const timestamp = new Date(value);
  if (!Number.isFinite(timestamp.getTime())) return <>Not available</>;
  const iso = timestamp.toISOString();
  return <time dateTime={value}>{iso.slice(0, 10)} {iso.slice(11, 19)} UTC</time>;
}

export function isTerminalResearch(status: ResearchRun["status"]): boolean {
  return status === "succeeded" || status === "failed" || status === "cancelled";
}

export function UseAsDraftPanel({
  folders,
  input,
  researcherId,
  sourceFolderId,
  storage = window.localStorage,
  confirmDiscard = (message) => window.confirm(message),
  navigate = (path) => window.location.assign(path),
}: {
  folders: ResearchFolderOption[];
  input: FrozenResearchAuthorableInput;
  researcherId: string;
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
      if (!useResearchAsDraft(
        storage,
        researcherId,
        targetFolderId,
        input,
        confirmDiscard,
      )) return;
      navigate(targetFolderId === "folder_default"
        ? "/research"
        : `/research?folder=${encodeURIComponent(targetFolderId)}`);
    } catch {
      setError("This Research could not be copied into the browser Draft.");
    }
  }

  return (
    <section aria-label="Create a draft" className="research-use-as-draft">
      <h2>Create a draft</h2>
      <p>Copy this Run’s frozen inputs into a browser draft to inspect or edit.</p>
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
      <button onClick={useAsDraft}>Create draft</button>
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
      const response = await coreFetch(`/api/research-runs/${run.id}`, {
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
    <section aria-label="Name and folder" className="research-organization">
      <h2>Name and folder</h2>
      <label>Research name
        <input
          aria-label="Research name"
          disabled={submitting}
          maxLength={200}
          onChange={(event) => setName(event.target.value)}
          value={name}
        />
      </label>
      <label>Folder
        <select
          aria-label="Folder"
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
        {submitting ? "Saving…" : "Save changes"}
      </button>
      {error !== null ? <p role="alert">{error}</p> : null}
    </section>
  );
}

export type ResearchRunSortKey =
  | "created_at"
  | "annualized_excess_return"
  | "sharpe"
  | "maximum_drawdown"
  | "one_session_rank_ic"
  | "five_session_rank_ic"
  | "twenty_session_rank_ic";
type ResearchRunSortDirection = "ascending" | "descending";
type ResearchRunSort = {
  key: ResearchRunSortKey;
  direction: ResearchRunSortDirection;
};
type ResearchRunMetricColumn = {
  key: Exclude<ResearchRunSortKey, "created_at">;
  label: string;
  shortLabel: string;
};

const DEFAULT_RESEARCH_RUN_SORT: ResearchRunSort = {
  key: "created_at",
  direction: "descending",
};

const FACTOR_RESEARCH_RUN_METRICS: ResearchRunMetricColumn[] = [
  { key: "one_session_rank_ic", label: "1-session Rank IC", shortLabel: "1S Rank IC" },
  { key: "five_session_rank_ic", label: "5-session Rank IC", shortLabel: "5S Rank IC" },
  { key: "twenty_session_rank_ic", label: "20-session Rank IC", shortLabel: "20S Rank IC" },
];

const STRATEGY_RESEARCH_RUN_METRICS: ResearchRunMetricColumn[] = [
  {
    key: "annualized_excess_return",
    label: "Annualized excess",
    shortLabel: "Excess",
  },
  { key: "sharpe", label: "Sharpe", shortLabel: "Sharpe" },
  { key: "maximum_drawdown", label: "Max drawdown", shortLabel: "Drawdown" },
];

export function ResearchRunHistory({
  items,
  researchKind = "",
}: {
  items: ResearchRun[];
  researchKind?: ResearchKindFilter;
}) {
  const [sort, setSort] = useState<ResearchRunSort>(DEFAULT_RESEARCH_RUN_SORT);
  const metricColumns = researchRunMetricColumns(researchKind);
  const sortedItems = useMemo(
    () => sortResearchRuns(items, sort.key, sort.direction),
    [items, sort.direction, sort.key],
  );

  function changeSort(key: ResearchRunSortKey) {
    setSort((current) => {
      if (current.key === key) {
        return {
          key,
          direction: current.direction === "ascending" ? "descending" : "ascending",
        };
      }
      return {
        key,
        direction: defaultResearchRunSortDirection(key),
      };
    });
  }

  function selectSort(key: ResearchRunSortKey) {
    setSort({
      key,
      direction: defaultResearchRunSortDirection(key),
    });
  }

  function toggleSortDirection() {
    setSort((current) => ({
      ...current,
      direction: current.direction === "ascending" ? "descending" : "ascending",
    }));
  }

  const MobileSortIcon = sort.direction === "ascending" ? CaretUp : CaretDown;

  return (
    <div className="research-run-history-container">
      <div className="research-run-mobile-sort">
        <label>Sort by
          <select
            aria-label="Sort Research Runs by"
            onChange={(event) => selectSort(event.target.value as ResearchRunSortKey)}
            value={sort.key}
          >
            <option value="created_at">Created</option>
            {metricColumns.map((column) => (
              <option key={column.key} value={column.key}>{column.label}</option>
            ))}
          </select>
        </label>
        <button
          aria-label={`Sort ${sort.direction}`}
          onClick={toggleSortDirection}
          type="button"
        >
          <MobileSortIcon aria-hidden="true" size={14} weight="bold" />
          {sort.direction === "ascending" ? "Ascending" : "Descending"}
        </button>
      </div>
      <div className="research-run-history-scroll">
      <table aria-label="Research Runs" className="research-run-history">
        <colgroup>
          <col className="research-run-col-name" />
          <col className="research-run-col-type" />
          <col className="research-run-col-created" />
          <col className="research-run-col-status" />
          {metricColumns.length === 0 ? (
            <col className="research-run-col-summary" />
          ) : metricColumns.map((column) => (
            <col className="research-run-col-metric" key={column.key} />
          ))}
        </colgroup>
        <thead>
          <tr>
            <th scope="col">Research</th>
            <th scope="col">Type</th>
            <SortableResearchRunHeading
              direction={sort.direction}
              isActive={sort.key === "created_at"}
              label="Created (UTC)"
              onSort={() => changeSort("created_at")}
            />
            <th scope="col">Status</th>
            {metricColumns.length === 0 ? (
              <th className="research-run-metric-heading" scope="col">Result summary</th>
            ) : metricColumns.map((column) => (
              <SortableResearchRunHeading
                direction={sort.direction}
                isActive={sort.key === column.key}
                key={column.key}
                label={column.label}
                onSort={() => changeSort(column.key)}
              />
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedItems.map((item) => (
            <tr key={item.id}>
              <th scope="row">
                <a href={`/research-runs/${item.id}`} onClick={followCoreLink}>{item.name}</a>
              </th>
              <td data-label="Type">{researchKindLabel(item.research_kind)}</td>
              <td data-label="Created (UTC)">
                <time dateTime={item.created_at}>{formatResearchRunCreatedAt(item.created_at)}</time>
              </td>
              <td data-label="Status"><span className={`run-status run-status-${item.status}`}>{item.status}</span></td>
              {metricColumns.length === 0 ? (
                <ResearchRunResultSummary item={item} />
              ) : metricColumns.map((column) => (
                <td className="research-run-metric" data-label={column.label} key={column.key}>
                  {formatResearchRunMetric(item, column.key)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}

function ResearchRunResultSummary({ item }: { item: ResearchRun }) {
  const columns = item.research_kind === "factor_evaluation"
    ? FACTOR_RESEARCH_RUN_METRICS
    : STRATEGY_RESEARCH_RUN_METRICS;
  return (
    <td className="research-run-result-summary" data-label="Result summary">
      <div>
        {columns.map((column) => (
          <span key={column.key}>
            <small>{column.shortLabel}</small>
            <strong>{formatResearchRunMetric(item, column.key)}</strong>
          </span>
        ))}
      </div>
    </td>
  );
}

function researchRunMetricColumns(
  researchKind: ResearchKindFilter,
): ResearchRunMetricColumn[] {
  if (researchKind === "factor_evaluation") return FACTOR_RESEARCH_RUN_METRICS;
  if (researchKind === "strategy_backtest") return STRATEGY_RESEARCH_RUN_METRICS;
  return [];
}

function defaultResearchRunSortDirection(
  key: ResearchRunSortKey,
): ResearchRunSortDirection {
  return key === "maximum_drawdown" ? "ascending" : "descending";
}

function SortableResearchRunHeading({
  direction,
  isActive,
  label,
  onSort,
}: {
  direction: ResearchRunSortDirection;
  isActive: boolean;
  label: string;
  onSort: () => void;
}) {
  const Icon = isActive
    ? direction === "ascending" ? CaretUp : CaretDown
    : CaretUpDown;
  return (
    <th aria-sort={isActive ? direction : "none"} scope="col">
      <button className="research-run-sort" onClick={onSort} type="button">
        {label}
        <Icon aria-hidden="true" size={12} weight="bold" />
      </button>
    </th>
  );
}

export function formatResearchRunCreatedAt(value: string): string {
  const timestamp = new Date(value);
  if (!Number.isFinite(timestamp.getTime())) return "Not available";
  const iso = timestamp.toISOString();
  return `${iso.slice(0, 10)} ${iso.slice(11, 19)}`;
}

export function sortResearchRuns(
  items: ResearchRun[],
  key: ResearchRunSortKey,
  direction: ResearchRunSortDirection,
): ResearchRun[] {
  return [...items].sort((left, right) => {
    const leftValue = researchRunSortValue(left, key);
    const rightValue = researchRunSortValue(right, key);
    if (leftValue === null && rightValue === null) return compareCreatedDescending(left, right);
    if (leftValue === null) return 1;
    if (rightValue === null) return -1;
    const comparison = leftValue - rightValue;
    if (comparison === 0) return compareCreatedDescending(left, right);
    return direction === "ascending" ? comparison : -comparison;
  });
}

function researchRunSortValue(item: ResearchRun, key: ResearchRunSortKey): number | null {
  if (key === "created_at") {
    const value = new Date(item.created_at).getTime();
    return Number.isFinite(value) ? value : null;
  }
  const metrics = item.key_metrics;
  if (key === "annualized_excess_return" || key === "sharpe" || key === "maximum_drawdown") {
    return metrics?.research_kind === "strategy_backtest" ? metrics[key] : null;
  }
  return metrics?.research_kind === "factor_evaluation" ? metrics[key] : null;
}

function formatResearchRunMetric(
  item: ResearchRun,
  key: Exclude<ResearchRunSortKey, "created_at">,
): string {
  const value = researchRunSortValue(item, key);
  if (key === "annualized_excess_return") return formatSignedPercent(value);
  if (key === "maximum_drawdown") return formatPercent(value);
  return formatDecimal(value);
}

function compareCreatedDescending(left: ResearchRun, right: ResearchRun): number {
  const comparison = new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
  return comparison === 0 ? left.id.localeCompare(right.id) : comparison;
}

export function ResearchResultView({ result }: { result: ResearchResult }) {
  const strategyResult = "strategy" in result ? result : null;
  return (
    <div className="research-result">
      <section className="research-result-section">
        <div className="section-heading">
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
        <StrategyPerformanceChart observations={strategyResult.strategy.observations} />
      </section> : null}

      {strategyResult !== null ? (
        <TerminalStrategyStateView state={strategyResult.terminal_strategy_state} />
      ) : null}
    </div>
  );
}

export function TerminalStrategyStateView({ state }: { state: TerminalStrategyState }) {
  return (
    <section className="research-result-section" aria-label="Final Portfolio">
      <div className="section-heading">
        <h2>Final Portfolio</h2>
      </div>
      <div className="strategy-metrics">
        <Metric label="As of" value={state.session} />
        <Metric
          label="Portfolio value"
          value={formatCnyDecimal(state.net_nav)}
          exactValue={state.net_nav}
        />
        <Metric
          label="Cash"
          value={formatCnyDecimal(state.net_cash)}
          exactValue={state.net_cash}
        />
        <Metric label="Positions" value={String(state.positions.length)} />
        <Metric
          label="Transaction costs"
          value={formatCnyDecimal(state.cumulative_transaction_cost)}
          exactValue={state.cumulative_transaction_cost}
        />
      </div>
      {state.positions.length === 0 ? (
        <p>No holdings at the end of the Research Period.</p>
      ) : (
        <div className="result-table-scroll">
          <table aria-label="Final holdings">
            <thead>
              <tr><th>Instrument</th><th>Shares</th><th>Adjusted units</th><th>Last price</th></tr>
            </thead>
            <tbody>
              {state.positions.map((position) => (
                <tr key={position.instrument_id}>
                  <td>{position.instrument_id}</td>
                  <td>{position.execution_shares}</td>
                  <td title={position.adjusted_units}>{formatNumericString(position.adjusted_units)}</td>
                  <td title={position.last_adjusted_price}>{formatNumericString(position.last_adjusted_price)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {state.pending_signal ? (
        <p>
          Signal from {state.pending_signal.signal_session} remains pending for the next Research Session open.
        </p>
      ) : null}
    </section>
  );
}

function FactorHorizonView({ horizon }: { horizon: FactorHorizon }) {
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
      <p className="factor-coverage">
        IC coverage {horizon.coverage.ic_valid_session_count}/
        {horizon.coverage.signal_session_count}
      </p>
    </section>
  );
}

function Metric({ label, value, exactValue }: { label: string; value: string; exactValue?: string }) {
  return (
    <div className="result-metric">
      <span>{label}</span>
      <strong title={exactValue}>{value}</strong>
    </div>
  );
}

function formatPercent(value: number | null) {
  return value === null ? "Not available" : `${(value * 100).toFixed(2)}%`;
}

function formatSignedPercent(value: number | null) {
  if (value === null) return "Not available";
  const percent = value * 100;
  return `${percent > 0 ? "+" : ""}${percent.toFixed(2)}%`;
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
function researchKindLabel(
  value: ResearchRun["research_kind"],
): "Factor Evaluation" | "Strategy Backtest" {
  return value === "factor_evaluation" ? "Factor Evaluation" : "Strategy Backtest";
}

function universeLabel(value: FrozenResearchAuthorableInput["universe"]): string {
  return {
    top300: "Top 300",
    top1000: "Top 1000",
    top2000: "Top 2000",
    top3000: "Top 3000",
  }[value];
}

function neutralizationLabel(
  value: FrozenResearchAuthorableInput["neutralization"],
): string {
  return value === "none" ? "None" : "Industry";
}

function rebalanceLabel(sessions: number): string {
  return sessions === 1 ? "Every session" : `Every ${sessions} sessions`;
}

function formatCnyDecimal(value: string) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "CNY",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value));
}

function formatNumericString(value: string) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  if (numeric !== 0 && Math.abs(numeric) < 0.000001) return numeric.toExponential(6);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 }).format(numeric);
}
