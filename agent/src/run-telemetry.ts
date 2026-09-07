import type { ModelCallObservation, RunInputEstimate } from "./guarded-language-model.js";
import type { SessionContextSnapshot } from "./session-context-state.js";
import { createHash, randomUUID } from "node:crypto";
import { write } from "node:fs";

import { agentFailure, type AgentFailureCode } from "../../contracts/agent-failure.mjs";
import { isChatThreadId } from "./chat-request.js";
import { isProviderModelId, reasoningEfforts } from "./model-registry.js";
import { frameworkTokenUsage, normalizeTokenUsage, type PersistedTokenUsage } from "./usage-capture.js";

type RunIdentity = Readonly<{
  researcherId: string;
  threadId: string;
  runId: string;
  traceId: string;
  modelKey: string;
  providerModelId: string;
  reasoningEffort: string;
}>;

export type AgentTelemetryEvent = Readonly<{
  component: "agent";
  event: "agent_run_accepted" | "agent_tool_finished" | "agent_run_waiting" | "agent_run_finished" | "agent_model_call_finished" | "agent_recovery_claimed";
  level: "INFO" | "WARN";
  timestamp: string;
  researcher_correlation: string | null;
  thread_id: string | null;
  run_id: string | null;
  trace_id: string | null;
  model_key: string | null;
  provider_model_id: string | null;
  reasoning_effort: string | null;
  token_usage: PersistedTokenUsage | Readonly<{ reported: false }>;
  input_token_estimate: RunInputEstimate | null;
  context_compaction: Readonly<Record<keyof SessionContextSnapshot["statistics"], number | null>> | null;
  model_call: Readonly<{ purpose: "answer" | "memory" | null; finish_reason: ModelCallObservation["finishReason"] | null;
    duration_ms: number | null; input_tokens: number | null; output_allowance: number | null;
    context_window: number | null; desired_output_tokens: number | null; safety_tokens: number | null;
    token_usage: PersistedTokenUsage | Readonly<{ reported: false }> }> | null;
  tool_result_bytes: number | null;
  recovery_attempts: number | null;
  step_count: number | null;
  duration_ms: number | null;
  status: "running" | "waiting_for_user" | "completed" | "stopped" | "failed";
  retry_classification: string;
  error_category: AgentFailureCode | null;
}>;

export type AgentTelemetryWriter = (event: AgentTelemetryEvent) => void;
export type RunTelemetry = ReturnType<typeof createRunTelemetry>;

export function agentTraceId(headers: Headers): string {
  const candidate = headers.get("x-request-id");
  return candidate !== null && isChatThreadId(candidate) ? candidate : randomUUID();
}

/** Observation only: no content, persistent state, replay or execution control. */
export function createRunTelemetry(identity: RunIdentity, options: Readonly<{
  metrics: () => Readonly<{ steps: number; usage: PersistedTokenUsage | undefined; recoveryAttempts?: number; inputEstimate?: RunInputEstimate; compaction?: SessionContextSnapshot["statistics"] }>;
  clock?: () => Date;
  monotonicMilliseconds?: () => number;
  write?: AgentTelemetryWriter;
}>) {
  const clock = options.clock ?? (() => new Date());
  const monotonic = options.monotonicMilliseconds ?? (() => performance.now());
  const write = options.write ?? writeAgentTelemetry;
  const startedAt = monotonic();
  let accepted = false;
  let terminal = false;

  function emit(event: AgentTelemetryEvent["event"], status: AgentTelemetryEvent["status"], failure: AgentFailureCode | null, extra: { call?: ModelCallObservation; toolBytes?: number } = {}) {
    try {
      const metrics = options.metrics();
      const safeFailure = failure === null ? null : agentFailure(failure);
      write({
        component: "agent", event, status,
        level: safeFailure === null ? "INFO" : "WARN",
        timestamp: clock().toISOString(),
        researcher_correlation: isChatThreadId(identity.researcherId)
          ? createHash("sha256").update("thesistrace-researcher\0").update(identity.researcherId).digest("hex") : null,
        thread_id: safeUuid(identity.threadId), run_id: safeUuid(identity.runId), trace_id: safeUuid(identity.traceId),
        model_key: safeIdentifier(identity.modelKey, /^[a-z0-9][a-z0-9._-]{0,63}$/),
        provider_model_id: isProviderModelId(identity.providerModelId) ? identity.providerModelId : null,
        reasoning_effort: reasoningEfforts.some((effort) => effort === identity.reasoningEffort) ? identity.reasoningEffort : null,
        token_usage: safeUsage(metrics.usage), step_count: safeCount(metrics.steps),
        model_call: safeModelCall(extra.call), tool_result_bytes: safeCount(extra.toolBytes),
        recovery_attempts: safeCount(metrics.recoveryAttempts),
        input_token_estimate: safeInputEstimate(metrics.inputEstimate), context_compaction: safeCompaction(metrics.compaction),
        duration_ms: safeCount(Math.max(0, Math.floor(monotonic() - startedAt))),
        retry_classification: safeFailure?.action ?? "none", error_category: safeFailure?.code ?? null,
      });
    } catch {
      // A failed operational sink never fails or retries product work. Do not
      // log the sink's error: it may contain the data this boundary excludes.
    }
  }

  return {
    accepted() {
      if (accepted || terminal) return;
      accepted = true;
      emit("agent_run_accepted", "running", null);
    },
    resumed() {
      if (accepted || terminal) return;
      accepted = true;
    },
    toolFinished(failure: AgentFailureCode | null, bytes?: number) {
      if (accepted && !terminal) emit("agent_tool_finished", failure === null ? "completed" : "failed", failure, { toolBytes: bytes });
    },
    modelCallFinished(call: ModelCallObservation) {
      if (accepted && !terminal) emit("agent_model_call_finished", "running", null, { call });
    },
    recoveryClaimed() {
      if (accepted && !terminal) emit("agent_recovery_claimed", "running", null);
    },
    finished(failure: AgentFailureCode | null) {
      if (!accepted || terminal) return;
      terminal = true;
      emit("agent_run_finished", failure === null ? "completed" : "failed", failure);
    },
    stopped() {
      if (!accepted || terminal) return;
      terminal = true;
      emit("agent_run_finished", "stopped", null);
    },
    waiting() {
      if (!accepted || terminal) return;
      terminal = true;
      emit("agent_run_waiting", "waiting_for_user", null);
    },
  };
}

function safeUuid(value: string): string | null {
  return isChatThreadId(value) ? value : null;
}
function safeIdentifier(value: string, pattern: RegExp): string | null {
  return typeof value === "string" && value.length <= 200 && pattern.test(value) ? value : null;
}
function safeCount(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
}
function safeUsage(usage: PersistedTokenUsage | undefined): AgentTelemetryEvent["token_usage"] {
  if (usage === undefined || usage.reported !== true) return { reported: false };
  try { return normalizeTokenUsage(frameworkTokenUsage(usage)); } catch { return { reported: false }; }
}
function writeAgentTelemetry(event: AgentTelemetryEvent): void {
  // fs.write reports pipe/descriptor failures through this callback instead
  // of emitting an unhandled error on the process-wide stderr stream.
  write(2, `${JSON.stringify(event)}\n`, () => undefined);
}

function safeInputEstimate(value: RunInputEstimate | undefined): RunInputEstimate | null {
  if (!value || safeCount(value.estimatedTokens) === null) return null;
  const actualTokens = safeCount(value.actualTokens);
  return { estimatedTokens: value.estimatedTokens, actualTokens,
    errorTokens: actualTokens === null ? null : actualTokens - value.estimatedTokens };
}

function safeCompaction(value: SessionContextSnapshot["statistics"] | undefined): AgentTelemetryEvent["context_compaction"] {
  if (!value) return null;
  return { inputTokensBefore: safeCount(value.inputTokensBefore), inputTokensAfter: safeCount(value.inputTokensAfter),
    outputTokensAfter: safeCount(value.outputTokensAfter), elapsedMs: safeCount(Math.floor(value.elapsedMs)),
    auxiliaryInputTokens: safeCount(value.auxiliaryInputTokens), auxiliaryOutputTokens: safeCount(value.auxiliaryOutputTokens) };
}

function safeModelCall(call: ModelCallObservation | undefined): AgentTelemetryEvent["model_call"] {
  if (!call) return null;
  const reasons: readonly string[] = ["stop", "tool-calls", "length", "content-filter", "error", "other", "cancelled"];
  return { purpose: call.purpose === "answer" || call.purpose === "memory" ? call.purpose : null,
    finish_reason: reasons.includes(call.finishReason) ? call.finishReason : null,
    duration_ms: safeCount(call.durationMs), input_tokens: safeCount(call.budget.inputTokens),
    output_allowance: safeCount(call.budget.outputTokens), context_window: safeCount(call.budget.contextWindow),
    desired_output_tokens: safeCount(call.budget.desiredOutputTokens), safety_tokens: safeCount(call.budget.safetyTokens),
    token_usage: safeUsage(call.usage) };
}
