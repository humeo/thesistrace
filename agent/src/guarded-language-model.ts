import type { LanguageModelV3, LanguageModelV3CallOptions, LanguageModelV3GenerateResult, LanguageModelV3StreamPart, SharedV3ProviderOptions } from "@ai-sdk/provider";
import { estimateTokenCount } from "tokenx";

import type { AgentFailureCode } from "../../contracts/agent-failure.mjs";
import { AgentRunFailure, providerFailureCode } from "./run-failure.js";
import { frameworkTokenUsage, RunUsageCapture } from "./usage-capture.js";

export const AGENT_LIMITS = Object.freeze({
  contextTokens: 65_536,
  outputTokens: 8_192,
  outputBytes: 256 * 1024,
  toolResultBytes: 512 * 1024,
  steps: 16,
  providerCallMs: 180_000,
});

/** Safe, request-local observations; not a planner or a second run lifecycle. */
export class RunModelObservation {
  failure: AgentFailureCode | undefined;
  steps = 0;
  lastFinishReason: string | undefined;
  private generatedBytes = 0;
  private hasRunAnswer = false;

  constructor(
    readonly usage: RunUsageCapture,
    initial: Readonly<{ generatedBytes?: number; steps?: number }> = {},
  ) {
    this.generatedBytes = initial.generatedBytes ?? 0;
    this.steps = initial.steps ?? 0;
  }

  get outputBytes(): number {
    return this.generatedBytes;
  }

  fail(code: AgentFailureCode): AgentRunFailure {
    this.failure ??= code;
    return new AgentRunFailure(this.failure);
  }

  begin(options: LanguageModelV3CallOptions): LanguageModelV3CallOptions {
    if (this.failure !== undefined) throw new AgentRunFailure(this.failure);
    // Use Mastra's own tokenizer dependency against the complete provider
    // context, including system instructions and the discovered Tool schemas.
    // Memory selection remains Mastra-owned; we never silently trim it here.
    // Mastra retains toModelOutput in internal provider options on both the
    // call and result. Provider adapters ignore that namespace; counting it
    // would charge the same result three times. Exclude only protocol-level
    // metadata, never identically named fields inside Tool input or output.
    const context = JSON.stringify({
      prompt: options.prompt.map((message) => ({
        ...message,
        providerOptions: countableProviderOptions(message.providerOptions),
        content: typeof message.content === "string" ? message.content : message.content.map((part) => ({
          ...part, providerOptions: countableProviderOptions(part.providerOptions),
        })),
      })),
      tools: options.tools,
    });
    if (estimateTokenCount(context) > AGENT_LIMITS.contextTokens || this.steps >= AGENT_LIMITS.steps) {
      throw this.fail("AGENT_LIMIT");
    }
    this.steps++;
    this.usage.beginStep();
    return { ...options, maxOutputTokens: Math.min(options.maxOutputTokens ?? AGENT_LIMITS.outputTokens, AGENT_LIMITS.outputTokens) };
  }

  output(text: string): void {
    this.generatedBytes += Buffer.byteLength(text, "utf8");
    if (this.generatedBytes > AGENT_LIMITS.outputBytes) throw this.fail("AGENT_LIMIT");
  }

  finish(part: Extract<LanguageModelV3StreamPart, { type: "finish" }>, hasStepAnswer: boolean): void {
    this.usage.capture(part.usage);
    const reason = part.finishReason?.unified;
    this.lastFinishReason = reason;
    const outputTokens = frameworkTokenUsage(part.usage).outputTokens.total;
    if (reason === "length" || (outputTokens !== undefined && outputTokens > AGENT_LIMITS.outputTokens)) {
      throw this.fail("AGENT_LIMIT");
    }
    if (reason === "content-filter") throw this.fail("PROVIDER_REFUSAL");
    if (reason !== "stop" && reason !== "tool-calls") throw this.fail("PROVIDER_MALFORMED_STREAM");
    // A tool (including render_a2ui) can already be the answer. Mastra may
    // then receive an empty stop; requiring new prose on every model step
    // incorrectly turns a valid multi-step completion into a protocol error.
    // A wholly empty Run or an empty tool-calls step still fails closed.
    if (!hasStepAnswer && !(reason === "stop" && this.hasRunAnswer)) {
      throw this.fail("PROVIDER_MALFORMED_STREAM");
    }
    this.hasRunAnswer ||= hasStepAnswer;
  }

  terminalFailure(): AgentFailureCode | undefined {
    return this.failure ?? (this.steps >= AGENT_LIMITS.steps && this.lastFinishReason === "tool-calls"
      ? "AGENT_LIMIT" : undefined);
  }
}

function countableProviderOptions(options: SharedV3ProviderOptions | undefined): SharedV3ProviderOptions | undefined {
  if (options === undefined) return undefined;
  const { mastra: _internal, ...modelOptions } = options;
  return modelOptions;
}

/** Single provider boundary: bound input/output, capture usage, erase raw errors. */
export class GuardedLanguageModel implements LanguageModelV3 {
  readonly specificationVersion = "v3" as const;
  constructor(private readonly delegate: LanguageModelV3, private readonly observation: RunModelObservation) {}
  get modelId() { return this.delegate.modelId; }
  get provider() { return this.delegate.provider; }
  get supportedUrls() { return this.delegate.supportedUrls; }

  async doGenerate(options: LanguageModelV3CallOptions): Promise<LanguageModelV3GenerateResult> {
    try {
      const result = await this.delegate.doGenerate(this.observation.begin(options));
      this.observation.output(JSON.stringify(result.content));
      this.observation.finish({ type: "finish", finishReason: result.finishReason, usage: result.usage },
        result.content.some((part) => part.type === "tool-call" || (part.type === "text" && part.text.trim().length > 0)));
      return { ...result, usage: frameworkTokenUsage(result.usage) };
    } catch (error) { throw this.failure(error, options.abortSignal); }
  }

  async doStream(options: LanguageModelV3CallOptions) {
    let result: Awaited<ReturnType<LanguageModelV3["doStream"]>>;
    try {
      result = await this.delegate.doStream(this.observation.begin(options));
    } catch (error) { throw this.failure(error, options.abortSignal); }
    const reader = result.stream.getReader();
    const observation = this.observation;
    const failure = (error: unknown) => this.failure(error, options.abortSignal);
    let finished = false;
    let hasAnswer = false;
    return { ...result, stream: new ReadableStream<LanguageModelV3StreamPart>({
      async pull(controller) {
        try {
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
          }
          if (part.type !== "text-delta" && part.type !== "reasoning-delta" && part.type !== "tool-input-delta" && part.type !== "tool-call") {
            observation.output(JSON.stringify(part));
          }
          if (part.type === "finish") {
            observation.finish(part, hasAnswer);
            finished = true;
          }
          controller.enqueue(part.type === "finish" ? { ...part, usage: frameworkTokenUsage(part.usage) } : part);
        } catch (error) {
          void reader.cancel().catch(() => undefined);
          controller.error(failure(error));
        }
      },
      cancel: (reason) => reader.cancel(reason),
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
