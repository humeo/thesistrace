import { ResearchFolderLoadFailure } from "./ResearchFolderLoadFailure";
import { ResearchRunList } from "./ResearchRunList";
import { useResearchRunListController } from "./useResearchRunListController";
import { Alert, AlertDescription, AlertTitle } from "../components/ui/alert";
import { Progress } from "../components/ui/progress";
import { StrategyResultView } from "./StrategyResultView";
import { Trans } from "react-i18next";
import { catalogLabel } from "../i18n/catalog";
import { formatDecimalString, formatDuration, formatNumber, formatUtcTimestamp } from "../i18n/format";
import { folderDisplayName } from "../research/folders";
import { formatRunError, formatExecutionFailure, readOrganizationError, type OrganizationError, type HttpActionError } from "./errors";
export { formatDuration } from "../i18n/format";
import { i18n, useTranslation } from "../i18n";
import { CurrentDataRerunOrigin, type RerunOrigin } from "../analysis/CurrentDataRerun";
import { DailyHoldings } from "../analysis/DailyHoldings";
import { StrategyEvents } from "../analysis/StrategyEvents";
import { type StrategyDecisionState } from "../research/strategyDecisionState";
import { FrozenFact, FrozenFrameworkModules, FrozenPythonProgram, FrozenSimulationCosts } from "../research/FrozenStrategyDefinition";
import {
  CaretLeft,
  CalendarBlank,
  CheckCircle,
  DotsThree,
  FileText,
  FolderSimple,
  Play,
  Trash,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { useUrlSelection } from "../shell/useUrlSelection";
import { cn } from "cn";

import { FactorEvidence } from "../analysis/FactorEvidence";
import { CommonInputObservations } from "../analysis/CommonInputObservations";
import { coreFetch } from "../auth/coreFetch";
import type { StrategyComparison } from "../analysis/strategyComparison";
import {
  useResearchAsDraft,
  type FrozenResearchAuthorableInput,
} from "../research/draft";
import { followCoreLink, navigateCorePath } from "../shell/navigation";
import { ResearchBatchCancelButton } from "./ResearchBatchesPage";
import { useResearchRunDetailController } from "./useResearchRunDetailController";
import { Page, PageContent, PageHeader, Section } from "../components/layout/Page";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Field, FieldGroup, FieldLabel } from "../components/ui/field";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Badge } from "../components/ui/badge";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { FactorResultView } from "./FactorResultView";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "../components/ui/alert-dialog";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "../components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuTrigger } from "../components/ui/dropdown-menu";

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

export type StrategyBacktestResearchResult = {
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

export type ResearchFolderOption = {
  id: string;
  name: string;
  is_default: boolean;
};

export function ResearchRunsPage({ researcherId, runId }: {
  researcherId: string;
  runId?: string;
}) {
  const { t } = useTranslation("runs");
  const detail = useResearchRunDetailController(runId);
  const { run } = detail;
  const list = useResearchRunListController(runId);
  const { folders, folderError, refreshFolders } = list;
  if (runId && detail.error) return <Page><PageContent>
    <PageHeader title={t("run")} />
    <Alert variant="destructive"><AlertDescription>{formatRunError(detail.error)}</AlertDescription></Alert>
    <div className="mt-4 flex flex-wrap gap-2"><ResearchRunBackLink /><Button variant="outline" onClick={detail.refresh}>{t("retry")}</Button></div>
  </PageContent></Page>;
  if (runId && run?.id !== runId) return <Page><p role="status">{t("loadingRun")}</p></Page>;
  if (runId && run?.id === runId) return <ResearchRunDetail key={run.id} detail={detail} folderError={folderError} folders={folders} onRefreshFolders={refreshFolders} researcherId={researcherId} run={run} />;
  return <ResearchRunList list={list} />;
}

function ResearchRunDetail({ detail, folderError, folders, onRefreshFolders, researcherId, run }: {
  detail: ReturnType<typeof useResearchRunDetailController>;
  folderError: "folderError" | null;
  folders: ResearchFolderOption[];
  onRefreshFolders: () => void;
  researcherId: string;
  run: ResearchRun;
}) {
  const { t } = useTranslation("runs");
  const terminal = isTerminalResearch(run.status);
  const result = run.status === "succeeded" ? run.result : null;
  const strategyResult = result != null && !("factor" in result);
  const tabs = result == null ? ["overview"] : "factor" in result
    ? ["overview", "evidence", "inputs", "configuration"]
    : ["overview", "holdings", "events", "inputs", "configuration"];
  const [tab, setTab] = useUrlSelection("tab", tabs, "overview");
  const [visited, setVisited] = useState<string[]>([tab]);
  useEffect(() => { setVisited(values => values.includes(tab) ? values : [...values, tab]); }, [tab]);
  const sourceFolder = folders.find(folder => folder.id === run.folder_id);
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

  return <Page aria-label={t("title")} className="research-run-page result-surface">
    <PageContent className="flex flex-col gap-4">
      <div className="text-sm text-muted-foreground"><a href="/research-runs" onClick={followCoreLink} aria-label={t("back")} className="hover:underline">{t("title")}</a><span aria-hidden="true"> / </span><span className="text-foreground">{run.name}</span></div>
      <PageHeader
        className="mb-0"
        variant="result"
        title={run.name}
        badges={<span className="flex items-center gap-2">
          <Badge variant="secondary" className="h-7 rounded-md">{researchKindLabel(run.research_kind)}</Badge>
          <Badge variant={run.status === "failed" ? "destructive" : run.status === "succeeded" ? "success" : "outline"} className="h-7 rounded-md">
            {run.status === "succeeded" ? <CheckCircle weight="fill" aria-hidden="true" /> : null}{t(`statuses.${run.status}`)}
          </Badge>
        </span>}
        description={<span className="flex flex-wrap items-center gap-3">
          <span className="inline-flex items-center gap-2"><CalendarBlank aria-hidden="true" className="size-4" />{run.start_date} — {run.end_date}</span>
          {sourceFolder ? <span className="ml-3 inline-flex items-center gap-2"><FolderSimple aria-hidden="true" className="size-4" />{folderDisplayName(sourceFolder)}</span> : null}
        </span>}
        actions={<>
          {run.batch_id ? <Button variant="outline" nativeButton={false} role="link" render={<a href={`/research-runs/batches/${encodeURIComponent(run.batch_id)}`} onClick={followCoreLink} />}>{t("viewBatch")}</Button> : null}
          {run.batch_id && ["queued", "running", "cancelling"].includes(run.status) ? <ResearchBatchCancelButton key={run.batch_id} batchId={run.batch_id} status={run.status} /> : null}
          {!run.batch_id && (run.status === "queued" || run.status === "running") ? <Button variant="outline" disabled={detail.canceling} onClick={() => void detail.cancel()}>{t(detail.canceling ? "cancelling" : "cancel")}</Button> : null}
          {run.status === "succeeded" && run.research_kind === "strategy_backtest" ? <Button size="xl" disabled={detail.startingTracking || detail.deleting} onClick={() => void detail.startTracking()}><Play aria-hidden="true" />{t(detail.startingTracking ? "startingTracking" : "startTracking")}</Button> : null}
          {strategyResult && run.input && folders.length > 0 ? <Dialog>
            <DialogTrigger render={<Button variant="outline" size="xl" disabled={detail.deleting} />}><FileText aria-hidden="true" />{t("draft.use")}</DialogTrigger>
            <DialogContent className="result-surface" closeLabel={i18n.t("common:close")}>
              <DialogHeader><DialogTitle>{t("draft.title")}</DialogTitle><DialogDescription>{t("draft.description")}</DialogDescription></DialogHeader>
              <UseAsDraftPanel embedded folders={folders} input={run.input} researcherId={researcherId} sourceFolderId={run.folder_id} />
            </DialogContent>
          </Dialog> : terminal && run.input && folders.length > 0 ? <Button variant="outline" size="xl" aria-label={t("draft.open")} onClick={() => { setTab(result ? "configuration" : "overview"); setVisited(current => current.includes("configuration") ? current : [...current, "configuration"]); window.requestAnimationFrame(() => document.getElementById("research-use-as-draft")?.scrollIntoView({ behavior: "smooth", block: "center" })); }}>{t("draft.create")}</Button> : null}
          {terminal ? <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="outline" size="icon-xl" aria-label={t("moreActions")} disabled={detail.deleting || detail.startingTracking} ref={detail.deleteTrigger} />}><DotsThree aria-hidden="true" /></DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="result-surface min-w-44"><DropdownMenuGroup>
              <DropdownMenuItem variant="destructive" onClick={detail.openDeleteDialog}><Trash aria-hidden="true" />{t(detail.deleting ? "deleting" : "delete")}</DropdownMenuItem>
            </DropdownMenuGroup></DropdownMenuContent>
          </DropdownMenu> : null}
        </>}
      />
      {detail.cancelError ? <Alert variant="destructive"><AlertDescription>{t(detail.cancelError)}</AlertDescription></Alert> : null}
      {detail.trackingError ? <Alert variant="destructive"><AlertDescription>{formatRunError(detail.trackingError)}</AlertDescription></Alert> : null}
      {detail.loadState === "refreshing" ? <p role="status" className="text-xs text-muted-foreground">{t("refreshingRun")}</p> : null}
      {run.rerun_origin ? <CurrentDataRerunOrigin origin={run.rerun_origin} /> : null}
      {run.status === "failed" ? <Alert variant="destructive" aria-label={t("failure")}>
        <AlertTitle>{t("failure")}</AlertTitle>
        <AlertDescription>{formatExecutionFailure(run.failure_reason ?? "")}</AlertDescription>
      </Alert> : null}
      {!terminal && run.progress ? <ResearchRunProgressView progress={run.progress} status={run.status} timing={run.execution_timing} /> : null}
      {result ? <Tabs value={tab} onValueChange={(value) => {
        setTab(value);
        setVisited((current) => current.includes(value) ? current : [...current, value]);
      }} className="mt-2 gap-6">
        <TabsList aria-label={t("result.views")} variant="line" className="h-auto w-full justify-start gap-6 overflow-x-auto border-b border-border p-0">
          <TabsTrigger size="lg" className="min-w-28 flex-none" value="overview">{t("result.overview")}</TabsTrigger>
          {"factor" in result ? <TabsTrigger size="lg" className="min-w-28 flex-none" value="evidence">{t("result.evidence")}</TabsTrigger> : <>
            <TabsTrigger size="lg" className="min-w-28 flex-none" value="holdings">{i18n.t("analysis:holdings.title")}</TabsTrigger>
            <TabsTrigger size="lg" className="min-w-28 flex-none" value="events">{i18n.t("analysis:events.title")}</TabsTrigger>
          </>}
          <TabsTrigger size="lg" className="min-w-28 flex-none" value="inputs">{t("result.inputs")}</TabsTrigger>
          <TabsTrigger size="lg" className="min-w-28 flex-none" value="configuration">{t("result.configuration")}</TabsTrigger>
        </TabsList>
        <TabsContent keepMounted value="overview" className="flex flex-col gap-6">
          <ResearchResultView result={result} />
        </TabsContent>
        {"factor" in result ? <TabsContent keepMounted value="evidence">
          {visited.includes("evidence") ? <FactorEvidence runId={run.id} embedded /> : null}
        </TabsContent> : <>
          <TabsContent keepMounted value="holdings">
            {visited.includes("holdings") ? <DailyHoldings embedded dateRange={{ start: run.start_date, end: run.end_date }} endpoint={`/api/research-runs/${encodeURIComponent(run.id)}/holdings/query`} rerun={{ folderId: run.folder_id, source: { kind: "research_run", run_id: run.id } }} /> : null}
          </TabsContent>
          <TabsContent keepMounted value="events">
            {visited.includes("events") ? <StrategyEvents embedded dateRange={{ start: run.start_date, end: run.end_date }} endpoint={`/api/research-runs/${encodeURIComponent(run.id)}/events/query`} /> : null}
          </TabsContent>
        </>}
        <TabsContent keepMounted value="inputs" className="text-sm">
          {visited.includes("inputs") ? <CommonInputObservations key={run.id} endpoint={`/api/research-runs/${encodeURIComponent(run.id)}/common-input-observations`} embedded /> : null}
        </TabsContent>
        <TabsContent keepMounted value="configuration" className="flex flex-col gap-6">
          {visited.includes("configuration") ? <>
            <ResearchRunFacts run={run} />
            {run.progress ? <ResearchRunProgressView progress={run.progress} status={run.status} timing={run.execution_timing} /> : null}
            {folderContent}
            {"factor" in result && !detail.deleting && folders.length > 0 && run.input ? <UseAsDraftPanel folders={folders} input={run.input} researcherId={researcherId} sourceFolderId={run.folder_id} /> : null}
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
    <Button variant="outline" nativeButton={false} role="link" render={<a href="/research-runs" onClick={followCoreLink} />}><CaretLeft aria-hidden="true" data-icon="inline-start" />{t("back")}</Button>
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
      <AlertDialogDescription className="text-sm text-foreground">
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
  const estimate = progress.remaining_duration_estimate_seconds;
  const completed = progress.completed_warmup_sessions + progress.completed_research_sessions;
  const total = progress.total_warmup_sessions + progress.total_research_sessions;
  const active = status === "running" || status === "cancelling";
  const progressPercentage = total === 0 ? 0 : Math.round((completed / total) * 100);
  const executionTiming = (
    <dl className="m-0 grid min-w-0 gap-4 sm:grid-cols-2 [&_dt]:text-muted-foreground [&_dd]:m-0 [&_dd]:font-mono [&_dd]:break-words">
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
      <Card aria-label={t("progress")} role="region" className="min-w-0">
        <CardHeader>
          <CardTitle role="heading" aria-level={2}>{t("executionInfo")}</CardTitle>
          <CardAction><span className="flex items-center gap-2 text-muted-foreground">
            <CheckCircle aria-hidden="true" size={18} weight="fill" />{t("executionComplete")}
          </span></CardAction>
        </CardHeader>
        <CardContent>
          <dl className="m-0 grid min-w-0 gap-4 lg:grid-cols-4">
            <FrozenFact label={t("researchSessions")}>{formatNumber(progress.completed_research_sessions)} / {formatNumber(progress.total_research_sessions)}</FrozenFact>
            <FrozenFact label={t("executionTime")}>{formatDuration(timing?.elapsed_seconds ?? null)}</FrozenFact>
            <FrozenFact label={t("started")}><span className="font-mono"><ExecutionTimestamp value={timing?.started_at ?? null} /></span></FrozenFact>
            <FrozenFact label={t("finished")}><span className="font-mono"><ExecutionTimestamp value={timing?.finished_at ?? null} /></span></FrozenFact>
          </dl>
        </CardContent>
      </Card>
    );
  }
  return (
    <section aria-label={t("progress")} className="flex min-w-0 flex-col gap-4 rounded-lg border border-border bg-card p-4">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <h2>{t("executionProgress")}</h2>
          <Badge variant={status === "failed" || status === "cancelled" ? "destructive" : "outline"}>{progressLabel(status, progress.phase)}</Badge>
        </div>
        <span className="ml-auto font-mono">{formatNumber(progressPercentage)}%</span>
        <dl className="m-0 [&_dt]:text-muted-foreground [&_dd]:m-0 [&_dd]:font-mono">
          <div>
            <dt>{t(timing?.is_final ? "executionTime" : "elapsed")}</dt>
            <dd>{formatDuration(timing?.elapsed_seconds ?? null)}</dd>
          </div>
        </dl>
      </header>
      <div className="w-full">
        <Progress
          aria-label={t("progressAria")}
          max={Math.max(total, 1)}
          value={completed}
        />
      </div>
      <div className="grid min-w-0 gap-4 lg:grid-cols-2">
        <dl className="m-0 [&_dt]:text-muted-foreground [&_dd]:m-0 [&_dd]:font-mono">
          <div>
            <dt>{progress.phase === "shared_alpha_factor"
              ? t("sharedSessions") : t("researchSessions")}</dt>
            <dd>{formatNumber(progress.completed_research_sessions)} / {formatNumber(progress.total_research_sessions)}</dd>
          </div>
        </dl>
        {executionTiming}
      </div>
      {active && estimate !== null ? (
        <p className="m-0 text-muted-foreground">
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
  const strategy = input?.research_kind === "strategy_backtest" ? input : undefined;
  return <div role="group" aria-label={t("conditions")} className={cn("grid min-w-0 items-start gap-6 text-sm", strategy && "xl:grid-cols-[minmax(0,1fr)_320px]")}>
    <div className="grid min-w-0 gap-6">
      <Card role="region" aria-label={t("configuration.conditions")}>
        <CardHeader><CardTitle role="heading" aria-level={2}>{t("configuration.conditions")}</CardTitle></CardHeader>
        <CardContent>
          <dl className="m-0 grid min-w-0 gap-x-8 gap-y-5 lg:grid-cols-2">
            <FrozenFact label={t("period")}>{t("dateRange", { start: run.start_date, end: run.end_date })}</FrozenFact>
            {input && <FrozenFact label={i18n.t("research:universe")}>{universeLabel(input.universe)}</FrozenFact>}
            {strategy && <>
              <FrozenFact label={i18n.t("research:initialCash")}><span title={strategy.initial_cash_cny}>{formatDecimalString(strategy.initial_cash_cny, 2)}</span></FrozenFact>
              <FrozenFact label={t("strategyMode")}>{t(strategy.strategy_mode === "direct" ? "directMode" : "frameworkMode")}</FrozenFact>
            </>}
          </dl>
        </CardContent>
      </Card>
      <Card role="region" aria-label={t(strategy ? "configuration.strategy" : "configuration.signal")}>
        <CardHeader><CardTitle role="heading" aria-level={2}>{t(strategy ? "configuration.strategy" : "configuration.signal")}</CardTitle></CardHeader>
        <CardContent>
          {strategy?.strategy_mode === "framework" ? <FrozenFrameworkModules input={strategy} />
            : strategy?.strategy_mode === "direct" ? <FrozenPythonProgram program={strategy.program} />
            : <dl className="m-0 grid min-w-0 gap-5">
              <FrozenFact label={t("formula")}><code>{input?.research_kind === "factor_evaluation" ? input.formula : run.formula_summary}</code></FrozenFact>
              {input?.research_kind === "factor_evaluation" && <FrozenFact label={i18n.t("research:neutralization")}>{neutralizationLabel(input.neutralization)}</FrozenFact>}
            </dl>}
        </CardContent>
      </Card>
    </div>
    {strategy && <FrozenSimulationCosts costs={strategy.costs} />}
  </div>;
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
  embedded = false,
  folders,
  input,
  researcherId,
  sourceFolderId,
  storage = window.localStorage,
  navigate = navigateCorePath,
}: {
  embedded?: boolean;
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
    <section id="research-use-as-draft" aria-label={t("draft.title")} className={embedded ? "grid min-w-0 gap-4" : "grid min-w-0 gap-4 rounded-lg border border-border bg-card p-6"}>
      {!embedded ? <div><h2 className="m-0 text-base font-semibold">{t("draft.title")}</h2>
        <p className="mb-0 mt-1 text-sm text-muted-foreground">{t("draft.description")}</p></div> : null}
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
    <section aria-label={t("organization.title")} className="grid min-w-0 gap-4 rounded-lg border border-border bg-card p-4">
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

export function ResearchResultView({ result }: { result: ResearchResult }) {
  return "factor" in result ? <FactorResultView result={result} /> : <StrategyResultView result={result} />;
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
