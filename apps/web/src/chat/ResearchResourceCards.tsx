import { useEffect, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { z } from "zod";
import { coreFetch } from "../auth/coreFetch";
import { i18n } from "../i18n";
import { formatDecimal, formatPercent, formatTimestamp } from "../i18n/format";
import { blockedReason } from "../daily-tracks/blockedReason";
import { formatExecutionFailure } from "../research-runs/errors";

import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Card, CardHeader, CardContent, CardFooter } from "../components/ui/card";
import { MetricGroup, Metric } from "../components/product/MetricGroup";
import styles from "./A2UISurfaces.module.css";

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
type State = { id: string; resource: Resource; loadedAt: string; errorCode?: ResourceErrorCode } | { id: string; errorCode: ResourceErrorCode };
class ResourceLoadError extends Error { constructor(readonly code: ResourceErrorCode) { super(code); } }

export function ResearchResourceCards({ kind, ids }: { kind: "run" | "track"; ids: string[] }) {
  return <div className={styles.column}>{ids.map((id) => <ResourceCard key={`${kind}:${id}`} kind={kind} id={id} />)}</div>;
}

function ResourceCard({ kind, id }: { kind: "run" | "track"; id: string }) {
  const { t } = useTranslation("chat");
  const [state, setState] = useState<State | null>(null);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const href = kind === "run" ? `/research-runs/${id}` : `/daily-tracks/${id}`;
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setState(previous => previous?.id === id && "resource" in previous ? { id, resource: previous.resource, loadedAt: previous.loadedAt } : null);
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
        if (!controller.signal.aborted) {
          const errorCode = error instanceof z.ZodError || error instanceof SyntaxError ? "invalidResponse" : error instanceof ResourceLoadError ? error.code : "loadFailed";
          setState(previous => errorCode === "loadFailed" && previous?.id === id && "resource" in previous
            ? { ...previous, errorCode } : { id, errorCode });
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [href, id, kind, revision]);
  const current = state?.id === id ? state : null;
  const snapshot = current && "resource" in current ? current : null;
  return <section aria-label={`${kind === "run" ? "ResearchRun" : "DailyTrack"} ${id}`}>
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <Button variant="link" className="h-auto min-h-11 min-w-0 whitespace-normal break-all text-left" nativeButton={false} role="link" render={<a href={href} />}>{id}</Button>
        <Button variant="outline" disabled={loading} onClick={() => { setLoading(true); setRevision(value => value + 1); }}>{t("a2ui.reload")}</Button>
      </CardHeader>
      <CardContent className={styles.column}>
        {loading ? <p role="status">{t("a2ui.loadingData")}</p> : null}
        {current?.errorCode ? <p role="alert" className={styles.error}>{t(`a2ui.${current.errorCode}`)}</p> : null}
        {snapshot ? <ResourceFacts resource={snapshot.resource} /> : null}
      </CardContent>
      {snapshot ? <CardFooter><small><Trans i18nKey="a2ui.readAt" ns="chat" values={{ time: formatTimestamp(snapshot.loadedAt, { hour: "numeric", minute: "2-digit" }) }} components={{ time: <time dateTime={snapshot.loadedAt} /> }} /></small></CardFooter> : null}
    </Card>
  </section>;
}

function ResourceFacts({ resource }: { resource: Resource }) {
  const { t } = useTranslation("chat");
  if (resource.kind === "track") {
    const track = resource.value;
    return <><h2 className={styles.title}>{i18n.t("daily:track")}</h2><Badge variant={track.status === "blocked" ? "destructive" : "secondary"}>{i18n.t(`daily:statuses.${track.status}`)}</Badge>
      <dl className={styles.facts}><Fact label={t("a2ui.originRun")} value={track.origin.seed_run_id} /><Fact label={t("a2ui.trackingSession")} value={track.strategy_session} /><Fact label={t("a2ui.dataThrough")} value={track.data_through_session} /><Fact label={t("a2ui.observationSession")} value={track.observation.session} /><Fact label={t("a2ui.trackingReturn")} value={formatMetric(track.observation.net_return, true)} /><Fact label={t("a2ui.maxDrawdown")} value={formatMetric(track.observation.maximum_drawdown, true)} /></dl>
      {track.status === "blocked" ? <p>{blockedReason(track.blocked_code)}</p> : null}</>;
  }
  const run = resource.value;
  const result = run.status === "succeeded" ? run.result : undefined;
  const factor = run.research_kind === "factor_evaluation" ? run.result?.factor : undefined;
  const strategy = run.research_kind === "strategy_backtest" ? run.result?.strategy : undefined;
  return <><h2 className={styles.title}>{run.name}</h2><div className={styles.row}><Badge variant={run.status === "failed" ? "destructive" : run.status === "succeeded" ? "default" : "outline"}>{i18n.t(`runs:statuses.${run.status}`)}</Badge><span>{t(run.research_kind === "factor_evaluation" ? "a2ui.factorEvaluation" : "a2ui.strategyBacktest")}</span></div>
    <p>{run.start_date} — {run.end_date}</p><code className={styles.code}>{run.formula_summary}</code>
    {run.failure_reason ? <p role="alert">{formatExecutionFailure(run.failure_reason)}</p> : null}
    {result ? <MetricGroup label={run.name} className="chat-a2ui-metrics m-0 sm:grid-cols-3">
      {factor ? (["1", "5", "20"] as const).map((horizon) => <Metric key={horizon} label={`${horizon}S Rank IC`} value={formatMetric(factor.horizons[horizon].summary.rank_ic.mean)} />) : null}
      {strategy ? <><Metric label={t("a2ui.annualizedExcess")} value={formatMetric(strategy.summary.metrics.annualized_excess_return, true)} /><Metric label={t("a2ui.sharpe")} value={formatMetric(strategy.summary.metrics.sharpe)} /><Metric label={t("a2ui.maxDrawdown")} value={formatMetric(strategy.summary.metrics.maximum_drawdown.value, true)} /></> : null}
    </MetricGroup> : <p>{t("a2ui.resultPending")}</p>}</>;
}
function Fact({ label, value }: { label: string; value: string }) { return <div><dt>{label}</dt><dd>{value}</dd></div>; }
function formatMetric(value: number | null, percent = false): string { return percent ? formatPercent(value) : formatDecimal(value); }
