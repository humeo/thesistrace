import { createContext, useContext } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Trans, useTranslation } from "react-i18next";
import { z } from "zod";
import { ArrowClockwiseIcon } from "@phosphor-icons/react";
import "./researchResourceList.css";
import { coreFetch } from "../auth/coreFetch";
import { followCoreLink } from "../shell/navigation";
import { i18n } from "../i18n";
import { formatDecimal, formatPercent, formatTimestamp } from "../i18n/format";
import { blockedReason } from "../daily-tracks/blockedReason";
import { formatExecutionFailure } from "../research-runs/errors";

import { Alert, Button, Descriptions, Flex, Listy, Space, Spin, Tag, Tooltip, Typography } from "antd";

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
type ResourceRead = { snapshot: { resource: Resource; loadedAt: string } | null; errorCode?: ResourceErrorCode };
class ResourceLoadError extends Error { constructor(readonly code: ResourceErrorCode) { super(code); } }
export const ResearchResourceDetailsContext = createContext<ReadonlySet<string> | null>(null);

export function ResearchResourceList({ kind, ids }: { kind: "run" | "track"; ids: string[] }) {
  const details = useContext(ResearchResourceDetailsContext);
  const { t } = useTranslation("chat");
  return <div role="list"><Listy items={ids} rowKey={id => `${kind}:${id}`} virtual={false}
    classNames={{ item: "chat-research-list-row" }}
    itemRender={id => <div role="listitem">{details === null || details.has(id) ? <ResourceRow kind={kind} id={id} />
      : <Typography.Link href={resourceHref(kind, id)} onClick={followCoreLink}>{t(kind === "run" ? "a2ui.researchLink" : "a2ui.trackLink", { id })}</Typography.Link>}
    </div>} /></div>;
}

function resourceHref(kind: "run" | "track", id: string) { return kind === "run" ? `/research-runs/${id}` : `/daily-tracks/${id}`; }

async function readResource(kind: "run" | "track", id: string, signal: AbortSignal): Promise<Resource> {
  const timeoutController = new AbortController();
  const requestSignal = AbortSignal.any([signal, timeoutController.signal]);
  let timeout: ReturnType<typeof setTimeout> | undefined;
  let removeAbortListener: (() => void) | undefined;
  try {
    return await Promise.race([
      (async (): Promise<Resource> => {
        const response = await coreFetch(`/api${resourceHref(kind, id)}`, { signal: requestSignal });
        if (!response.ok) throw new ResourceLoadError(response.status === 404 || response.status === 403 ? "unavailable" : "loadFailed");
        const body: unknown = await response.json();
        const resource: Resource = kind === "run" ? { kind, value: runSchema.parse(body) } : { kind, value: trackSchema.parse(body) };
        if (resource.value.id !== id) throw new ResourceLoadError("identityMismatch");
        if (resource.kind === "run" && resource.value.status === "succeeded" && !resource.value.result) throw new ResourceLoadError("resultUnavailable");
        return resource;
      })(),
      new Promise<never>((_, reject) => {
        const abort = () => reject(new ResourceLoadError("loadFailed"));
        if (requestSignal.aborted) { abort(); return; }
        requestSignal.addEventListener("abort", abort, { once: true });
        removeAbortListener = () => requestSignal.removeEventListener("abort", abort);
        // Bound headers and body together; a late response cannot replace a retry.
        timeout = setTimeout(() => timeoutController.abort(), 15_000);
      }),
    ]);
  } catch (error) {
    throw new ResourceLoadError(error instanceof z.ZodError || error instanceof SyntaxError ? "invalidResponse" : error instanceof ResourceLoadError ? error.code : "loadFailed");
  } finally {
    clearTimeout(timeout);
    removeAbortListener?.();
  }
}

function ResourceRow({ kind, id }: { kind: "run" | "track"; id: string }) {
  const { t } = useTranslation("chat");
  const href = resourceHref(kind, id);
  const client = useQueryClient();
  const queryKey = ["chat-research", kind, id] as const;
  const { data, error, isFetching: loading, refetch } = useQuery<ResourceRead, ResourceLoadError>({
    queryKey,
    queryFn: async ({ signal }) => {
      try {
        const resource = await readResource(kind, id, signal);
        return { snapshot: { resource, loadedAt: new Date().toISOString() } };
      } catch (error) {
        if (signal.aborted) throw error;
        const errorCode = error instanceof ResourceLoadError ? error.code : "loadFailed";
        // Clear inaccessible or invalid facts in the shared result itself, so
        // a later transient failure cannot revive them in another occurrence.
        return { errorCode, snapshot: errorCode === "loadFailed" ? client.getQueryData<ResourceRead>(queryKey)?.snapshot ?? null : null };
      }
    },
    staleTime: query => {
      const resource = query.state.data?.snapshot?.resource;
      // A new reference to ongoing work must be able to observe its completion.
      return resource && !["succeeded", "failed", "cancelled", "stopped"].includes(resource.value.status) ? 0 : Infinity;
    },
  });
  const snapshot = data?.snapshot;
  const readAt = snapshot ? formatTimestamp(snapshot.loadedAt, { year: "numeric", month: "2-digit", day: "2-digit", hour: "numeric", minute: "2-digit" }) : "";
  const errorCode = data?.errorCode ?? error?.code;
  const resource = snapshot?.resource;
  const title = resource?.kind === "run" ? resource.value.name : resource?.kind === "track" ? i18n.t("daily:track") : id;
  return <section aria-label={`${kind === "run" ? "ResearchRun" : "DailyTrack"} ${id}`}>
      <Flex vertical gap={4}>
        <Flex justify="space-between" align="center" gap="small">
          <Flex align="center" gap="small" wrap>
            <Typography.Link href={href} onClick={followCoreLink} strong>{title}</Typography.Link>
            {resource ? <ResourceStatus resource={resource} /> : null}
          </Flex>
          <Space size="small">
            {snapshot ? <Tooltip title={<Trans i18nKey="a2ui.readAt" ns="chat" values={{ time: readAt }} components={{ time: <span /> }} />}>
              <Typography.Text type="secondary"><time dateTime={snapshot.loadedAt}>{t("a2ui.readTime", { time: readAt })}</time></Typography.Text>
            </Tooltip> : null}
            <Tooltip title={t("a2ui.reload")}><Button type="text" size="small" loading={loading}
              icon={<ArrowClockwiseIcon size={16} />} aria-label={`${t("a2ui.reload")}: ${title}`}
              onClick={() => { void refetch({ cancelRefetch: false }); }} /></Tooltip>
          </Space>
        </Flex>
        {loading ? <Flex gap={8} align="center" role="status"><Spin size="small" /><Typography.Text>{t("a2ui.loadingData")}</Typography.Text></Flex> : null}
        {errorCode ? <Alert type="error" role="alert" title={t(`a2ui.${errorCode}`)} /> : null}
        {resource ? <ResourceFacts resource={resource} /> : null}
      </Flex>
  </section>;
}

function ResourceStatus({ resource }: { resource: Resource }) {
  const { t } = useTranslation("chat");
  if (resource.kind === "track") return <Tag color={resource.value.status === "blocked" ? "error" : "default"}>{i18n.t(`daily:statuses.${resource.value.status}`)}</Tag>;
  const run = resource.value;
  return <><Tag color={run.status === "failed" ? "error" : run.status === "succeeded" ? "success" : "default"}>{i18n.t(`runs:statuses.${run.status}`)}</Tag>
    <Typography.Text type="secondary">{t(run.research_kind === "factor_evaluation" ? "a2ui.factorEvaluation" : "a2ui.strategyBacktest")}</Typography.Text></>;
}

function ResourceFacts({ resource }: { resource: Resource }) {
  const { t } = useTranslation("chat");
  if (resource.kind === "track") {
    const track = resource.value;
    return <><Descriptions size="small" column={2} items={[
        { key: "origin", label: t("a2ui.originRun"), children: <Typography.Link href={`/research-runs/${track.origin.seed_run_id}`} onClick={followCoreLink}>{track.origin.seed_run_id}</Typography.Link> },
        { key: "session", label: t("a2ui.trackingSession"), children: track.strategy_session },
        { key: "data", label: t("a2ui.dataThrough"), children: track.data_through_session },
        { key: "observation", label: t("a2ui.observationSession"), children: track.observation.session },
        { key: "return", label: t("a2ui.trackingReturn"), children: <span aria-label={track.observation.net_return === null ? i18n.t("common:notAvailable") : undefined}>{formatMetric(track.observation.net_return, true)}</span> },
        { key: "drawdown", label: t("a2ui.maxDrawdown"), children: <span aria-label={track.observation.maximum_drawdown === null ? i18n.t("common:notAvailable") : undefined}>{formatMetric(track.observation.maximum_drawdown, true)}</span> },
      ]} />
      {track.status === "blocked" ? <Alert type="warning" title={blockedReason(track.blocked_code)} /> : null}</>;
  }
  const run = resource.value;
  const result = run.status === "succeeded" ? run.result : undefined;
  const factor = run.research_kind === "factor_evaluation" ? run.result?.factor : undefined;
  const strategy = run.research_kind === "strategy_backtest" ? run.result?.strategy : undefined;
  const metrics: { title: string; value: number | null; percent?: boolean }[] = factor
    ? (["1", "5", "20"] as const).map(horizon => ({ title: `${horizon}S Rank IC`, value: factor.horizons[horizon].summary.rank_ic.mean }))
    : strategy ? [
      { title: t("a2ui.annualizedExcess"), value: strategy.summary.metrics.annualized_excess_return, percent: true },
      { title: t("a2ui.sharpe"), value: strategy.summary.metrics.sharpe },
      { title: t("a2ui.maxDrawdown"), value: strategy.summary.metrics.maximum_drawdown.value, percent: true },
    ] : [];
  return <>
    {result ? <Space size="middle" wrap aria-label={run.name}>{metrics.map(entry => <Typography.Text key={entry.title}>
      <Typography.Text type="secondary">{entry.title} </Typography.Text>
      <Typography.Text strong aria-label={entry.value === null ? i18n.t("common:notAvailable") : undefined}>{formatMetric(entry.value, entry.percent)}</Typography.Text>
    </Typography.Text>)}</Space> : <Typography.Text type="secondary">{t("a2ui.resultPending")}</Typography.Text>}
    <Flex gap="small" align="center" wrap>
      <Typography.Text type="secondary">{run.start_date} — {run.end_date}</Typography.Text>
      <Typography.Text code style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{run.formula_summary}</Typography.Text>
    </Flex>
    {run.failure_reason ? <Alert type="error" role="alert" title={formatExecutionFailure(run.failure_reason)} /> : null}
  </>;
}
function formatMetric(value: number | null, percent = false): string { return percent ? formatPercent(value, { missing: "dash" }) : formatDecimal(value, 3, "dash"); }
