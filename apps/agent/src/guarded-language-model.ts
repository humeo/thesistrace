import type { LanguageModelV3, LanguageModelV3CallOptions, LanguageModelV3GenerateResult, LanguageModelV3StreamPart } from "@ai-sdk/provider";

import { recoveryImprovesBudget } from "./model-step-recovery.js";

import type { AgentFailureCode } from "@thesistrace/contracts/agent-failure";
import { AgentRunFailure, providerFailureCode } from "./run-failure.js";
import { frameworkTokenUsage, normalizeTokenUsage, RunUsageCapture, type PersistedTokenUsage } from "./usage-capture.js";
import { ModelInputTokenCounter, modelRequestBudget, type ModelCapacity, type ModelRequestBudget } from "./model-context.js";

export class ModelRequestFailure extends AgentRunFailure {
  constructor(readonly code: "CONTEXT_TOO_LARGE" | "OUTPUT_LIMIT", readonly budget: ModelRequestBudget) {
    super(code);
  }
}

export const AGENT_LIMITS = Object.freeze({
  toolResultBytes: 512 * 1024,
  providerCallMs: 180_000,
});

export type RunInputEstimate = Readonly<{ estimatedTokens: number; actualTokens: number | null; errorTokens: number | null }>;

export type ModelCallObservation = Readonly<{
  purpose: "answer" | "memory";
  finishReason: "stop" | "tool-calls" | "length" | "content-filter" | "error" | "other" | "cancelled";
  budget: ModelRequestBudget;
  usage: PersistedTokenUsage | undefined;
  durationMs: number;
}>;

/** Safe, request-local observations; not a planner or a second run lifecycle. */
export class RunModelObservation {
  failure: AgentFailureCode | undefined;
  steps = 0;
  recoveryAttempts = 0;
  onCallFinished: ((call: ModelCallObservation) => void) | undefined;
  private activeCall: { purpose: "answer" | "memory"; budget: ModelRequestBudget; startedAt: number } | undefined;
  inputEstimate: RunInputEstimate | undefined;
  private readonly tokenCounter = new ModelInputTokenCounter();
  private generatedBytes = 0;
  private hasRunAnswer = false;
  private budget: ModelRequestBudget | undefined;
  private requestFailure: ModelRequestFailure | undefined;

  constructor(
    readonly usage: RunUsageCapture,
    initial: Readonly<{ generatedBytes?: number; steps?: number }> = {},
  ) {
    this.generatedBytes = initial.generatedBytes ?? 0;
    this.steps = initial.steps ?? 0;
  }

  get pendingRequestFailure(): ModelRequestFailure | undefined { return this.requestFailure; }

  terminateRequestFailure(code: AgentFailureCode): AgentRunFailure {
    this.failure = code;
    return new AgentRunFailure(code);
  }

  get outputBytes(): number {
    return this.generatedBytes;
  }

  fail(code: AgentFailureCode): AgentRunFailure {
    this.completeCall(undefined, "error");
    if ((code === "CONTEXT_TOO_LARGE" || code === "OUTPUT_LIMIT") && this.budget !== undefined) {
      this.requestFailure ??= new ModelRequestFailure(code, this.budget);
      return this.requestFailure;
    }
    this.failure ??= code;
    return new AgentRunFailure(this.failure);
  }

  begin(options: LanguageModelV3CallOptions, model: ModelCapacity, purpose: "answer" | "memory" = "answer"): LanguageModelV3CallOptions {
    if (this.failure !== undefined) throw new AgentRunFailure(this.failure);
    if (purpose === "answer" && this.requestFailure !== undefined) throw this.requestFailure;
    this.budget = modelRequestBudget(options, model, this.tokenCounter);
    const maxOutputTokens = this.budget.outputTokens;
    if (!Number.isSafeInteger(maxOutputTokens) || maxOutputTokens <= 0) throw this.fail(purpose === "memory" ? "CONTEXT_COMPACTION_FAILED" : "CONTEXT_TOO_LARGE");
    this.steps++;
    this.activeCall = { purpose, budget: this.budget, startedAt: performance.now() };
    this.usage.beginStep();
    return { ...options, maxOutputTokens };
  }

  output(text: string): void {
    this.generatedBytes += Buffer.byteLength(text, "utf8");
  }

  finish(part: Extract<LanguageModelV3StreamPart, { type: "finish" }>, hasStepAnswer: boolean, purpose: "answer" | "memory" = "answer"): void {
    this.usage.capture(part.usage);
    if (this.budget) {
      const reported = part.usage?.inputTokens?.total;
      const actualTokens = typeof reported === "number" && Number.isSafeInteger(reported) && reported >= 0 ? reported : null;
      this.inputEstimate = { estimatedTokens: this.budget.inputTokens, actualTokens,
        errorTokens: actualTokens === null ? null : actualTokens - this.budget.inputTokens };
    }
    const reason = part.finishReason?.unified;
    let usage: PersistedTokenUsage | undefined;
    try { usage = normalizeTokenUsage(part.usage); } catch { /* Unknown usage remains unknown. */ }
    this.completeCall(usage, reason === "stop" || reason === "tool-calls" || reason === "length"
      || reason === "content-filter" || reason === "error" ? reason : "other");
    if (reason === "length") throw this.fail(purpose === "memory" ? "CONTEXT_COMPACTION_FAILED" : "OUTPUT_LIMIT");
    if (reason === "content-filter") throw this.fail("PROVIDER_REFUSAL");
    if (reason !== "stop" && reason !== "tool-calls") throw this.fail("PROVIDER_MALFORMED_STREAM");
    // A tool (including render_a2ui) can already be the answer. Mastra may
    // then receive an empty stop; requiring new prose on every model step
    // incorrectly turns a valid multi-step completion into a protocol error.
    // A wholly empty Run or an empty tool-calls step still fails closed.
    if (!hasStepAnswer && !(purpose === "answer" && reason === "stop" && this.hasRunAnswer)) {
      throw this.fail("PROVIDER_MALFORMED_STREAM");
    }
    if (purpose === "answer") this.hasRunAnswer ||= hasStepAnswer;
  }

  /** Called only after the runtime has claimed and committed a valid recovery. */
  acknowledgeRecovery(failure: ModelRequestFailure, replacement: ModelRequestBudget): void {
    if (this.failure !== undefined || this.requestFailure !== failure
      || !recoveryImprovesBudget(failure.code, failure.budget, replacement)) {
      throw new AgentRunFailure("CONTEXT_COMPACTION_FAILED");
    }
    this.requestFailure = undefined;
  }

  cancelCall(): void { this.completeCall(undefined, "cancelled"); }

  private completeCall(usage: PersistedTokenUsage | undefined, finishReason: ModelCallObservation["finishReason"]): void {
    const call = this.activeCall;
    this.activeCall = undefined;
    if (!call) return;
    try {
      this.onCallFinished?.({ purpose: call.purpose, budget: call.budget, usage, finishReason,
        durationMs: Math.max(0, Math.floor(performance.now() - call.startedAt)) });
    } catch { /* Observation cannot fail or retry model work. */ }
  }

  terminalFailure(): AgentFailureCode | undefined {
    return this.failure ?? this.requestFailure?.code;
  }
}

/** Single provider boundary: bound input/output, capture usage, erase raw errors. */
export class GuardedLanguageModel implements LanguageModelV3 {
  readonly specificationVersion = "v3" as const;
  constructor(
    private readonly delegate: LanguageModelV3,
    private readonly observation: RunModelObservation,
    private readonly model: ModelCapacity,
    private readonly purpose: "answer" | "memory" = "answer",
  ) {}
  get modelId() { return this.delegate.modelId; }
  get provider() { return this.delegate.provider; }
  get supportedUrls() { return this.delegate.supportedUrls; }

  async doGenerate(options: LanguageModelV3CallOptions): Promise<LanguageModelV3GenerateResult> {
    try {
      const result = await this.delegate.doGenerate(this.observation.begin(options, this.model, this.purpose));
      this.observation.output(JSON.stringify(result.content));
      this.observation.finish({ type: "finish", finishReason: result.finishReason, usage: result.usage },
        result.content.some((part) => part.type === "tool-call" || (part.type === "text" && part.text.trim().length > 0)), this.purpose);
      return { ...result, usage: frameworkTokenUsage(result.usage) };
    } catch (error) { throw this.failure(error, options.abortSignal); }
  }

  async doStream(options: LanguageModelV3CallOptions) {
    let result: Awaited<ReturnType<LanguageModelV3["doStream"]>>;
    try {
      result = await this.delegate.doStream(this.observation.begin(options, this.model, this.purpose));
    } catch (error) { throw this.failure(error, options.abortSignal); }
    const reader = result.stream.getReader();
    const observation = this.observation;
    const purpose = this.purpose;
    const failure = (error: unknown) => this.failure(error, options.abortSignal);
    let finished = false;
    let hasAnswer = false;
    // Mastra can execute collected calls even after a later stream error.
    // Mastra can reconstruct a complete invocation from argument deltas on
    // an error path. Hold the entire tool-input sequence, not only tool-call,
    // until this model response has a validated completion reason.
    const pendingToolParts: LanguageModelV3StreamPart[] = [];
    return { ...result, stream: new ReadableStream<LanguageModelV3StreamPart>({
      async pull(controller) {
        try {
          for (;;) {
            const next = await reader.read();
            if (next.done) {
              if (!finished) throw new AgentRunFailure("PROVIDER_MALFORMED_STREAM");
              controller.close();
              return;
            }
            const part = next.value;
            if (finished || part === null || typeof part !== "object" || !PROVIDER_PART_TYPES.has(part.type)) {
              throw new AgentRunFailure("PROVIDER_MALFORMED_STREAM");
            }
            if (part.type === "error") throw failure(part.error);
            if (part.type === "text-delta" || part.type === "reasoning-delta" || part.type === "tool-input-delta") {
              if (typeof part.delta !== "string") throw new AgentRunFailure("PROVIDER_MALFORMED_STREAM");
              observation.output(part.delta);
              if (part.type === "text-delta" && part.delta.trim().length > 0) hasAnswer = true;
            }
            if (part.type === "tool-call") {
              if (typeof part.input !== "string") throw new AgentRunFailure("PROVIDER_MALFORMED_STREAM");
              observation.output(part.input);
              hasAnswer = true;
              pendingToolParts.push(part);
              continue;
            }
            if (part.type !== "text-delta" && part.type !== "reasoning-delta" && part.type !== "tool-input-delta") {
              observation.output(JSON.stringify(part));
            }
            if (part.type === "tool-input-start" || part.type === "tool-input-delta" || part.type === "tool-input-end") {
              pendingToolParts.push(part);
              continue;
            }
            if (part.type === "finish") {
              observation.finish(part, hasAnswer, purpose);
              finished = true;
              for (const call of pendingToolParts) controller.enqueue(call);
              pendingToolParts.length = 0;
            }
            controller.enqueue(part.type === "finish" ? { ...part, usage: frameworkTokenUsage(part.usage) } : part);
            return;
          }
        } catch (error) {
          void reader.cancel().catch(() => undefined);
          // A stream error discards queued prose in downstream transforms.
          // Preserve ordering with the Provider error event before closing.
          controller.enqueue({ type: "error", error: failure(error) });
          controller.close();
        }
      },
      cancel: (reason) => { observation.cancelCall(); return reader.cancel(reason); },
    }) };
  }

  private failure(error: unknown, signal?: AbortSignal): AgentRunFailure {
    return this.observation.fail(providerFailureCode(signal?.aborted ? signal.reason : error));
  }
}

const PROVIDER_PART_TYPES = new Set([
  "stream-start", "response-metadata", "text-start", "text-delta", "text-end",
  "reasoning-start", "reasoning-delta", "reasoning-end", "tool-input-start",
  "tool-input-delta", "tool-input-end", "tool-call", "tool-result", "tool-approval-request",
  "file", "source", "raw", "finish", "error",
]);
