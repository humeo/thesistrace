import { useEffect, useState } from "react";
import { z } from "zod";
import { coreFetch } from "../auth/coreFetch";

const metric = z.number().finite().nullable();
const strategyMetrics = z.object({ annualized_excess_return: metric, sharpe: metric, maximum_drawdown: z.object({ value: metric }) });
const runSchema = z.object({
  id: z.string(), name: z.string(), status: z.enum(["queued", "running", "cancelling", "succeeded", "failed", "cancelled"]),
  formula_summary: z.string(), start_date: z.string(), end_date: z.string(),
  research_kind: z.enum(["factor_evaluation", "strategy_backtest"]), failure_reason: z.string().optional(),
  result: z.object({
    factor: z.object({ horizons: z.object({
      "1": z.object({ summary: z.object({ rank_ic: z.object({ mean: metric }) }) }),
      "5": z.object({ summary: z.object({ rank_ic: z.object({ mean: metric }) }) }),
      "20": z.object({ summary: z.object({ rank_ic: z.object({ mean: metric }) }) }),
    }) }),
    strategy: z.object({ summary: z.object({ metrics: strategyMetrics }) }).optional(),
  }).optional(),
});
const trackSchema = z.object({
  id: z.string(), status: z.enum(["active", "blocked", "stopping", "stopped"]),
  origin: z.object({ seed_run_id: z.string(), strategy_session: z.string() }),
  strategy_session: z.string(), data_through_session: z.string(), blocked_reason: z.string().nullable(),
  observation: z.object({ net_return: metric, maximum_drawdown: metric, session: z.string() }),
});
type Resource = { kind: "run"; value: z.infer<typeof runSchema> } | { kind: "track"; value: z.infer<typeof trackSchema> };
type State = { id: string; resource: Resource; loadedAt: string } | { id: string; error: string };

export function ResearchResourceCards({ kind, ids }: { kind: "run" | "track"; ids: string[] }) {
  return <div className="chat-a2ui-column">{ids.map((id) => <ResourceCard key={`${kind}:${id}`} kind={kind} id={id} />)}</div>;
}

function ResourceCard({ kind, id }: { kind: "run" | "track"; id: string }) {
  const [state, setState] = useState<State | null>(null);
  const [revision, setRevision] = useState(0);
  const href = kind === "run" ? `/research-runs/${id}` : `/daily-tracks/${id}`;
  useEffect(() => {
    const controller = new AbortController();
    setState(null);
    void (async () => {
      try {
        const response = await coreFetch(`/api${href}`, { signal: controller.signal });
        if (!response.ok) throw new Error(response.status === 404 || response.status === 403 ? "Resource unavailable or access denied." : "Research data could not be loaded.");
        const body: unknown = await response.json();
        const resource: Resource = kind === "run" ? { kind, value: runSchema.parse(body) } : { kind, value: trackSchema.parse(body) };
        if (resource.value.id !== id) throw new Error("Research response identity mismatch.");
        if (resource.kind === "run" && resource.value.status === "succeeded" && (!resource.value.result || (resource.value.research_kind === "strategy_backtest" && !resource.value.result.strategy))) throw new Error("Completed research result is unavailable.");
        if (!controller.signal.aborted) setState({ id, resource, loadedAt: new Date().toISOString() });
      } catch (error) {
        if (!controller.signal.aborted) setState({ id, error: error instanceof z.ZodError ? "Research response is invalid." : error instanceof Error ? error.message : "Research data could not be loaded." });
      }
    })();
    return () => controller.abort();
  }, [href, id, kind, revision]);
  const current = state?.id === id ? state : null;
  return <section className="chat-a2ui-domain-section chat-a2ui-resource" aria-label={`${kind === "run" ? "ResearchRun" : "DailyTrack"} ${id}`}>
    <header><a className="chat-a2ui-navigation" href={href}>{id}</a><button type="button" disabled={current === null} onClick={() => setRevision((value) => value + 1)}>Reload view</button></header>
    {current === null ? <p role="status">Loading research data…</p> : "error" in current ? <p role="alert">{current.error}</p> : <>
      <ResourceFacts resource={current.resource} />
      <small>Read from Core at <time dateTime={current.loadedAt}>{new Date(current.loadedAt).toLocaleTimeString()}</time>. Reload to check for changes.</small>
    </>}
  </section>;
}

function ResourceFacts({ resource }: { resource: Resource }) {
  if (resource.kind === "track") {
    const track = resource.value;
    return <><h2>DailyTrack</h2><p>{track.status}</p>
      <dl className="chat-a2ui-facts"><Fact label="Origin ResearchRun" value={track.origin.seed_run_id} /><Fact label="Tracking session" value={track.strategy_session} /><Fact label="Data through" value={track.data_through_session} /><Fact label="Observation session" value={track.observation.session} /><Fact label="Return since tracking" value={formatMetric(track.observation.net_return, true)} /><Fact label="Maximum drawdown" value={formatMetric(track.observation.maximum_drawdown, true)} /></dl>
      {track.blocked_reason !== null ? <p>{track.blocked_reason}</p> : null}</>;
  }
  const run = resource.value;
  const result = run.status === "succeeded" ? run.result : undefined;
  return <><h2>{run.name}</h2><p>{run.status} · {run.research_kind === "factor_evaluation" ? "Factor Evaluation" : "Strategy Backtest"}</p>
    <p>{run.start_date} — {run.end_date}</p><code>{run.formula_summary}</code>
    {run.failure_reason ? <p role="alert">{run.failure_reason}</p> : null}
    {result ? <dl className="chat-a2ui-metrics">
      {(["1", "5", "20"] as const).map((horizon) => <Fact key={horizon} label={`${horizon}S Rank IC`} value={formatMetric(result.factor.horizons[horizon].summary.rank_ic.mean)} />)}
      {result.strategy ? <><Fact label="Annualized excess return" value={formatMetric(result.strategy.summary.metrics.annualized_excess_return, true)} /><Fact label="Sharpe" value={formatMetric(result.strategy.summary.metrics.sharpe)} /><Fact label="Maximum drawdown" value={formatMetric(result.strategy.summary.metrics.maximum_drawdown.value, true)} /></> : null}
    </dl> : <p>Results are available after this research succeeds.</p>}</>;
}
function Fact({ label, value }: { label: string; value: string }) { return <div><dt>{label}</dt><dd>{value}</dd></div>; }
function formatMetric(value: number | null, percent = false): string { return value === null ? "Not available" : percent ? `${(value * 100).toFixed(2)}%` : value.toFixed(3); }
