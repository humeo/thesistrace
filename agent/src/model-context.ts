import { createHash } from "node:crypto";
import type { LanguageModelV3CallOptions, SharedV3ProviderOptions } from "@ai-sdk/provider";
import { estimateTokenCount } from "tokenx";

export type ModelCapacity = Readonly<{ contextWindow: number; maxOutputTokens: number }>;
export type ModelRequestBudget = Readonly<{
  inputTokens: number;
  desiredOutputTokens: number;
  outputTokens: number;
  contextWindow: number;
  safetyTokens: number;
}>;

/** Run-local, bounded estimates; hashes avoid retaining a second copy of private history. */
export class ModelInputTokenCounter {
  private readonly estimates = new Map<string, number>();

  estimateSerialized(value: unknown): number {
    const text = JSON.stringify(value) ?? "";
    const key = createHash("sha256").update(text).digest("hex");
    const cached = this.estimates.get(key);
    if (cached !== undefined) return cached;
    const tokens = estimateTokenCount(text);
    if (this.estimates.size >= 2048) this.estimates.delete(this.estimates.keys().next().value!);
    this.estimates.set(key, tokens);
    return tokens;
  }

  estimate(options: Pick<LanguageModelV3CallOptions, "prompt" | "tools" | "responseFormat" | "toolChoice">): number {
    // Count each immutable message separately so appends reuse previous estimates.
    // Explicit envelope punctuation is conservative at segment boundaries.
    return this.estimateSerialized({ prompt: [], tools: [], responseFormat: options.responseFormat, toolChoice: options.toolChoice })
      + (options.tools ?? []).reduce((total, tool) => total + this.estimateSerialized(tool) + 1, 0)
      + options.prompt.reduce((total, message) => total + this.estimateSerialized({
        ...message,
        providerOptions: countableProviderOptions(message.providerOptions),
        content: typeof message.content === "string" ? message.content : message.content.map((part) => ({
          ...part, providerOptions: countableProviderOptions(part.providerOptions),
        })),
      }) + 1, 0);
  }
}

/** Count provider-visible protocol content without OM's internal copies. */
export function estimateModelInput(options: Pick<LanguageModelV3CallOptions, "prompt" | "tools" | "responseFormat" | "toolChoice">): number {
  return new ModelInputTokenCounter().estimate(options);
}

export function modelRequestBudget(options: LanguageModelV3CallOptions, model: ModelCapacity, counter = new ModelInputTokenCounter()): ModelRequestBudget {
  const inputTokens = counter.estimate(options);
  const desiredOutputTokens = Math.min(options.maxOutputTokens ?? model.maxOutputTokens, model.maxOutputTokens);
  const safetyTokens = 4096;
  return {
    inputTokens, desiredOutputTokens, contextWindow: model.contextWindow, safetyTokens,
    outputTokens: Math.min(desiredOutputTokens, model.contextWindow - inputTokens - safetyTokens),
  };
}

function countableProviderOptions(options: SharedV3ProviderOptions | undefined): SharedV3ProviderOptions | undefined {
  if (options === undefined) return undefined;
  const { mastra: _internal, ...modelOptions } = options;
  return modelOptions;
}
