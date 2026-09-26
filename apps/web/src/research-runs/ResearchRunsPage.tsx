import type { ParseKeys } from "i18next";
import { Trans } from "react-i18next";
import { catalogLabel } from "../i18n/catalog";
import { formatDecimal, formatDuration, formatNumber, formatPercent, formatUtcTimestamp } from "../i18n/format";
import { folderDisplayName } from "../research/folders";
import { formatRunError, formatExecutionFailure, readOrganizationError, type OrganizationError, type RunError, type HttpActionError } from "./errors";
export { formatDuration } from "../i18n/format";
import { i18n, useTranslation } from "../i18n";
import { CloseRiskFacts } from "../analysis/CloseRiskFacts";
import { CurrentDataRerunOrigin, type RerunOrigin } from "../analysis/CurrentDataRerun";
import { DailyHoldings } from "../analysis/DailyHoldings";
import { StrategyEvents } from "../analysis/StrategyEvents";
import { SelectionEligibilityView } from "../research/SelectionEligibility";
import { isBuiltinFrameworkState, strategySelection, type StrategyDecisionState } from "../research/strategyDecisionState";
import { FrameworkStateView } from "../research/FrameworkStateView";
import { FrozenFrameworkModules, FrozenPythonProgram, FrozenSimulationCosts } from "../research/FrozenStrategyDefinition";
import {
  CaretDown,
  CaretLeft,
  CaretRight,
  CaretUp,
  CaretUpDown,
  CheckCircle,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";

import { FactorEvidence } from "../analysis/FactorEvidence";
import { CommonInputObservations } from "../analysis/CommonInputObservations";
import { coreFetch } from "../auth/coreFetch";
import { StrategyComparisonPanel } from "../analysis/StrategyComparisonPanel";
import { MetricHelp, type MetricHelpContent } from "../analysis/MetricHelp";
import type { StrategyComparison } from "../analysis/strategyComparison";
import {
  useResearchAsDraft,
  type FrozenResearchAuthorableInput,
} from "../research/draft";
import { followCoreLink } from "../shell/navigation";
import { strategyMetricHelp } from "./metricHelp";
import { ResearchBatchCancelButton } from "./ResearchBatchesPage";
import { ResearchRunsNavigation } from "./ResearchRunsNavigation";
import { useResearchRunDetailController } from "./useResearchRunDetailController";
import { Page, PageContent, PageHeader, Section } from "../components/layout/Page";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Field, FieldGroup, FieldLabel } from "../components/ui/field";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../components/ui/collapsible";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Badge } from "../components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { FactorResultView } from "./FactorResultView";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "../components/ui/alert-dialog";

type CorrelationSummary = {
  mean: number | null;
  sample_deviation: number | null;
  icir: number | null;
  positive_fraction: number | null;
  valid_session_count: number;
};

export type FactorHorizon = {
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
  close_risk_nav_cny: string;
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
  benchmark_cumulative_return: number | null;
  benchmark_cagr: number | null;
  annualized_excess_return: number | null;
  maximum_drawdown: { value: number | null };
  sharpe: number | null;
  transaction_costs: { ratio: number };
};

export type TerminalStrategyState = {
  decision_state: StrategyDecisionState;
  contract_checksum: string;
  session: string;
  gross_cash: string;
  net_cash: string;
  gross_nav: string;
  net_nav: string;
  close_risk_nav_cny: string;
  cumulative_transaction_cost: string;
  positions: Array<{
    instrument_id: string;
    execution_shares: number;
    adjusted_units: string;
    last_adjusted_price: string;
    last_close_adjusted_price: string;
    remaining_acquisition_cost_cny: string;
    holding_cycle_started_session: string;
    holding_age: number;
  }>;
  research_phase: {
    origin_session: string;
    report_session_count: number;
  };
  pending_target: {
    decision_session: string;
    reason: string;
    contract_checksum: string;
    allocation: {
      mode: "rebalance" | "reduce" | "increase";
      instrument_ids: string[];
      relative_weights: Record<string, string>;
      exposure: number;
    } | null;
    position_limits: Record<string, number>;
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

export type FactorEvaluationResearchResult = {
  factor: { horizons: Record<"1" | "5" | "20", FactorHorizon> };
  provenance: ResearchResultProvenance & {
    research_kind: "factor_evaluation";
  };
};

type StrategyBacktestResearchResult = {
  strategy: {
    summary: {
      alpha_checksum: string | null;
      entry_session: string | null;
      initial_cash_cny: string;
      source_checksum: string;
      metrics: StrategyMetrics;
    };
    observations: StrategyObservation[];
    comparison: StrategyComparison;
  };
  terminal_strategy_state: TerminalStrategyState;
  provenance: ResearchResultProvenance & {
    research_kind: "strategy_backtest";
  };
};

export type ResearchResult = FactorEvaluationResearchResult | StrategyBacktestResearchResult;

export type ResearchRunProgress = {
  phase: "queued" | "preparing_data" | "shared_alpha_factor" | "waiting_for_execution"
    | "warmup" | "research" | "strategy" | "finalizing" | "recovering" | "succeeded";
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
  batch_id?: string | null;
  rerun_origin?: RerunOrigin;
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

type ResearchRunList = { items: ResearchRun[]; total_count: number };
export type ResearchFolderOption = {
  id: string;
  name: string;
  is_default: boolean;
};
type ResearchFolderList = { items: ResearchFolderOption[]; next_cursor: null };
type LoadState = "loading" | "refreshing" | null;
const RESEARCH_RUN_PAGE_SIZE = 20;
type ResearchKindFilter = "" | ResearchRun["research_kind"];

export function ResearchRunsPage({ researcherId, runId }: {
  researcherId: string;
  runId?: string;
}) {
  const { t } = useTranslation("runs");
  const detail = useResearchRunDetailController(runId);
  const {
    run, setRun, canceling, cancelError, startingTracking, deleting,
    deleteDialogOpen, deleteError, deleteTrigger, cancel, startTracking,
    openDeleteDialog, closeDeleteDialog, performResearchDeletion,
  } = detail;
  const [items, setItems] = useState<ResearchRun[] | null>(null);
  const [folders, setFolders] = useState<ResearchFolderOption[]>([]);
  const [folderFilter, setFolderFilter] = useState("");
  const [researchKindFilter, setResearchKindFilter] = useState<ResearchKindFilter>("");
  const [pageIndex, setPageIndex] = useState(0);
  const [sort, setSort] = useState<ResearchRunSort>(DEFAULT_RESEARCH_RUN_SORT);
  const [metricFilters, setMetricFilters] = useState<ResearchMetricFilter[]>([]);
  const [totalCount, setTotalCount] = useState<number | null>(null);
  const [folderError, setFolderError] = useState<"folderError" | null>(null);
  const [error, setError] = useState<RunError | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [refreshGeneration, setRefreshGeneration] = useState(0);
  const [folderRefreshGeneration, setFolderRefreshGeneration] = useState(0);
  const loadGeneration = useRef(0);

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
        setFolderError("folderError");
      });
    return () => controller.abort();
  }, [folderRefreshGeneration]);

  useEffect(() => {
    if (runId !== undefined) return;
    const controller = new AbortController();
    const generation = ++loadGeneration.current;
    let timeout: number | undefined;
    setError(null);
    setLoadState(items === null ? "loading" : "refreshing");
    const path = researchRunListPath({
      page: pageIndex + 1,
      sort,
      metricFilters,
      folderId: folderFilter,
      researchKind: researchKindFilter,
    });

    async function load(polling = false) {
      try {
        const response = await coreFetch(path, { signal: controller.signal });
        if (!response.ok) throw new Error("ResearchRun unavailable");
        if (generation !== loadGeneration.current) return;
        const payload = (await response.json()) as ResearchRunList;
        const nextItems = payload.items;
        if (generation !== loadGeneration.current) return;
        setItems(nextItems);
        setTotalCount(payload.total_count);
        const lastPageIndex = Math.max(0, Math.ceil(payload.total_count / RESEARCH_RUN_PAGE_SIZE) - 1);
        if (pageIndex > lastPageIndex) setPageIndex(lastPageIndex);
        if (nextItems.some((item) => ["queued", "running", "cancelling"].includes(item.status))) {
          timeout = window.setTimeout(() => void load(true), 500);
        }
        if (!polling) setLoadState(null);
      } catch (reason: unknown) {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        if (generation !== loadGeneration.current) return;
        setLoadState(null);
        setError({ code: "loadError" });
      }
    }

    void load();
    return () => {
      if (generation === loadGeneration.current) loadGeneration.current += 1;
      if (timeout !== undefined) window.clearTimeout(timeout);
      controller.abort();
    };
  }, [pageIndex, folderFilter, refreshGeneration, researchKindFilter, runId, sort, metricFilters]);

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
    setTotalCount(null);
  }

  function changeSort(value: ResearchRunSort): void {
    setSort(value);
    resetListPage();
  }

  function changeFolderFilter(value: string): void {
    setFolderFilter(value);
    resetListPage();
  }

  function changeResearchKindFilter(value: ResearchKindFilter): void {
    setResearchKindFilter(value);
    setMetricFilters([]);
    setSort(DEFAULT_RESEARCH_RUN_SORT);
    resetListPage();
  }

  function showPreviousPage(): void {
    if (pageIndex === 0) return;
    setItems([]);
    setLoadState("refreshing");
    setPageIndex((current) => current - 1);
  }

  function showNextPage(): void {
    if (totalCount === null || (pageIndex + 1) * RESEARCH_RUN_PAGE_SIZE >= totalCount) return;
    setItems([]);
    setLoadState("refreshing");
    setPageIndex((current) => current + 1);
  }

  const visibleError = runId === undefined ? error : detail.error;
  if (visibleError) {
    return (
      <section aria-label={t("title")} className="state-section">
        <h1>{t("run")}</h1>
        <p role="alert">{formatRunError(visibleError)}</p>
        <div className="flex flex-wrap gap-2">
          {runId !== undefined ? <ResearchRunBackLink /> : null}
          <Button variant="outline" onClick={runId === undefined ? refresh : detail.refresh}>{t("retry")}</Button>
        </div>
      </section>
    );
  }
  if (runId && run?.id !== runId) {
    return <section aria-label={t("title")} className="state-section"><p>{t("loadingRun")}</p></section>;
  }
  if (!runId && items === null) {
    return <section aria-label={t("title")} className="state-section"><p>{t("loadingRuns")}</p></section>;
  }
  if (runId && run?.id === runId) {
    if (run.research_kind === "factor_evaluation") {
      return <FactorRunDetail
        detail={detail}
        folderError={folderError}
        folders={folders}
        onRefreshFolders={refreshFolders}
        researcherId={researcherId}
        run={run}
      />;
    }
    const terminal = isTerminalResearch(run.status);
    const progressView = run.progress ? (
      <ResearchRunProgressView
        progress={run.progress}
        status={run.status}
        timing={run.execution_timing}
      />
    ) : null;
    return (
      <section aria-label={t("title")} className="research-run-page">
        <header className="research-run-header">
          <div>
            <h1>{t("run")}</h1>
          </div>
          <div>
            <ResearchRunBackLink />
            {run.batch_id ? <a className="button button-quiet" href={`/research-runs/batches/${encodeURIComponent(run.batch_id)}`} onClick={followCoreLink}>{t("viewBatch")}</a> : null}
            {run.batch_id && ["queued", "running", "cancelling"].includes(run.status) ? (
              <ResearchBatchCancelButton key={run.batch_id} batchId={run.batch_id} status={run.status} />
            ) : null}
            {!run.batch_id && (run.status === "queued" || run.status === "running") ? (
              <button disabled={canceling} onClick={() => void cancel()}>
                {t(canceling ? "cancelling" : "cancel")}
              </button>
            ) : null}
            {run.status === "succeeded" && run.research_kind === "strategy_backtest" ? (
              <button
                disabled={startingTracking || deleting}
                onClick={() => void startTracking()}
              >
                {t(startingTracking ? "startingTracking" : "startTracking")}
              </button>
            ) : null}
            {isTerminalResearch(run.status) ? (
              <button
                aria-controls="research-delete-dialog"
                aria-expanded={deleteDialogOpen}
                aria-haspopup="dialog"
                disabled={deleting || startingTracking}
                onClick={openDeleteDialog}
                ref={deleteTrigger}
              >
                {t(deleting ? "deleting" : "delete")}
              </button>
            ) : null}
          </div>
        </header>
        {cancelError !== null ? (
          <p className="inline-status inline-status-error" role="alert">{t(cancelError)}</p>
        ) : null}
        <ResearchDeleteDialog
          deleting={deleting}
          error={deleteError}
          name={run.name}
          onConfirm={() => void performResearchDeletion()}
          onDismiss={closeDeleteDialog}
          open={deleteDialogOpen}
        />
        {detail.loadState === "refreshing" ? (
          <p role="status">{t("refreshingRun")}</p>
        ) : null}
        <ResearchRunFacts run={run} />
        {run.rerun_origin && <CurrentDataRerunOrigin origin={run.rerun_origin} />}
        {!terminal ? progressView : null}
        {deleting ? null : folderError !== null ? (
          <ResearchFolderLoadFailure error={folderError} onRetry={refreshFolders} />
        ) : folders.length === 0 ? (
          <p role="status">{t("loadingFolders")}</p>
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
          <p role="alert"><strong>{t("failure")}</strong> {formatExecutionFailure(run.failure_reason)}</p>
        ) : null}
        {run.status === "succeeded" && run.result ? (
          <>
            <ResearchResultView result={run.result} />
            {"factor" in run.result ? <FactorEvidence key={`factor:${run.id}`} runId={run.id} /> : null}
            {"strategy" in run.result && <DailyHoldings key={`holdings:${run.id}`} rerun={{ folderId: run.folder_id, source: { kind: "research_run", run_id: run.id } }} endpoint={`/api/research-runs/${encodeURIComponent(run.id)}/holdings/query`} />}
            {"strategy" in run.result && <StrategyEvents key={`events:${run.id}`} endpoint={`/api/research-runs/${encodeURIComponent(run.id)}/events/query`} />}
            <CommonInputObservations key={`inputs:${run.id}`} endpoint={`/api/research-runs/${encodeURIComponent(run.id)}/common-input-observations`} />
          </>
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
    <section aria-label={t("title")} className="research-runs-list-page">
      <header className="page-header">
        <h1>{t("title")}</h1>
      </header>
      <ResearchRunsNavigation active="runs" />
      <div className="research-run-list-toolbar">
        <div className="research-run-filters">
          {folderError !== null ? (
            <ResearchFolderLoadFailure error={folderError} onRetry={refreshFolders} />
          ) : folders.length === 0 ? (
            <p role="status">{t("loadingFolders")}</p>
          ) : (
            <label>{t("folder")}<select
                aria-label={t("filterFolder")}
                onChange={(event) => changeFolderFilter(event.target.value)}
                value={folderFilter}
              >
                <option value="">{t("allFolders")}</option>
                {folders.map((folder) => (
                  <option key={folder.id} value={folder.id}>{folderDisplayName(folder)}</option>
                ))}
              </select>
            </label>
          )}
          <label>{t("type")}<select
              aria-label={t("filterType")}
              onChange={(event) => changeResearchKindFilter(
                event.target.value as ResearchKindFilter,
              )}
              value={researchKindFilter}
            >
              <option value="">{t("allTypes")}</option>
              <option value="factor_evaluation">{i18n.t("research:factor_evaluation")}</option>
              <option value="strategy_backtest">{i18n.t("research:strategy_backtest")}</option>
            </select>
          </label>
        </div>
      </div>
      {researchKindFilter !== "" && (
        <ResearchMetricFilters key={`metric-filters-${researchKindFilter}`} researchKind={researchKindFilter}
          onApply={(filters) => { setMetricFilters(filters); resetListPage(); }} />
      )}
      {loadState === "refreshing" ? (
        <p className="research-run-list-status" role="status">{t("loadingRuns")}</p>
      ) : null}
      {loadState === null && items?.length === 0 ? (
        <p className="research-run-list-empty">{t("empty")}</p>
      ) : null}
      <ResearchRunHistory
        items={items ?? []}
        key={researchKindFilter || "all"}
        researchKind={researchKindFilter}
        sort={sort}
        onSortChange={changeSort}
      />
      <ResearchRunPagination
        totalCount={totalCount}
        loading={loadState !== null || error !== null}
        onNextPage={showNextPage}
        onPreviousPage={showPreviousPage}
        pageIndex={pageIndex}
      />
    </section>
  );
}

function FactorRunDetail({ detail, folderError, folders, onRefreshFolders, researcherId, run }: {
  detail: ReturnType<typeof useResearchRunDetailController>;
  folderError: "folderError" | null;
  folders: ResearchFolderOption[];
  onRefreshFolders: () => void;
  researcherId: string;
  run: ResearchRun;
}) {
  const { t } = useTranslation("runs");
  const [tab, setTab] = useState("overview");
  const [visited, setVisited] = useState<string[]>(["overview"]);
  const terminal = isTerminalResearch(run.status);
  const result = run.result && "factor" in run.result ? run.result : null;
  const folderContent = detail.deleting ? null : folderError ? (
    <ResearchFolderLoadFailure error={folderError} onRetry={onRefreshFolders} />
  ) : folders.length === 0 ? (
    <p role="status">{t("loadingFolders")}</p>
  ) : <ResearchOrganizationPanel
    folders={folders}
    key={`${run.id}:${run.name}:${run.folder_id}`}
    onOrganized={(organized) => detail.setRun((current) => current === null ? organized : { ...current, ...organized })}
    run={run}
  />;

  return <Page aria-label={t("title")} className="research-run-page px-4 py-6 sm:px-6 lg:px-8">
    <PageContent className="flex flex-col gap-6">
      <PageHeader
        title={run.name}
        description={<span className="flex flex-wrap items-center gap-2">
          <span>{researchKindLabel(run.research_kind)}</span>
          <Badge variant={run.status === "failed" ? "destructive" : run.status === "succeeded" ? "default" : "outline"} className="rounded-md">{t(`statuses.${run.status}`)}</Badge>
        </span>}
        actions={<>
          <Button variant="outline" render={<a href="/research-runs" onClick={followCoreLink} />}><CaretLeft aria-hidden="true" />{t("back")}</Button>
          {run.batch_id ? <Button variant="outline" render={<a href={`/research-runs/batches/${encodeURIComponent(run.batch_id)}`} onClick={followCoreLink} />}>{t("viewBatch")}</Button> : null}
          {run.batch_id && ["queued", "running", "cancelling"].includes(run.status) ? <ResearchBatchCancelButton key={run.batch_id} batchId={run.batch_id} status={run.status} /> : null}
          {!run.batch_id && (run.status === "queued" || run.status === "running") ? <Button variant="outline" disabled={detail.canceling} onClick={() => void detail.cancel()}>{t(detail.canceling ? "cancelling" : "cancel")}</Button> : null}
          {terminal ? <Button variant="destructive" disabled={detail.deleting} onClick={detail.openDeleteDialog} ref={detail.deleteTrigger}>{t(detail.deleting ? "deleting" : "delete")}</Button> : null}
        </>}
      />
      {detail.cancelError ? <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{t(detail.cancelError)}</p> : null}
      {detail.loadState === "refreshing" ? <p role="status" className="text-xs text-muted-foreground">{t("refreshingRun")}</p> : null}
      {run.rerun_origin ? <CurrentDataRerunOrigin origin={run.rerun_origin} /> : null}
      {run.status === "failed" ? <section aria-label={t("failure")} className="rounded-lg border border-destructive/30 bg-destructive/10 p-5" role="alert">
        <h2 className="m-0 text-base font-semibold text-destructive">{t("failure")}</h2>
        <p className="mb-0 mt-2 text-sm">{formatExecutionFailure(run.failure_reason ?? "")}</p>
      </section> : null}
      {!terminal && run.progress ? <ResearchRunProgressView progress={run.progress} status={run.status} timing={run.execution_timing} /> : null}
      {result ? <Tabs value={tab} onValueChange={(value) => {
        setTab(value);
        setVisited((current) => current.includes(value) ? current : [...current, value]);
      }} className="gap-6">
        <TabsList aria-label={t("result.views")} variant="line" className="h-auto w-full justify-start gap-4 overflow-x-auto border-b border-border p-0">
          <TabsTrigger className="min-h-11 flex-none px-2 text-sm" value="overview">{t("result.overview")}</TabsTrigger>
          <TabsTrigger className="min-h-11 flex-none px-2 text-sm" value="evidence">{t("result.evidence")}</TabsTrigger>
          <TabsTrigger className="min-h-11 flex-none px-2 text-sm" value="inputs">{t("result.inputs")}</TabsTrigger>
          <TabsTrigger className="min-h-11 flex-none px-2 text-sm" value="configuration">{t("result.configuration")}</TabsTrigger>
        </TabsList>
        <TabsContent keepMounted value="overview" className="flex flex-col gap-6 text-sm">
          <FactorResultView result={result} />
        </TabsContent>
        <TabsContent keepMounted value="evidence" className="text-sm">
          {visited.includes("evidence") ? <FactorEvidence key={run.id} runId={run.id} embedded /> : null}
        </TabsContent>
        <TabsContent keepMounted value="inputs" className="text-sm">
          {visited.includes("inputs") ? <CommonInputObservations key={run.id} endpoint={`/api/research-runs/${encodeURIComponent(run.id)}/common-input-observations`} embedded /> : null}
        </TabsContent>
        <TabsContent keepMounted value="configuration" className="flex flex-col gap-6 text-sm">
          {visited.includes("configuration") ? <>
            <ResearchRunFacts run={run} />
            {run.progress ? <ResearchRunProgressView progress={run.progress} status={run.status} timing={run.execution_timing} /> : null}
            {folderContent}
            {!detail.deleting && folders.length > 0 && run.input ? <UseAsDraftPanel folders={folders} input={run.input} researcherId={researcherId} sourceFolderId={run.folder_id} /> : null}
          </> : null}
        </TabsContent>
      </Tabs> : <Section title={t("result.configuration")} className="border-t border-border pt-6">
        <ResearchRunFacts run={run} />
        {terminal && run.progress ? <ResearchRunProgressView progress={run.progress} status={run.status} timing={run.execution_timing} /> : null}
        {folderContent}
        {!detail.deleting && folders.length > 0 && run.input ? <UseAsDraftPanel folders={folders} input={run.input} researcherId={researcherId} sourceFolderId={run.folder_id} /> : null}
      </Section>}
      <ResearchDeleteDialog deleting={detail.deleting} error={detail.deleteError} name={run.name} onConfirm={() => void detail.performResearchDeletion()} onDismiss={detail.closeDeleteDialog} open={detail.deleteDialogOpen} />
    </PageContent>
  </Page>;
}

export function ResearchRunBackLink() {
  const { t } = useTranslation("runs");
  return (
    <a className="button button-quiet" href="/research-runs" onClick={followCoreLink}>
      <CaretLeft aria-hidden="true" size={13} weight="bold" />{t("back")}</a>
  );
}

export function ResearchDeleteDialog({
  deleting,
  error,
  name,
  onConfirm,
  onDismiss,
  open,
}: {
  deleting: boolean;
  error: HttpActionError | null;
  name: string;
  onConfirm: () => void;
  onDismiss: () => void;
  open: boolean;
}) {
  const { t } = useTranslation("runs");
  return <AlertDialog open={open} onOpenChange={(next) => { if (!next && !deleting) onDismiss(); }}>
    <AlertDialogContent id="research-delete-dialog" className="mx-4 w-[calc(100%-2rem)] max-w-[440px] gap-4 p-6">
      <AlertDialogHeader className="text-left">
        <p className="m-0 text-xs font-semibold uppercase tracking-wide text-destructive">{t("deleteDialog.permanent")}</p>
        <AlertDialogTitle className="text-base font-semibold">{t("deleteDialog.title")}</AlertDialogTitle>
      </AlertDialogHeader>
      <AlertDialogDescription className="text-sm leading-[22px] text-foreground">
        <Trans t={t} i18nKey="deleteDialog.description" components={{ name: <strong>{name}</strong> }} />
      </AlertDialogDescription>
      <p className="m-0 text-sm text-muted-foreground">{t("deleteDialog.retained")}</p>
      {error ? <p role="alert" className="m-0 text-sm text-destructive">{error.status === null ? t("deleteError") : t("deleteHttpError", { status: error.status })}</p> : null}
      <AlertDialogFooter>
        <AlertDialogCancel className="min-h-11" disabled={deleting}>{t("deleteDialog.keep")}</AlertDialogCancel>
        <AlertDialogAction className="min-h-11" variant="destructive" disabled={deleting} onClick={onConfirm}>
          {t(deleting ? "deleting" : "delete")}
        </AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>;
}

export function researchRunListPath({
  page,
  metricFilters = [],
  sort,
  folderId,
  researchKind,
}: {
  page: number;
  metricFilters?: ResearchMetricFilter[];
  sort: ResearchRunSort;
  folderId: string;
  researchKind: ResearchKindFilter;
}): string {
  const parameters = new URLSearchParams({ page: String(page), page_size: String(RESEARCH_RUN_PAGE_SIZE), sort_by: sort.key, sort_direction: sort.direction });
  if (metricFilters.length) parameters.set("metric_filters", JSON.stringify(metricFilters));
  if (folderId !== "") parameters.set("folder_id", folderId);
  if (researchKind !== "") parameters.set("research_kind", researchKind);
  return `/api/research-runs?${parameters.toString()}`;
}

export function ResearchRunPagination({
  totalCount,
  loading,
  onNextPage,
  onPreviousPage,
  pageIndex,
}: {
  totalCount: number | null;
  loading: boolean;
  onNextPage: () => void;
  onPreviousPage: () => void;
  pageIndex: number;
}) {
  const { t } = useTranslation("runs");
  return (
    <nav aria-label={t("pages")} className="research-run-pagination">
      <button disabled={loading || pageIndex === 0} onClick={onPreviousPage} type="button">
        <CaretLeft aria-hidden="true" size={13} weight="bold" />{t("previous")}</button>
      <span className="research-run-pagination-summary" aria-live="polite">
        <span>{totalCount === null ? t("loading") : t("total", { total: formatNumber(totalCount), size: formatNumber(RESEARCH_RUN_PAGE_SIZE) })}</span>
        {totalCount !== null && <span>{t("page", { page: formatNumber(totalCount === 0 ? 0 : pageIndex + 1), pages: formatNumber(Math.ceil(totalCount / RESEARCH_RUN_PAGE_SIZE)) })}</span>}
      </span>
      <button disabled={loading || totalCount === null || (pageIndex + 1) * RESEARCH_RUN_PAGE_SIZE >= totalCount} onClick={onNextPage} type="button">{t("next")}<CaretRight aria-hidden="true" size={13} weight="bold" />
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
  const { t } = useTranslation("runs");
  const [timingOpen, setTimingOpen] = useState(false);
  const estimate = progress.remaining_duration_estimate_seconds;
  const completed = progress.completed_warmup_sessions + progress.completed_research_sessions;
  const total = progress.total_warmup_sessions + progress.total_research_sessions;
  const active = status === "running" || status === "cancelling";
  const progressPercentage = total === 0 ? 0 : Math.round((completed / total) * 100);
  const executionTiming = (
    <dl className="research-run-timing">
      <div>
        <dt>{t("started")}</dt>
        <dd><ExecutionTimestamp value={timing?.started_at ?? null} /></dd>
      </div>
      <div>
        <dt>{t("finished")}</dt>
        <dd><ExecutionTimestamp value={timing?.finished_at ?? null} /></dd>
      </div>
    </dl>
  );
  if (status === "succeeded") {
    return (
      <section aria-label={t("progress")} className="research-run-progress research-run-progress-complete">
        <Collapsible open={timingOpen} onOpenChange={setTimingOpen} className="research-run-completion-details">
          <CollapsibleTrigger render={<Button variant="ghost" className="w-full justify-start whitespace-normal text-left" />}>
            <span className="research-run-completion-label">
              <CheckCircle aria-hidden="true" size={18} weight="fill" />{t("executionComplete")}</span>
            <span className="research-run-completion-metric">
              <strong>{formatNumber(progress.completed_research_sessions)} / {formatNumber(progress.total_research_sessions)}</strong> {t("sessions")}
            </span>
            <span className="research-run-completion-metric">
              <span>{t("executionTime")}</span> <strong>{formatDuration(timing?.elapsed_seconds ?? null)}</strong>
            </span>
            <span className="research-run-completion-toggle">{t("timingDetails")}<CaretDown aria-hidden="true" size={14} className={timingOpen ? "rotate-180" : undefined} />
            </span>
          </CollapsibleTrigger>
          <CollapsibleContent>{executionTiming}</CollapsibleContent>
        </Collapsible>
      </section>
    );
  }
  return (
    <section aria-label={t("progress")} className="research-run-progress">
      <header className="research-run-progress-heading">
        <div className="research-run-progress-title">
          <h2>{t("executionProgress")}</h2>
          <span className="research-run-progress-state" data-status={status}>
            {progressLabel(status, progress.phase)}
          </span>
        </div>
        <span className="research-run-progress-percentage">{formatNumber(progressPercentage)}%</span>
        <dl className="research-run-duration">
          <div>
            <dt>{t(timing?.is_final ? "executionTime" : "elapsed")}</dt>
            <dd>{formatDuration(timing?.elapsed_seconds ?? null)}</dd>
          </div>
        </dl>
      </header>
      <div className="research-run-progress-track">
        <progress
          aria-label={t("progressAria")}
          max={Math.max(total, 1)}
          value={completed}
        />
      </div>
      <div className="research-run-progress-ledger">
        <dl className="research-run-progress-stats">
          <div>
            <dt>{progress.phase === "shared_alpha_factor"
              ? t("sharedSessions") : t("researchSessions")}</dt>
            <dd>{formatNumber(progress.completed_research_sessions)} / {formatNumber(progress.total_research_sessions)}</dd>
          </div>
        </dl>
        {executionTiming}
      </div>
      {active && estimate !== null ? (
        <p className="research-run-progress-note">
          {t("remaining", { duration: formatDuration(estimate) })}
          {progress.duration_is_estimate ? t("estimate") : ""}
        </p>
      ) : null}
    </section>
  );
}

export function ResearchRunFacts({ run }: { run: ResearchRun }) {
  const { t } = useTranslation("runs");
  const input = run.input;
  const direct = input?.research_kind === "strategy_backtest" && input.strategy_mode === "direct";
  const factorConditionClass = input?.research_kind === "factor_evaluation"
    ? "research-run-fact-half"
    : undefined;
  return (
    <div
      aria-label={t("conditions")}
      className="research-run-facts research-run-execution-facts"
      role="group"
    >
      <p><strong>{t("status")}</strong> {t(`statuses.${run.status}`)}</p>
      <p><strong>{i18n.t("research:kind")}</strong> {researchKindLabel(run.research_kind)}</p>
      <p className="research-run-fact-name"><strong>{t("name")}</strong> {run.name}</p>
      {(input === undefined || "formula" in input) && <p className="research-run-fact-formula">
        <strong>{t("formula")}</strong> <code>{input?.formula ?? run.formula_summary}</code>
      </p>}
      <p className="research-run-fact-period">
        <strong>{t("period")}</strong> {t("dateRange", { start: run.start_date, end: run.end_date })}
      </p>
      {input !== undefined ? (
        <>
          <p className={factorConditionClass}>
            <strong>{i18n.t("research:universe")}</strong> {universeLabel(input.universe)}
          </p>
          {"neutralization" in input && input.neutralization !== undefined && <p className={factorConditionClass}>
            <strong>{i18n.t("research:neutralization")}</strong> {neutralizationLabel(input.neutralization)}
          </p>}
          {input.research_kind === "strategy_backtest" ? (
            <>
              <p><strong>{t("strategyMode")}</strong> {t(input.strategy_mode === "direct" ? "directMode" : "frameworkMode")}</p>
              <p><strong>{i18n.t("research:initialCash")}</strong> {input.initial_cash_cny}</p>
              <FrozenSimulationCosts costs={input.costs} />
              {input.strategy_mode === "direct" ? <FrozenPythonProgram program={input.program} /> : <>
              <FrozenFrameworkModules modules={input.modules} />
              {input.selection_every_sessions !== undefined && <>
              <p><strong>{i18n.t("research:holdings")}</strong> {formatNumber(input.holdings_count!)}</p>
              {input.weighting === "inverse_volatility" && <p><strong>{t("volatilityWindow")}</strong> {formatNumber(input.volatility_window!)} {t("sessions")}</p>}
              {input.weighting !== undefined && <p><strong>{i18n.t("research:weighting")}</strong> {i18n.t(`research:weightings.${input.weighting}`)}</p>}
              <p><strong>{t("exposureExpression")}</strong> <code>{input.exposure_expression}</code></p>
              <p>
                <strong>{t("selection")}</strong>{" "}
                {selectionLabel(input.selection_every_sessions)}
              </p>
              </>}
              </>}
            </>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function progressLabel(status: ResearchRun["status"], phase: ResearchRunProgress["phase"]): string {
  return status === "running" ? i18n.t(`runs:progressPhases.${phase}`) : i18n.t(`runs:progressStates.${status}`);
}

function ExecutionTimestamp({ value }: { value: string | null }) {
  useTranslation("common");
  return <time dateTime={value ?? undefined}>{formatUtcTimestamp(value, true)}</time>;
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
  navigate = (path) => window.location.assign(path),
}: {
  folders: ResearchFolderOption[];
  input: FrozenResearchAuthorableInput;
  researcherId: string;
  sourceFolderId: string;
  storage?: Pick<Storage, "getItem" | "setItem">;
  navigate?: (path: string) => void;
}) {
  const { t } = useTranslation("runs");
  const [targetFolderId, setTargetFolderId] = useState(sourceFolderId);
  const [error, setError] = useState<"draft.error" | null>(null);
  const [discardDialogOpen, setDiscardDialogOpen] = useState(false);

  function useAsDraft(discard: boolean): void {
    setError(null);
    try {
      if (!useResearchAsDraft(
        storage,
        researcherId,
        targetFolderId,
        input,
        () => {
          if (!discard) setDiscardDialogOpen(true);
          return discard;
        },
      )) return;
      setDiscardDialogOpen(false);
      navigate(targetFolderId === "folder_default"
        ? "/research"
        : `/research?folder=${encodeURIComponent(targetFolderId)}`);
    } catch {
      setDiscardDialogOpen(false);
      setError("draft.error");
    }
  }

  return (
    <section aria-label={t("draft.title")} className="grid min-w-0 gap-4 rounded-lg border border-border bg-card p-5">
      <div><h2 className="m-0 text-base font-semibold">{t("draft.title")}</h2>
        <p className="mb-0 mt-1 text-sm text-muted-foreground">{t("draft.description")}</p></div>
      <div className="flex min-w-0 flex-wrap items-end gap-3">
        <ResearchFolderSelect id="draft-folder" label={t("draft.folder")} folders={folders} value={targetFolderId} onChange={setTargetFolderId} />
        <Button onClick={() => useAsDraft(false)}>{t("draft.create")}</Button>
      </div>
      {error !== null ? <p role="alert">{t(error)}</p> : null}
      <AlertDialog open={discardDialogOpen} onOpenChange={setDiscardDialogOpen}>
        <AlertDialogContent className="mx-4 w-[calc(100%-2rem)] max-w-[440px]">
          <AlertDialogHeader><AlertDialogTitle>{t("draft.title")}</AlertDialogTitle></AlertDialogHeader>
          <AlertDialogDescription>{i18n.t("research:useDraftConfirm")}</AlertDialogDescription>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("draft.keepCurrent")}</AlertDialogCancel>
            <AlertDialogAction onClick={() => useAsDraft(true)}>{t("draft.replace")}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}

export function ResearchFolderLoadFailure({
  error,
  onRetry,
}: {
  error: "folderError";
  onRetry: () => void;
}) {
  const { t } = useTranslation("runs");
  return (
    <section aria-label={t("folderAvailability")}>
      <p role="alert">{t(error)}</p>
      <Button variant="outline" onClick={onRetry}>{t("retryFolders")}</Button>
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
  const { t } = useTranslation("runs");
  const [name, setName] = useState(run.name);
  const [folderId, setFolderId] = useState(run.folder_id);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<OrganizationError | null>(null);
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
        setError(await readOrganizationError(response));
        return;
      }
      onOrganized((await response.json()) as ResearchRun);
    } catch {
      setError({ status: null });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section aria-label={t("organization.title")} className="grid min-w-0 gap-4 rounded-lg border border-border bg-card p-5">
      <h2 className="m-0 text-base font-semibold">{t("organization.title")}</h2>
      <FieldGroup className="grid min-w-0 gap-4 sm:grid-cols-2">
        <Field><FieldLabel htmlFor="run-organization-name" className="text-sm font-medium">{i18n.t("research:name")}</FieldLabel>
          <Input id="run-organization-name" aria-label={i18n.t("research:name")} disabled={submitting} maxLength={200}
            onChange={(event) => setName(event.target.value)} value={name} />
        </Field>
        <ResearchFolderSelect id="run-organization-folder" label={t("folder")} folders={folders} value={folderId} disabled={submitting} onChange={setFolderId} />
      </FieldGroup>
      <div><Button disabled={submitting || (!nameChanged && !folderChanged)} onClick={() => void organize()}>
        {t(submitting ? "organization.saving" : "organization.save")}
      </Button></div>
      {error !== null ? <p role="alert">{"code" in error ? t("organization.folderMissing") : error.status === null ? t("organization.error") : t("organization.httpError", { status: error.status })}</p> : null}
    </section>
  );
}

function ResearchFolderSelect({ id, label, folders, value, onChange, disabled }: {
  id: string;
  label: string;
  folders: ResearchFolderOption[];
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return <Field className="min-w-[180px] flex-1 text-sm">
    <FieldLabel htmlFor={id} className="text-sm font-medium">{label}</FieldLabel>
    <Select value={value} onValueChange={(next) => { if (next !== null) onChange(next); }} disabled={disabled}>
      <SelectTrigger id={id} aria-label={label} className="w-full"><SelectValue>{folderDisplayName(folders.find((folder) => folder.id === value) ?? folders[0])}</SelectValue></SelectTrigger>
      <SelectContent><SelectGroup>{folders.map((folder) => <SelectItem key={folder.id} value={folder.id}>{folderDisplayName(folder)}</SelectItem>)}</SelectGroup></SelectContent>
    </Select>
  </Field>;
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
  label: ParseKeys<"runs">;
  shortLabel: ParseKeys<"runs">;
};

const DEFAULT_RESEARCH_RUN_SORT: ResearchRunSort = {
  key: "created_at",
  direction: "descending",
};

const FACTOR_RESEARCH_RUN_METRICS: ResearchRunMetricColumn[] = [
  { key: "one_session_rank_ic", label: "metrics.one_session_rank_ic", shortLabel: "shortMetrics.one_session_rank_ic" },
  { key: "five_session_rank_ic", label: "metrics.five_session_rank_ic", shortLabel: "shortMetrics.five_session_rank_ic" },
  { key: "twenty_session_rank_ic", label: "metrics.twenty_session_rank_ic", shortLabel: "shortMetrics.twenty_session_rank_ic" },
];

const STRATEGY_RESEARCH_RUN_METRICS: ResearchRunMetricColumn[] = [
  {
    key: "annualized_excess_return",
    label: "metrics.annualized_excess_return",
    shortLabel: "shortMetrics.annualized_excess_return",
  },
  { key: "sharpe", label: "metrics.sharpe", shortLabel: "shortMetrics.sharpe" },
  { key: "maximum_drawdown", label: "metrics.maximum_drawdown", shortLabel: "shortMetrics.maximum_drawdown" },
];

export type ResearchMetricFilter = {
  metric: Exclude<ResearchRunSortKey, "created_at">;
  operator: "gt" | "gte" | "lt" | "lte";
  value: number;
};

type MetricFilterDraft = Omit<ResearchMetricFilter, "value"> & { id: number; value: string };

export function ResearchMetricFilters({ researchKind, onApply }: {
  researchKind: Exclude<ResearchKindFilter, "">;
  onApply: (filters: ResearchMetricFilter[]) => void;
}) {
  const { t } = useTranslation("runs");
  const columns = researchKind === "strategy_backtest"
    ? STRATEGY_RESEARCH_RUN_METRICS
    : FACTOR_RESEARCH_RUN_METRICS;
  const [rows, setRows] = useState<MetricFilterDraft[]>([]);
  const [applied, setApplied] = useState("[]");
  const nextId = useRef(0);
  const dirty = JSON.stringify(rows) !== applied;
  function update(id: number, values: Partial<MetricFilterDraft>) {
    setRows(current => current.map(row => row.id === id ? { ...row, ...values } : row));
  }
  return (
    <form className="research-metric-filters" aria-label={t("filters.title")} onSubmit={event => {
      event.preventDefault();
      onApply(rows.map(row => ({ metric: row.metric, operator: row.operator,
        value: Number(row.value) / (isPercentMetric(row.metric) ? 100 : 1) })));
      setApplied(JSON.stringify(rows));
    }}>
      <div className="research-metric-filter-actions">
        <span>{t("filters.title")}</span>
        <button type="button" disabled={rows.length >= 12} onClick={() => {
          const id = nextId.current++;
          setRows(current => [...current, { id, metric: columns[0].key, operator: "gt", value: "" }]);
        }}>{t("filters.add")}</button>
        {(rows.length > 0 || applied !== "[]") && <>
          <button type="submit" disabled={!dirty}>{t("filters.apply")}</button>
          <button type="button" onClick={() => { setRows([]); setApplied("[]"); onApply([]); }}>{t("filters.clear")}</button>
        </>}
      </div>
      {rows.length > 0 && <p>{t("filters.allMatch")}{researchKind === "strategy_backtest" && t("filters.percent")}</p>}
      {rows.map((row, index) => (
        <div className="research-metric-filter-row" key={row.id}>
          <label>{t("filters.metric")}<select aria-label={t("filters.metricAt", { index: formatNumber(index + 1) })} value={row.metric}
              onChange={event => update(row.id, { metric: event.target.value as ResearchMetricFilter["metric"], value: "" })}>
              {columns.map(column => <option key={column.key} value={column.key}>{t(column.label)}</option>)}
            </select>
          </label>
          <label>{t("filters.comparison")}<select aria-label={t("filters.comparisonAt", { index: formatNumber(index + 1) })} value={row.operator}
              onChange={event => update(row.id, { operator: event.target.value as ResearchMetricFilter["operator"] })}>
              <option value="gt">&gt;</option><option value="gte">≥</option>
              <option value="lt">&lt;</option><option value="lte">≤</option>
            </select>
          </label>
          <label>{t(isPercentMetric(row.metric) ? "filters.valuePercent" : "filters.value")}
            <input aria-label={t("filters.thresholdAt", { index: formatNumber(index + 1) })} type="number" step="any" required value={row.value}
              onChange={event => update(row.id, { value: event.target.value })} />
          </label>
          <button type="button" aria-label={t("filters.removeAt", { index: formatNumber(index + 1) })}
            onClick={() => setRows(current => current.filter(item => item.id !== row.id))}>{t("filters.remove")}</button>
        </div>
      ))}
      {dirty && <p role="status">{t("filters.notApplied")}</p>}
    </form>
  );
}

function isPercentMetric(metric: ResearchMetricFilter["metric"]): boolean {
  return metric === "annualized_excess_return" || metric === "maximum_drawdown";
}

export function ResearchRunHistory({
  items,
  researchKind = "",
  sort,
  onSortChange,
}: {
  items: ResearchRun[];
  researchKind?: ResearchKindFilter;
  sort: ResearchRunSort;
  onSortChange: (sort: ResearchRunSort) => void;
}) {
  const { t } = useTranslation("runs");
  const metricColumns = researchRunMetricColumns(researchKind);

  function changeSort(key: ResearchRunSortKey) {
    onSortChange({ key, direction: sort.key === key
      ? (sort.direction === "ascending" ? "descending" : "ascending")
      : defaultResearchRunSortDirection(key) });
  }

  function selectSort(key: ResearchRunSortKey) {
    onSortChange({ key, direction: defaultResearchRunSortDirection(key) });
  }

  function toggleSortDirection() {
    onSortChange({ ...sort, direction: sort.direction === "ascending" ? "descending" : "ascending" });
  }

  const MobileSortIcon = sort.direction === "ascending" ? CaretUp : CaretDown;

  return (
    <div className="research-run-history-container">
      <div className="research-run-mobile-sort">
        <label>{t("sortBy")}<select
            aria-label={t("sortByAria")}
            onChange={(event) => selectSort(event.target.value as ResearchRunSortKey)}
            value={sort.key}
          >
            <option value="created_at">{t("created")}</option>
            {metricColumns.map((column) => (
              <option key={column.key} value={column.key}>{t(column.label)}</option>
            ))}
          </select>
        </label>
        <button
          aria-label={t(sort.direction === "ascending" ? "sortAscending" : "sortDescending")}
          onClick={toggleSortDirection}
          type="button"
        >
          <MobileSortIcon aria-hidden="true" size={14} weight="bold" />
          {t(sort.direction === "ascending" ? "ascending" : "descending")}
        </button>
      </div>
      <div className="research-run-history-scroll">
      <table aria-label={t("title")} className="research-run-history">
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
            <th scope="col">{i18n.t("research:title")}</th>
            <th scope="col">{t("type")}</th>
            <SortableResearchRunHeading
              direction={sort.direction}
              isActive={sort.key === "created_at"}
              label={t("createdUtc")}
              onSort={() => changeSort("created_at")}
            />
            <th scope="col">{t("status")}</th>
            {metricColumns.length === 0 ? (
              <th className="research-run-metric-heading" scope="col">{t("resultSummary")}</th>
            ) : metricColumns.map((column) => (
              <SortableResearchRunHeading
                direction={sort.direction}
                isActive={sort.key === column.key}
                key={column.key}
                label={t(column.label)}
                onSort={() => changeSort(column.key)}
              />
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <th scope="row">
                <a href={`/research-runs/${item.id}`} onClick={followCoreLink}>{item.name}</a>
              </th>
              <td data-label={t("type")}>{researchKindLabel(item.research_kind)}</td>
              <td data-label={t("createdUtc")}>
                <time dateTime={item.created_at}>{formatResearchRunCreatedAt(item.created_at)}</time>
              </td>
              <td data-label={t("status")}><span className={`run-status run-status-${item.status}`}>{t(`statuses.${item.status}`)}</span></td>
              {metricColumns.length === 0 ? (
                <ResearchRunResultSummary item={item} />
              ) : metricColumns.map((column) => (
                <td className="research-run-metric" data-label={t(column.label)} key={column.key}>
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
  const { t } = useTranslation("runs");
  const columns = item.research_kind === "factor_evaluation"
    ? FACTOR_RESEARCH_RUN_METRICS
    : STRATEGY_RESEARCH_RUN_METRICS;
  return (
    <td className="research-run-result-summary" data-label={t("resultSummary")}>
      <div>
        {columns.map((column) => (
          <span key={column.key}>
            <small>{t(column.shortLabel)}</small>
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
  return formatUtcTimestamp(value);
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

export function ResearchResultView({ result }: { result: ResearchResult }) {
  const { t } = useTranslation("runs");
  const strategyHelp = strategyMetricHelp();
  const strategyResult = "strategy" in result ? result : null;
  const factorResult = "factor" in result ? result : null;
  const selection = strategyResult ? strategySelection(strategyResult.terminal_strategy_state.decision_state) : null;
  return (
    <div className="research-result">
      {factorResult !== null ? <FactorResultView result={factorResult} /> : null}

      {strategyResult !== null ? <section className="research-result-section">
        <div className="section-heading strategy-summary-heading">
          <h2>{t("result.strategy")}</h2>
          <p>{t("result.accountThrough")} <time>{strategyResult.terminal_strategy_state.session}</time></p>
        </div>
        <div className="strategy-metrics">
          <Metric label={t("result.netCumulative")} help={strategyHelp.netCumulative} value={formatPercent(strategyResult.strategy.summary.metrics.net_cumulative_return)} />
          <Metric
            label={t("result.benchmarkCumulative", { benchmark: catalogLabel("benchmarks", "csi300-price-index-open") })}
            help={strategyHelp.benchmarkCumulative}
            value={formatPercent(strategyResult.strategy.summary.metrics.benchmark_cumulative_return)}
          />
          <Metric
            label={t("result.annualizedExcess")}
            help={strategyHelp.annualizedExcess}
            value={formatPercent(strategyResult.strategy.summary.metrics.annualized_excess_return)}
          />
          <Metric
            label={t("result.maximumDrawdown")}
            help={strategyHelp.maximumDrawdown}
            value={formatPercent(strategyResult.strategy.summary.metrics.maximum_drawdown.value)}
          />
          <Metric label={t("result.sharpe")} help={strategyHelp.sharpe} value={formatDecimal(strategyResult.strategy.summary.metrics.sharpe)} />
          <Metric
            label={t("result.costRatio")}
            help={strategyHelp.cumulativeCostRatio}
            value={formatPercent(strategyResult.strategy.summary.metrics.transaction_costs.ratio)}
          />
        </div>
        <div className="strategy-execution-context">
          <div className="strategy-context-row">
            <h3>{t("result.exposure")}</h3>
            <dl className="strategy-exposure-values">
              <div><dt>{t("result.lastCloseTarget")}</dt><dd>{formatPercent(isBuiltinFrameworkState(strategyResult.terminal_strategy_state.decision_state)
                ? strategyResult.terminal_strategy_state.decision_state.exposure
                : strategyResult.terminal_strategy_state.pending_target?.allocation?.exposure ?? null)}</dd></div>
              <div><dt>{t("result.actualOpenAllocation")}</dt><dd>{formatPercent(1 - Number(strategyResult.terminal_strategy_state.net_cash) / Number(strategyResult.terminal_strategy_state.net_nav))}</dd></div>
            </dl>
          </div>
          {selection !== null ? <div className="strategy-context-row">
            <h3>{t("result.selection")}</h3>
            <SelectionEligibilityView selection={selection} />
          </div> : null}
          <CloseRiskFacts session={strategyResult.terminal_strategy_state.session}
            nav={strategyResult.terminal_strategy_state.close_risk_nav_cny}
            positions={strategyResult.terminal_strategy_state.positions} />
          <FrameworkStateView state={strategyResult.terminal_strategy_state.decision_state} />
          <details className="strategy-execution-notes">
            <summary>{t("result.conventions")}<CaretDown aria-hidden="true" size={14} /></summary>
            <ul>
              <li>{t("result.nextOpen")}</li>
              <li>{t("result.allocation")}</li>
            </ul>
          </details>
        </div>
        <StrategyComparisonPanel comparison={strategyResult.strategy.comparison} />
      </section> : null}

    </div>
  );
}

function Metric({ label, value, help, context }: {
  label: string;
  value: string;
  help: MetricHelpContent;
  context?: string;
}) {
  return (
    <div className="result-metric">
      <div className="result-metric-heading">
        <span>{label}</span>
        <MetricHelp label={context === undefined ? label : `${context} ${label}`} content={help} />
      </div>
      <strong>{value}</strong>
    </div>
  );
}

function formatSignedPercent(value: number | null) {
  return formatPercent(value, { signed: true });
}

function researchKindLabel(value: ResearchRun["research_kind"]): string {
  return i18n.t(`research:${value}`);
}

export function universeLabel(value: FrozenResearchAuthorableInput["universe"]): string {
  return i18n.t("research:top", { count: Number(value.slice(3)) });
}

export function neutralizationLabel(value: "none" | "industry"): string {
  return i18n.t(`research:${value}`);
}

function selectionLabel(sessions: number): string {
  return sessions === 1 ? i18n.t("runs:everySession") : i18n.t("runs:everySessions", { sessions: formatNumber(sessions) });
}
