import { z } from "zod";

import { isAgentFailureCode, type AgentFailureCode } from "../../contracts/agent-failure.mjs";
import { isProviderModelId, reasoningEfforts } from "./model-registry.js";
import { RESEARCH_A2UI_TOOL_NAME } from "./research-a2ui-tool.js";

const identifier = z.string().regex(/^[a-z0-9][a-z0-9._-]{0,63}$/);
const toolName = z.string().regex(/^[a-z][a-z0-9_]{0,127}$/);
const date = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const count = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
const rate = z.number().min(0).max(1);
const dollars = z.number().finite().nonnegative();
const outcomes = z.enum(["factor", "clarified-factor", "repaired-factor", "admission-repaired-factor", "strategy", "batch", "track-started", "track-refreshed", "track-recovered", "polled-factor", "explained-result"]);
const corpusSchema = z.object({
  version: identifier,
  dataset: identifier,
  clock_window: z.object({ start: date, end: date, head: date }).strict(),
  admission_window: z.object({ requested_start: date, corrected_start: date }).strict(),
  cases: z.array(z.object({
    id: identifier,
    fixture: z.enum(["empty", "strategy", "factor", "active-track", "blocked-track", "paused-research"]),
    outcome: outcomes,
    messages: z.array(z.string().min(1).max(16 * 1024)).min(1).max(2),
    required_tools: z.array(toolName).min(1).max(32),
    forbidden_tools: z.array(toolName).min(1).max(32),
    max_cost_usd: dollars.positive().max(10),
    max_duration_ms: count.min(1000).max(600000),
  }).strict()).min(1).max(100),
}).strict();
const pricingSchema = z.object({
  basis: z.literal("published-standard-upper-bound"),
  input_usd_per_million: dollars,
  cached_input_usd_per_million: dollars,
  output_usd_per_million: dollars,
  source: z.string().url(), checked_on: date, tier: z.literal("standard"),
}).strict();
const thresholdsSchema = z.object({
  min_task_success_rate: rate,
  min_case_success_rate: rate,
  max_tool_error_rate: rate,
  max_p95_duration_ms: count.positive(),
  max_case_cost_usd: dollars.positive(),
  max_repetition_success_variance: rate,
  min_admission_correction_rate: rate,
}).strict();
const candidatesSchema = z.object({
  baseline_repetitions: z.literal(1),
  qualification_repetitions: z.literal(3),
  candidates: z.array(z.object({
    key: identifier,
    display_name: z.string().min(1).max(80),
    provider_adapter: z.enum(["openai", "anthropic", "google"]),
    provider_model_id: z.string().refine(isProviderModelId),
    reasoning_efforts: z.array(z.enum(reasoningEfforts)).min(1).max(reasoningEfforts.length),
    provider_max_input_tokens: count.min(8192).max(2000000),
    pricing: pricingSchema, thresholds: thresholdsSchema,
  }).strict()).min(1).max(16),
}).strict();

export type ResearchEvalCorpus = z.infer<typeof corpusSchema>;
export type ResearchEvalCase = ResearchEvalCorpus["cases"][number];
export type ResearchEvalCandidates = z.infer<typeof candidatesSchema>;
export type ResearchEvalCandidate = ResearchEvalCandidates["candidates"][number];
export type ResearchEvalPricing = z.infer<typeof pricingSchema>;
export type ResearchEvalFailureSource = "model-quality" | "provider" | "mcp" | "core-admission" | "dataset-worker" | "eval-infrastructure";

export class ResearchEvalError extends Error {
  constructor(readonly category: "CONFIG_INVALID" | "CORPUS_INVALID" | "REPORT_INVALID" | "PROTOCOL_INVALID" | "DEPENDENCY_UNAVAILABLE" | "BUDGET_EXHAUSTED") {
    super(`RESEARCH_EVAL_${category}`);
  }
}

export function parseResearchEvalCorpus(value: unknown): ResearchEvalCorpus {
  const parsed = corpusSchema.safeParse(value);
  if (!parsed.success) throw new ResearchEvalError("CORPUS_INVALID");
  const corpus = parsed.data;
  if (new Set(corpus.cases.map((item) => item.id)).size !== corpus.cases.length
    || new Set(corpus.cases.map((item) => item.outcome)).size !== outcomes.options.length
    || corpus.clock_window.start > corpus.clock_window.end || corpus.clock_window.end > corpus.clock_window.head
    || corpus.admission_window.requested_start >= corpus.admission_window.corrected_start
    || corpus.admission_window.corrected_start > corpus.clock_window.start
    || corpus.cases.some((item) => item.required_tools.some((tool) => item.forbidden_tools.includes(tool))
      || new Set(item.required_tools).size !== item.required_tools.length
      || new Set(item.forbidden_tools).size !== item.forbidden_tools.length
      || (item.outcome === "clarified-factor") !== (item.messages.length === 2))) {
    throw new ResearchEvalError("CORPUS_INVALID");
  }
  return corpus;
}

export function parseResearchEvalCandidates(value: unknown): ResearchEvalCandidates {
  const parsed = candidatesSchema.safeParse(value);
  if (!parsed.success || new Set(parsed.data.candidates.map((item) => item.key)).size !== parsed.data.candidates.length
    || parsed.data.candidates.some((item) => new Set(item.reasoning_efforts).size !== item.reasoning_efforts.length
      || item.pricing.cached_input_usd_per_million > item.pricing.input_usd_per_million)) {
    throw new ResearchEvalError("CONFIG_INVALID");
  }
  return parsed.data;
}

export function researchEvalRepetitions(
  candidates: ResearchEvalCandidates,
  phase: "baseline" | "qualification",
): number {
  return phase === "baseline"
    ? candidates.baseline_repetitions
    : candidates.qualification_repetitions;
}

export function evalStartupRegistry(candidate: ResearchEvalCandidate, effort: string) {
  if (!candidate.reasoning_efforts.some((value) => value === effort)) throw new ResearchEvalError("CONFIG_INVALID");
  return { default_model_key: candidate.key, models: [{
    key: candidate.key, display_name: candidate.display_name, provider_adapter: candidate.provider_adapter,
    provider_model_id: candidate.provider_model_id, reasoning_efforts: [effort], default_reasoning_effort: effort,
    secret_env: `THESISTRACE_AGENT_${candidate.provider_adapter.toUpperCase()}_API_KEY`, enabled: true,
  }] };
}

const tokenCounters = z.object({ total: count.nullable(), cacheRead: count.nullable(), cacheWrite: count.nullable(), noCache: count.nullable() }).strict();
const outputCounters = z.object({ total: count.nullable(), text: count.nullable(), reasoning: count.nullable() }).strict();
const usageSchema = z.union([
  z.object({ reported: z.literal(false) }).strict(),
  z.object({ reported: z.literal(true), inputTokens: tokenCounters, outputTokens: outputCounters }).strict(),
]);
export type EvalUsage = z.infer<typeof usageSchema>;

export function usageCostUsd(usage: EvalUsage, pricing: ResearchEvalPricing): number | null {
  if (!usage.reported || usage.inputTokens.total === null || usage.outputTokens.total === null) return null;
  // The profile's input ceiling also covers cache writes and long context.
  // Unknown cache breakdown is conservatively priced at that upper-bound rate;
  // missing TOTAL usage stays unknown. Never manufacture zero paid usage.
  const cached = usage.inputTokens.cacheRead ?? 0;
  if (cached > usage.inputTokens.total) throw new ResearchEvalError("REPORT_INVALID");
  return ((usage.inputTokens.total - cached) * pricing.input_usd_per_million
    + cached * pricing.cached_input_usd_per_million
    + usage.outputTokens.total * pricing.output_usd_per_million) / 1_000_000;
}

/** Without a call-count bound, no finite full-Turn spend reserve is known. */
export function maximumEvalTurnCostUsd(_candidate: ResearchEvalCandidate): number {
  return Number.POSITIVE_INFINITY;
}
export function maximumTitleCostUsd(candidate: ResearchEvalCandidate): number {
  // One separate first-message title invocation; use the provider's full
  // input ceiling as a conservative spend reserve, including its instructions.
  return (candidate.provider_max_input_tokens * candidate.pricing.input_usd_per_million
    + 32 * candidate.pricing.output_usd_per_million) / 1_000_000;
}

export function readResearchEvalControls(candidate: ResearchEvalCandidate, phase: string | undefined, encodedBudget: string | undefined) {
  const budget = Number(encodedBudget);
  if ((phase !== "baseline" && phase !== "qualification") || encodedBudget === undefined
    || !/^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(encodedBudget)
    || !Number.isFinite(budget) || budget < 2 * maximumEvalTurnCostUsd(candidate) || budget > 100) {
    throw new ResearchEvalError("CONFIG_INVALID");
  }
  return { phase, budget };
}

export function evalFailureSource(code: AgentFailureCode | null, evidence?: {
  workerFailure: boolean; transportFailed: boolean; usageComplete: boolean;
}): ResearchEvalFailureSource {
  if (code?.startsWith("PROVIDER_")) return "provider";
  if (code === "MCP_AUTHENTICATION" || code === "MCP_TRANSIENT") return "mcp";
  if (code === "TOOL_REJECTION") return "core-admission";
  // Generic tool failure alone does not prove a Dataset/Worker failure.
  // That source requires independently observed failed Core artifacts.
  if (code === "TOOL_ERROR") return "mcp";
  if (code === "AGENT_LIMIT") return "model-quality";
  if (code !== null) return "eval-infrastructure";
  // A failed fixture may predate this Turn. Attribute it only when no
  // explicit Agent terminal failure already explains the observed failure.
  if (evidence?.workerFailure) return "dataset-worker";
  if (code === null && !evidence?.transportFailed && evidence?.usageComplete !== false) return "model-quality";
  return "eval-infrastructure";
}

export function evalBatchWorkerFailure(status: string): boolean {
  return status === "failed" || status === "completed_with_failures";
}

export function evalToolCapabilities(names: readonly string[], mcpInventory: readonly string[], forbidden: readonly string[]) {
  const allowed = new Set([...mcpInventory, RESEARCH_A2UI_TOOL_NAME]);
  return {
    invalid: names.filter((name) => !allowed.has(name)).length,
    forbidden: names.filter((name) => forbidden.includes(name) || /^(?:cancel_|stop_|refresh_)/.test(name)).length,
  };
}

export const evalRunSchema = z.object({
  run_id: z.string().uuid(), thread_id: z.string().uuid(),
  status: z.enum(["completed", "failed"]),
  error_category: z.custom<AgentFailureCode>(isAgentFailureCode).nullable(),
  step_count: count, duration_ms: count, token_usage: usageSchema,
}).strict();
const checksSchema = z.object({
  artifact: z.boolean(), required_tools: z.boolean(), forbidden_tools: z.boolean(),
  ownership: z.boolean(), conversation: z.boolean(), terminal: z.boolean(),
  within_time: z.boolean(), within_cost: z.boolean(), usage_complete: z.boolean(),
}).strict();
const observationSchema = z.object({
  case_id: identifier, repetition: count.min(1).max(10),
  succeeded: z.boolean(), checks: checksSchema,
  failure_source: z.enum(["model-quality", "provider", "mcp", "core-admission", "dataset-worker", "eval-infrastructure"]).nullable(),
  duration_ms: count, estimated_cost_usd: dollars.nullable(),
  title_cost_upper_bound_usd: dollars, runs: z.array(evalRunSchema).max(2),
  tool_calls: count, invalid_tool_calls: count, forbidden_tool_calls: count, tool_errors: count, tool_retries: count,
  admission_correction: z.boolean().nullable(),
  artifact_ids: z.array(z.string().regex(/^(?:run|batch|track)_[a-f0-9]{20}$/)).max(8),
}).strict();
export type ResearchEvalObservation = z.infer<typeof observationSchema>;

export function validateEvalObservation(value: unknown): ResearchEvalObservation {
  const parsed = observationSchema.safeParse(value);
  if (!parsed.success) throw new ResearchEvalError("REPORT_INVALID");
  const result = parsed.data;
  if (result.succeeded !== Object.values(result.checks).every(Boolean)
    || result.succeeded !== (result.failure_source === null)
    || result.runs.some((run) => (run.status === "completed") !== (run.error_category === null))
    || (result.checks.terminal && (result.runs.length === 0 || result.runs.some((run) => run.status !== "completed")))
    || (result.checks.usage_complete && (result.runs.length === 0 || result.estimated_cost_usd === null
      || result.runs.some((run) => !run.token_usage.reported
        || run.token_usage.inputTokens.total === null || run.token_usage.outputTokens.total === null)))
    || result.invalid_tool_calls > result.tool_calls || result.forbidden_tool_calls > result.tool_calls
    || result.tool_errors > result.tool_calls || result.tool_retries > result.tool_calls) {
    throw new ResearchEvalError("REPORT_INVALID");
  }
  return result;
}

export function summarizeResearchEval(corpus: ResearchEvalCorpus, repetitions: number, observations: readonly ResearchEvalObservation[]) {
  const valid = observations.map(validateEvalObservation);
  const identities = valid.map((item) => `${item.case_id}:${item.repetition}`);
  if (valid.length === 0 || new Set(identities).size !== identities.length
    || valid.some((item) => {
      const testCase = corpus.cases.find((value) => value.id === item.case_id);
      return item.repetition > repetitions || testCase === undefined
        || (testCase.outcome === "admission-repaired-factor") !== (item.admission_correction !== null)
        || (item.checks.terminal && item.runs.length !== testCase.messages.length);
    })) {
    throw new ResearchEvalError("REPORT_INVALID");
  }
  const complete = valid.length === corpus.cases.length * repetitions;
  const runs = valid.flatMap((item) => item.runs);
  const usageComplete = valid.every((item) => item.checks.usage_complete && item.estimated_cost_usd !== null);
  const reported = runs.flatMap((item) => item.token_usage.reported ? [item.token_usage] : []);
  const durations = valid.map((item) => item.duration_ms).sort((a, b) => a - b);
  const tools = sum(valid.map((item) => item.tool_calls));
  const ratio = (values: number[]) => tools === 0 ? null : sum(values) / tools;
  const caseRates = corpus.cases.map((testCase) => ({
    case_id: testCase.id,
    attempts: valid.filter((item) => item.case_id === testCase.id).length,
    success_rate: valid.filter((item) => item.case_id === testCase.id && item.succeeded).length / repetitions,
  }));
  const repetitionRates = Array.from({ length: repetitions }, (_, index) => (
    valid.filter((item) => item.repetition === index + 1 && item.succeeded).length / corpus.cases.length
  ));
  const repairs = valid.filter((item) => item.admission_correction !== null);
  const successRate = valid.filter((item) => item.succeeded).length / (corpus.cases.length * repetitions);
  return {
    complete, expected_cases: corpus.cases.length * repetitions, observed_cases: valid.length,
    task_success_rate: successRate,
    minimum_case_success_rate: Math.min(...caseRates.map((item) => item.success_rate)),
    ownership_failures: valid.filter((item) => !item.checks.ownership).length,
    invalid_tool_rate: ratio(valid.map((item) => item.invalid_tool_calls)),
    forbidden_tool_rate: ratio(valid.map((item) => item.forbidden_tool_calls)),
    tool_error_rate: ratio(valid.map((item) => item.tool_errors)),
    tool_retry_rate: ratio(valid.map((item) => item.tool_retries)),
    admission_correction_success_rate: repairs.length === 0 ? null : repairs.filter((item) => item.admission_correction).length / repairs.length,
    usage_complete: usageComplete,
    input_tokens: usageComplete ? sum(reported.map((item) => item.inputTokens.total ?? 0)) : null,
    output_tokens: usageComplete ? sum(reported.map((item) => item.outputTokens.total ?? 0)) : null,
    reasoning_tokens: !usageComplete || reported.some((item) => item.outputTokens.reasoning === null) ? null : sum(reported.map((item) => item.outputTokens.reasoning ?? 0)),
    estimated_primary_cost_usd: usageComplete ? sum(valid.map((item) => item.estimated_cost_usd ?? 0)) : null,
    title_cost_upper_bound_usd: sum(valid.map((item) => item.title_cost_upper_bound_usd)),
    maximum_case_cost_usd: usageComplete ? Math.max(...valid.map((item) => (item.estimated_cost_usd ?? 0) + item.title_cost_upper_bound_usd)) : null,
    duration_p50_ms: percentile(durations, 0.5), duration_p95_ms: percentile(durations, 0.95),
    duration_stddev_ms: Math.sqrt(variance(durations)),
    total_agent_steps: sum(runs.map((item) => item.step_count)),
    maximum_run_steps: Math.max(0, ...runs.map((item) => item.step_count)),
    maximum_run_duration_ms: Math.max(0, ...runs.map((item) => item.duration_ms)),
    repetition_success_variance: variance(repetitionRates), case_rates: caseRates, repetition_success_rates: repetitionRates,
    failures: Object.fromEntries((["model-quality", "provider", "mcp", "core-admission", "dataset-worker", "eval-infrastructure"] as const)
      .map((source) => [source, valid.filter((item) => item.failure_source === source).length])),
  };
}

export function researchEvalPasses(summary: ReturnType<typeof summarizeResearchEval>, candidate: ResearchEvalCandidate): boolean {
  const t = candidate.thresholds;
  return summary.complete && summary.usage_complete
    && summary.ownership_failures === 0
    && summary.task_success_rate >= t.min_task_success_rate && summary.minimum_case_success_rate >= t.min_case_success_rate
    && summary.invalid_tool_rate === 0 && summary.forbidden_tool_rate === 0
    && summary.tool_error_rate !== null && summary.tool_error_rate <= t.max_tool_error_rate
    && summary.duration_p95_ms <= t.max_p95_duration_ms
    && summary.maximum_case_cost_usd !== null && summary.maximum_case_cost_usd <= t.max_case_cost_usd
    && summary.repetition_success_variance <= t.max_repetition_success_variance
    && summary.admission_correction_success_rate !== null && summary.admission_correction_success_rate >= t.min_admission_correction_rate;
}

const sum = (values: readonly number[]) => values.reduce((total, value) => total + value, 0);
function percentile(sorted: readonly number[], proportion: number): number { return sorted[Math.max(0, Math.ceil(sorted.length * proportion) - 1)] ?? 0; }
function variance(values: readonly number[]): number { const mean = sum(values) / values.length; return sum(values.map((value) => (value - mean) ** 2)) / values.length; }
