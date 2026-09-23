import { useEffect, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { z } from "zod";
import { coreFetch } from "../auth/coreFetch";
import { i18n } from "../i18n";
import { formatDecimal, formatPercent, formatTimestamp } from "../i18n/format";
import { blockedReason } from "../daily-tracks/blockedReason";
import { formatExecutionFailure } from "../research-runs/errors";

const metric = z.number().finite().nullable();
const strategyMetrics = z.object({ annualized_excess_return: metric, sharpe: metric, maximum_drawdown: z.object({ value: metric }) });
const runBase = z.object({
  id: z.string(), name: z.string(), status: z.enum(["queued", "running", "cancelling", "succeeded", "failed", "cancelled"]),
  formula_summary: z.string(), start_date: z.string(), end_date: z.string(),
  failure_reason: z.string().optional(),
});
const runSchema = z.discriminatedUnion("research_kind", [
  runBase.extend({
    research_kind: z.literal("factor_evaluation"),
    result: z.object({ factor: z.object({ horizons: z.object({
      "1": z.object({ summary: z.object({ rank_ic: z.object({ mean: metric }) }) }),
      "5": z.object({ summary: z.object({ rank_ic: z.object({ mean: metric }) }) }),
      "20": z.object({ summary: z.object({ rank_ic: z.object({ mean: metric }) }) }),
    }) }) }).optional(),
  }),
  runBase.extend({
    research_kind: z.literal("strategy_backtest"),
    result: z.object({ strategy: z.object({ summary: z.object({ metrics: strategyMetrics }) }) }).optional(),
  }),
]);
const trackSchema = z.object({
  id: z.string(), status: z.enum(["active", "blocked", "stopping", "stopped"]),
  origin: z.object({ seed_run_id: z.string(), strategy_session: z.string() }),
  strategy_session: z.string(), data_through_session: z.string(), blocked_reason: z.string().nullable(), blocked_code: z.string().nullable(),
  observation: z.object({ net_return: metric, maximum_drawdown: metric, session: z.string() }),
});
type Resource = { kind: "run"; value: z.infer<typeof runSchema> } | { kind: "track"; value: z.infer<typeof trackSchema> };
type ResourceErrorCode = "unavailable" | "loadFailed" | "identityMismatch" | "resultUnavailable" | "invalidResponse";
type State = { id: string; resource: Resource; loadedAt: string } | { id: string; errorCode: ResourceErrorCode };
class ResourceLoadError extends Error { constructor(readonly code: ResourceErrorCode) { super(code); } }

export function ResearchResourceCards({ kind, ids }: { kind: "run" | "track"; ids: string[] }) {
  return <div className="chat-a2ui-column">{ids.map((id) => <ResourceCard key={`${kind}:${id}`} kind={kind} id={id} />)}</div>;
}

function ResourceCard({ kind, id }: { kind: "run" | "track"; id: string }) {
  const { t } = useTranslation("chat");
  const [state, setState] = useState<State | null>(null);
  const [revision, setRevision] = useState(0);
  const href = kind === "run" ? `/research-runs/${id}` : `/daily-tracks/${id}`;
  useEffect(() => {
    const controller = new AbortController();
    setState(null);
    void (async () => {
      try {
        const response = await coreFetch(`/api${href}`, { signal: controller.signal });
        if (!response.ok) throw new ResourceLoadError(response.status === 404 || response.status === 403 ? "unavailable" : "loadFailed");
        const body: unknown = await response.json();
        const resource: Resource = kind === "run" ? { kind, value: runSchema.parse(body) } : { kind, value: trackSchema.parse(body) };
        if (resource.value.id !== id) throw new ResourceLoadError("identityMismatch");
        if (resource.kind === "run" && resource.value.status === "succeeded" && !resource.value.result) throw new ResourceLoadError("resultUnavailable");
        if (!controller.signal.aborted) setState({ id, resource, loadedAt: new Date().toISOString() });
      } catch (error) {
        if (!controller.signal.aborted) setState({ id, errorCode: error instanceof z.ZodError ? "invalidResponse" : error instanceof ResourceLoadError ? error.code : "loadFailed" });
      }
    })();
    return () => controller.abort();
  }, [href, id, kind, revision]);
  const current = state?.id === id ? state : null;
  return <section className="chat-a2ui-domain-section chat-a2ui-resource" aria-label={`${kind === "run" ? "ResearchRun" : "DailyTrack"} ${id}`}>
    <header><a className="chat-a2ui-navigation" href={href}>{id}</a><button type="button" disabled={current === null} onClick={() => setRevision((value) => value + 1)}>{t("a2ui.reload")}</button></header>
    {current === null ? <p role="status">{t("a2ui.loadingData")}</p> : "errorCode" in current ? <p role="alert">{t(`a2ui.${current.errorCode}`)}</p> : <>
      <ResourceFacts resource={current.resource} />
      <small><Trans i18nKey="a2ui.readAt" ns="chat" values={{ time: formatTimestamp(current.loadedAt, { hour: "numeric", minute: "2-digit" }) }} components={{ time: <time dateTime={current.loadedAt} /> }} /></small>
    </>}
  </section>;
}

function ResourceFacts({ resource }: { resource: Resource }) {
  const { t } = useTranslation("chat");
  if (resource.kind === "track") {
    const track = resource.value;
    return <><h2>{i18n.t("daily:track")}</h2><p>{i18n.t(`daily:statuses.${track.status}`)}</p>
      <dl className="chat-a2ui-facts"><Fact label={t("a2ui.originRun")} value={track.origin.seed_run_id} /><Fact label={t("a2ui.trackingSession")} value={track.strategy_session} /><Fact label={t("a2ui.dataThrough")} value={track.data_through_session} /><Fact label={t("a2ui.observationSession")} value={track.observation.session} /><Fact label={t("a2ui.trackingReturn")} value={formatMetric(track.observation.net_return, true)} /><Fact label={t("a2ui.maxDrawdown")} value={formatMetric(track.observation.maximum_drawdown, true)} /></dl>
      {track.status === "blocked" ? <p>{blockedReason(track.blocked_code)}</p> : null}</>;
  }
  const run = resource.value;
  const result = run.status === "succeeded" ? run.result : undefined;
  const factor = run.research_kind === "factor_evaluation" ? run.result?.factor : undefined;
  const strategy = run.research_kind === "strategy_backtest" ? run.result?.strategy : undefined;
  return <><h2>{run.name}</h2><p>{i18n.t(`runs:statuses.${run.status}`)} · {t(run.research_kind === "factor_evaluation" ? "a2ui.factorEvaluation" : "a2ui.strategyBacktest")}</p>
    <p>{run.start_date} — {run.end_date}</p><code>{run.formula_summary}</code>
    {run.failure_reason ? <p role="alert">{formatExecutionFailure(run.failure_reason)}</p> : null}
    {result ? <dl className="chat-a2ui-metrics">
      {factor ? (["1", "5", "20"] as const).map((horizon) => <Fact key={horizon} label={`${horizon}S Rank IC`} value={formatMetric(factor.horizons[horizon].summary.rank_ic.mean)} />) : null}
      {strategy ? <><Fact label={t("a2ui.annualizedExcess")} value={formatMetric(strategy.summary.metrics.annualized_excess_return, true)} /><Fact label={t("a2ui.sharpe")} value={formatMetric(strategy.summary.metrics.sharpe)} /><Fact label={t("a2ui.maxDrawdown")} value={formatMetric(strategy.summary.metrics.maximum_drawdown.value, true)} /></> : null}
    </dl> : <p>{t("a2ui.resultPending")}</p>}</>;
}
function Fact({ label, value }: { label: string; value: string }) { return <div><dt>{label}</dt><dd>{value}</dd></div>; }
function formatMetric(value: number | null, percent = false): string { return percent ? formatPercent(value) : formatDecimal(value); }
