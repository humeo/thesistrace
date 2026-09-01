import type { LanguageModelV3CallOptions } from "@ai-sdk/provider";

import {
  projectResearchA2UIContent,
  RESEARCH_A2UI_CATALOG_ID,
  RESEARCH_A2UI_PROTOCOL_VERSION,
} from "../../contracts/research-a2ui.mjs";
import {
  boundedConstraintDefault,
  boundedWindowStart,
  effectRequestId,
  factorSurfaceMetrics,
  isRecord,
  latestSuccessfulOutput,
  latestUnresolvedTransportFailure,
  latestUserText,
  preferredEnum,
  readRetryAfter,
  requiredTool,
  strategySurfaceMetrics,
  textContent,
  toolObservations,
  type JsonRecord,
  type ScriptedResearchDecision,
  type ToolObservation,
} from "./scripted-research-support.js";

export const SCRIPTED_FACTOR_BATCH_PROMPT =
  "Compare positive and negative price-rank Alpha signals as Factor Evaluations.";
export const SCRIPTED_STRATEGY_SWEEP_PROMPT =
  "Compare focused and broad holdings for a price-rank Alpha strategy.";
export const SCRIPTED_RESUME_BATCH_PROMPT =
  "Resume the Research Batch from this Chat and explain each authoritative Child Result.";
export const SCRIPTED_BATCH_LIST_PROMPT = "List my recent Research Batches.";
export const SCRIPTED_BATCH_OBSERVATIONS_PROMPT =
  "Inspect all paginated strategy observations for the first child of this Batch.";
export const SCRIPTED_AMBIGUOUS_BATCH_PROMPT = "Compare some research for me.";

const MAX_POLLS = 3;
const MAX_RESULT_PAGES = 3;
const BATCH_ID = /^batch_[a-f0-9]{20}$/;
const RUN_ID = /^run_[a-f0-9]{20}$/;
const ACTIVE_STATUSES = new Set(["queued", "running", "cancelling"]);
const TERMINAL_STATUSES = new Set(["succeeded", "completed_with_failures", "failed", "cancelled"]);
const FACTORS = [
  { item_key: "positive-price-rank", name: "Positive price rank", formula: "rank(close)" },
  { item_key: "negative-price-rank", name: "Negative price rank", formula: "-rank(close)" },
] as const;

type BatchMode = "factor_evaluation" | "strategy_sweep";
type BatchItem = Readonly<{
  item_key: string;
  ordinal: number;
  research_run_id: string;
  run_availability: "available" | "deleted";
  status: string;
}>;
type BatchDetail = JsonRecord & Readonly<{
  id: string;
  batch_kind: BatchMode;
  items: readonly BatchItem[];
  status: string;
}>;

// This adapter is a deterministic model fixture. No part of its command or
// sequencing logic runs in the production Host when a real model is selected.
export function scriptedBatchDecision(
  options: LanguageModelV3CallOptions,
): ScriptedResearchDecision | null {
  const latest = latestUserText(options);
  if (latest === undefined) return null;
  if (latest.text === SCRIPTED_AMBIGUOUS_BATCH_PROMPT) {
    return text("Which Alpha signals or Strategy configurations should I compare? A useful comparison needs an investment question.");
  }
  if (latest.text === SCRIPTED_BATCH_LIST_PROMPT) {
    const observations = toolObservations(options, latest.index);
    const failure = toolFailureDecision(options, observations);
    if (failure !== null) return failure;
    const page = latestSuccessfulOutput(observations, "list_research_batches");
    if (page === undefined) return requiredTool(options, "list_research_batches", { limit: 20 });
    if (!Array.isArray(page.items)) return incomplete();
    const items = page.items.filter(isRecord);
    if (items.some((item) => typeof item.id !== "string" || !BATCH_ID.test(item.id))) return incomplete();
    return text(items.length === 0
      ? "No Research Batches are available in this Researcher account."
      : items.map((item) => `${String(item.id)}: ${String(item.status)}`).join("\n")
        + (typeof page.next_cursor === "string" ? "\nMore Research Batches are available; this is one bounded recent page." : ""));
  }

  const mode = batchMode(latest.text);
  const resume = latest.text === SCRIPTED_RESUME_BATCH_PROMPT;
  const inspectPages = latest.text === SCRIPTED_BATCH_OBSERVATIONS_PROMPT;
  if (mode === null && !resume && !inspectPages) return null;
  const original = mode === null ? previousBatchIdea(options, latest.index) : { index: latest.index, mode };
  if (original === null) return text("This Chat has no prior Batch comparison to resume.");
  const observations = toolObservations(options, original.index);
  if (resume) {
    const unresolved = latestUnresolvedTransportFailure(observations);
    if (unresolved !== undefined) return requiredTool(options, unresolved.name, unresolved.input);
  }
  const failure = toolFailureDecision(options, observations);
  if (failure !== null) return failure;
  const accepted = observations.find((item) => item.name === "submit_research_batch"
    && item.output.outcome === "accepted");
  if (accepted === undefined) {
    if (inspectPages) return text("No accepted Batch is available for result inspection.");
    return prepareAdmission(options, original.mode, observations);
  }
  const batchId = accepted.output.batch_id;
  if (typeof batchId !== "string" || !BATCH_ID.test(batchId)) return incomplete();
  const polls = observations.filter((item) => item.name === "get_research_batch"
    && item.input.batch_id === batchId);
  const currentPolls = polls.filter((item) => item.promptIndex > latest.index);
  const poll = polls.at(-1);
  if (poll === undefined || (resume && currentPolls.length === 0)) {
    return requiredTool(options, "get_research_batch", { batch_id: batchId }, readRetryAfter(accepted.output));
  }
  const detail = readBatchDetail(poll.output, batchId, original.mode);
  if (detail === null) return incomplete();
  if (inspectPages) return inspectObservations(options, detail, observations, latest.index);
  if (ACTIVE_STATUSES.has(detail.status)) {
    const progressId = `batch-progress-${currentPolls[0]?.toolCallId ?? poll.toolCallId}`;
    if (!hasSurface(observations, progressId)) {
      return renderBatch(options, detail, [], progressId, false);
    }
    const wait = readRetryAfter(detail);
    return currentPolls.length < MAX_POLLS && wait !== undefined
      ? requiredTool(options, "get_research_batch", { batch_id: batchId }, wait)
      : text(`Research Batch ${batchId} is ${detail.status}. This bounded Agent Run is ending; Core continues independently. Resume this Chat when you want another progress check.`);
  }

  const rows: string[][] = [];
  for (const item of detail.items) {
    const row = [String(item.ordinal), item.item_key, item.research_run_id, item.status];
    if (item.status !== "succeeded" || item.run_availability === "deleted") {
      rows.push([...row, item.run_availability === "deleted" ? "ResearchRun deleted" : "No successful Result"]);
      continue;
    }
    const child = [...observations].reverse().find((observation) => observation.name === "get_research_run"
      && observation.input.run_id === item.research_run_id);
    if (child === undefined) return requiredTool(options, "get_research_run", { run_id: item.research_run_id });
    const section = original.mode === "factor_evaluation" ? "factor" : "strategy_summary";
    if (child.output.id !== item.research_run_id || child.output.status !== "succeeded"
      || !Array.isArray(child.output.available_result_sections)
      || !child.output.available_result_sections.includes(section)) return incomplete();
    const result = [...observations].reverse().find((observation) => observation.name === "get_research_run_result"
      && observation.input.run_id === item.research_run_id && observation.input.section === section);
    if (result === undefined) return requiredTool(options, "get_research_run_result", { run_id: item.research_run_id, section });
    if (result.output.run_id !== item.research_run_id || result.output.section !== section) return incomplete();
    const metrics = original.mode === "factor_evaluation"
      ? factorSurfaceMetrics(result.output) : strategySurfaceMetrics(result.output);
    if (metrics === null) return incomplete();
    rows.push([...row, metrics.map((metric) => `${String(metric.label)}: ${String(metric.value)}`).join("; ")]);
  }
  const surfaceId = `batch-results-${poll.toolCallId}`;
  if (!hasSurface(observations, surfaceId)) return renderBatch(options, detail, rows, surfaceId, true);
  return text(`Research Batch ${batchId} is ${detail.status}. Each row refers to its own authoritative ResearchRun Result, not a combined Batch Result.\n\n`
    + rows.map((row) => `${row[0]}. ${row[1]} — [${row[2]}](/research-runs/${row[2]}): ${row[3]}. ${row[4]}`).join("\n")
    + (detail.status === "completed_with_failures" ? "\nSome children failed; their missing metrics are not zero and do not invalidate successful sibling Results." : ""));
}

function prepareAdmission(
  options: LanguageModelV3CallOptions,
  mode: BatchMode,
  observations: readonly ToolObservation[],
): ScriptedResearchDecision {
  const rejected = [...observations].reverse().find((item) => item.name === "submit_research_batch"
    && item.output.outcome === "rejected");
  if (rejected !== undefined) {
    const codes = Array.isArray(rejected.output.issues)
      ? rejected.output.issues.filter(isRecord).map((issue) => issue.code).filter((code) => typeof code === "string").slice(0, 3)
      : [];
    return text(`Core rejected Batch admission${codes.length > 0 ? `: ${codes.join(", ")}` : ""}. No Batch or child ResearchRun was created. Clarify or revise the comparison before submitting a changed command.`);
  }
  const context = latestSuccessfulOutput(observations, "get_research_context");
  if (context === undefined) return requiredTool(options, "get_research_context", {});
  const catalog = latestSuccessfulOutput(observations, "get_alpha_catalog");
  if (catalog === undefined) return requiredTool(options, "get_alpha_catalog", { identifiers: ["close", "rank"] });
  if (!Array.isArray(catalog.unknown_identifiers) || catalog.unknown_identifiers.length > 0) return incomplete();
  for (const formula of mode === "factor_evaluation" ? FACTORS.map((factor) => factor.formula) : ["rank(close)"]) {
    const diagnostic = [...observations].reverse().find((item) => item.name === "diagnose_alpha_formula" && item.input.source === formula);
    if (diagnostic === undefined) return requiredTool(options, "diagnose_alpha_formula", { source: formula });
    if (diagnostic.output.valid !== true) return text("The proposed Batch contains an invalid Formula. I did not admit any children.");
  }
  const requestId = effectRequestId(options, "batch", 1);
  if (requestId === null) return text("A validated Agent Run identity is required before submitting a Batch.");
  const command = batchCommand(context, mode, requestId);
  return command === null ? incomplete() : requiredTool(options, "submit_research_batch", command);
}

function batchCommand(context: JsonRecord, mode: BatchMode, requestId: string): JsonRecord | null {
  const overview = isRecord(context.data_overview) ? context.data_overview : undefined;
  const coverage = isRecord(overview?.market_coverage) ? overview.market_coverage : undefined;
  if (typeof coverage?.start !== "string" || typeof coverage.end !== "string") return null;
  const start = boundedWindowStart(coverage.start, coverage.end);
  const universe = preferredEnum(context, "universes", "top1000");
  const neutralization = preferredEnum(context, "neutralizations", "none");
  if (start === null || universe === null || neutralization === null) return null;
  const common = { batch_kind: mode, start_date: start, end_date: coverage.end, universe, neutralization, request_id: requestId };
  if (mode === "factor_evaluation") return { ...common, factors: FACTORS.map((factor) => ({ ...factor })) };
  const focused = boundedConstraintDefault(context, "holdings_count", 10);
  const broad = boundedConstraintDefault(context, "holdings_count", 20);
  const rebalance = boundedConstraintDefault(context, "rebalance_every_sessions", 5);
  if (focused === null || broad === null || focused === broad || rebalance === null) return null;
  return {
    ...common,
    alpha: { formula: "rank(close)", hypothesis: "Compare portfolio breadth while holding the price-rank Alpha and rebalance schedule fixed." },
    strategies: [
      { item_key: "focused-holdings", name: "Focused holdings", holdings_count: focused, rebalance_every_sessions: rebalance },
      { item_key: "broad-holdings", name: "Broad holdings", holdings_count: broad, rebalance_every_sessions: rebalance },
    ],
  };
}

function readBatchDetail(value: JsonRecord, id: string, mode: BatchMode): BatchDetail | null {
  if (value.id !== id || value.batch_kind !== mode || typeof value.status !== "string"
    || (!ACTIVE_STATUSES.has(value.status) && !TERMINAL_STATUSES.has(value.status))
    || !Array.isArray(value.items) || value.items.length < 1 || value.items.length > 20) return null;
  const seen = new Set<string>();
  const seenRuns = new Set<string>();
  for (const [ordinal, item] of value.items.entries()) {
    if (!isRecord(item) || item.ordinal !== ordinal + 1 || typeof item.item_key !== "string"
      || item.item_key.length === 0 || item.item_key.length > 200 || seen.has(item.item_key)
      || typeof item.research_run_id !== "string" || !RUN_ID.test(item.research_run_id)
      || seenRuns.has(item.research_run_id) || typeof item.status !== "string"
      || (!ACTIVE_STATUSES.has(item.status) && !["succeeded", "failed", "cancelled"].includes(item.status))
      || !["available", "deleted"].includes(String(item.run_availability))) return null;
    seen.add(item.item_key);
    seenRuns.add(item.research_run_id);
  }
  return value as BatchDetail;
}

function renderBatch(
  options: LanguageModelV3CallOptions,
  detail: BatchDetail,
  resultRows: readonly string[][],
  surfaceId: string,
  terminal: boolean,
): ScriptedResearchDecision {
  const progress = isRecord(detail.progress) ? detail.progress : undefined;
  const completed = detail.batch_kind === "factor_evaluation" ? progress?.completed_factor_tasks : progress?.completed_strategy_tasks;
  const total = detail.batch_kind === "factor_evaluation" ? progress?.total_factor_tasks : progress?.total_strategy_tasks;
  if (!Number.isSafeInteger(completed) || !Number.isSafeInteger(total)
    || typeof completed !== "number" || typeof total !== "number" || completed < 0 || total < 1 || completed > total) return incomplete();
  const title = detail.batch_kind === "factor_evaluation" ? "Positive versus negative price-rank Alpha" : "Focused versus broad holdings";
  const navigation = detail.items.filter((item) => item.run_availability === "available").map((item) => ({
    component: "Navigation", href: `/research-runs/${item.research_run_id}`,
    id: `child-${item.ordinal}`, label: `Open ${item.item_key} ResearchRun`,
  }));
  const components = [
    { component: "Column", id: "root", gap: "normal", children: ["title", "progress", "comparison", "provenance", ...navigation.map((item) => item.id)] },
    { component: "Text", id: "title", variant: "title", text: title },
    { component: "Text", id: "progress", text: `Batch ${detail.id} · ${detail.status} · ${completed}/${total} completed` },
    {
      component: "Table", id: "comparison", caption: terminal ? "Ordered child ResearchRun results" : "Ordered Batch progress",
      columns: ["Order", "Item", "ResearchRun", "Status", "Result"], initiallyExpanded: true,
      rows: terminal ? resultRows : detail.items.map((item) => [String(item.ordinal), item.item_key, item.research_run_id, item.status, "Not read"]),
      summary: terminal ? "Inspect Batch comparison" : "Inspect Batch progress",
    },
    {
      component: "Provenance", id: "provenance", summary: "Inspect Batch provenance",
      entries: [{ label: "Batch", value: detail.id }, { label: "Research type", value: detail.batch_kind },
        { label: "Result ownership", value: "Each Child ResearchRun owns its own immutable Result; Batch has no aggregate Result." }],
    },
    ...navigation,
  ];
  const projected = projectResearchA2UIContent({ a2ui_operations: [{
    version: RESEARCH_A2UI_PROTOCOL_VERSION,
    createSurface: { catalogId: RESEARCH_A2UI_CATALOG_ID, surfaceId },
  }, { version: RESEARCH_A2UI_PROTOCOL_VERSION, updateComponents: { components, surfaceId } }] });
  return projected.valid && projected.kind === "ready"
    ? requiredTool(options, "render_a2ui", { components, surfaceId, data: {} }) : incomplete();
}

function inspectObservations(
  options: LanguageModelV3CallOptions,
  detail: BatchDetail,
  observations: readonly ToolObservation[],
  afterIndex: number,
): ScriptedResearchDecision {
  const first = detail.items[0];
  if (detail.batch_kind !== "strategy_sweep" || first?.status !== "succeeded" || first.run_availability !== "available") {
    return text("The first Batch child has no successful available Strategy observations to inspect.");
  }
  const child = [...observations].reverse().find((item) => item.name === "get_research_run"
    && item.input.run_id === first.research_run_id);
  if (child === undefined) return requiredTool(options, "get_research_run", { run_id: first.research_run_id });
  if (child.output.id !== first.research_run_id || child.output.status !== "succeeded"
    || !Array.isArray(child.output.available_result_sections)
    || !child.output.available_result_sections.includes("strategy_observations")) return incomplete();
  const pages = observations.filter((item) => item.promptIndex > afterIndex && item.name === "get_research_run_result"
    && item.input.run_id === first.research_run_id && item.input.section === "strategy_observations");
  const last = pages.at(-1);
  if (last === undefined) return requiredTool(options, "get_research_run_result", { run_id: first.research_run_id, section: "strategy_observations", limit: 20 });
  if (pages.some((page) => page.output.run_id !== first.research_run_id || page.output.section !== "strategy_observations"
    || !Array.isArray(page.output.items) || (page.output.next_cursor !== null && typeof page.output.next_cursor !== "string"))) return incomplete();
  const next = last.output.next_cursor;
  if (typeof next === "string" && pages.length < MAX_RESULT_PAGES) {
    if (pages.some((page) => page.input.cursor === next)) return text("The Result repeated a pagination cursor; I stopped without looping or claiming complete observations.");
    return requiredTool(options, "get_research_run_result", { ...last.input, cursor: next });
  }
  const count = pages.reduce((total, page) => total + (page.output.items as unknown[]).length, 0);
  return text(`Read ${count} Strategy observations from ${pages.length} authoritative pages for ${first.research_run_id}. `
    + (next === null ? "The Result cursor confirms this section is complete." : "More pages remain. This inspection reached its bounded page limit and is not a complete series."));
}

function hasSurface(observations: readonly ToolObservation[], surfaceId: string): boolean {
  return observations.some((item) => item.name === "render_a2ui" && item.input.surfaceId === surfaceId);
}

function toolFailureDecision(
  options: LanguageModelV3CallOptions,
  observations: readonly ToolObservation[],
): ScriptedResearchDecision | null {
  const last = observations.at(-1);
  if (typeof last?.output.code !== "string") return null;
  const wait = readRetryAfter(last.output);
  return last.output.code === "TEMPORARILY_UNAVAILABLE" && wait !== undefined
    ? requiredTool(options, last.name, last.input, wait)
    : text(`The Research Tool reported ${last.output.code}. I did not repeat an uncertain effect or claim a Batch result.`);
}

function batchMode(prompt: string): BatchMode | null {
  if (prompt === SCRIPTED_FACTOR_BATCH_PROMPT) return "factor_evaluation";
  return prompt === SCRIPTED_STRATEGY_SWEEP_PROMPT ? "strategy_sweep" : null;
}

function previousBatchIdea(options: LanguageModelV3CallOptions, before: number): Readonly<{ index: number; mode: BatchMode }> | null {
  for (let index = before - 1; index >= 0; index -= 1) {
    const message = options.prompt[index];
    if (message?.role !== "user") continue;
    const mode = batchMode(textContent(message.content));
    if (mode !== null) return { index, mode };
  }
  return null;
}

function text(value: string): ScriptedResearchDecision { return { kind: "text", text: value }; }
function incomplete(): ScriptedResearchDecision {
  return text("The current Batch context or authoritative child Result is incomplete or outside display limits. I stopped without inventing Research facts.");
}
