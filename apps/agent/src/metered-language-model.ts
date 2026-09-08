import type { LanguageModelV3, LanguageModelV3CallOptions, LanguageModelV3StreamPart, LanguageModelV3Usage } from "@ai-sdk/provider";
import type { RegisteredModel } from "./model-registry.js";
import { ModelBudget, modelCost, type ModelReservation } from "./model-budget.js";
import { AgentRunFailure } from "./run-failure.js";

/** Meter the SDK's final provider request, including titles and memory calls. */
export class MeteredLanguageModel implements LanguageModelV3 {
  readonly specificationVersion = "v3" as const;
  private readonly metadata: LanguageModelV3;
  get supportedUrls() { return this.metadata.supportedUrls; }
  get modelId() { return this.metadata.modelId; }
  get provider() { return this.metadata.provider; }
  constructor(private readonly factory: (fetch: typeof globalThis.fetch) => LanguageModelV3,
    private readonly model: RegisteredModel, private readonly budget: Pick<ModelBudget, "reserve" | "settle">,
    private readonly researcherId: string) { this.metadata = factory(globalThis.fetch); }

  private call(options: LanguageModelV3CallOptions) {
    let reservation: ModelReservation | undefined;
    const price = this.model.pricing;
    const free = Object.values(price).every(value => value === 0);
    const meteredFetch: typeof globalThis.fetch = async (input, init) => {
      if (reservation !== undefined) throw new AgentRunFailure("INTERNAL_FAILURE");
      const url = new URL(input instanceof Request ? input.url : input.toString());
      if (typeof init?.body !== "string") throw new AgentRunFailure("INTERNAL_FAILURE");
      const body = JSON.parse(init.body) as Record<string, unknown>;
      let tokens = 0;
      if (!free) {
        const count = tokenCountRequest(this.model, url, body);
        const counted = await fetch(count.url, { ...init,
          body: JSON.stringify(count.body), redirect: "error" });
        if (!counted.ok) throw new AgentRunFailure("PROVIDER_UNAVAILABLE");
        const value = await counted.json() as Record<string, unknown>;
        const inputTokens = value[count.field];
        if (typeof inputTokens !== "number" || !Number.isSafeInteger(inputTokens) || inputTokens < 0) {
          throw new AgentRunFailure("PROVIDER_MALFORMED_STREAM");
        }
        tokens = inputTokens;
        if (tokens > this.model.contextWindow) throw new AgentRunFailure("CONTEXT_TOO_LARGE");
      }
      const output = options.maxOutputTokens ?? this.model.maxOutputTokens;
      reservation = await this.budget.reserve(this.researcherId,
        tokens * Math.max(price.input, price.cacheRead, price.cacheWrite) + output * price.output);
      // Once dispatched, any ambiguous failure retains the reservation.
      return fetch(input, init);
    };
    return {
      delegate: this.factory(meteredFetch),
      prepare: async () => {
        if (this.model.providerAdapter === "scripted") reservation = await this.budget.reserve(this.researcherId, 0);
      },
      settle: async (usage: LanguageModelV3Usage) => {
        if (reservation === undefined) throw new AgentRunFailure("INTERNAL_FAILURE");
        const actual = free ? 0 : modelCost(usage, price);
        if (actual === null) throw new AgentRunFailure("PROVIDER_MALFORMED_STREAM");
        await this.budget.settle(reservation, actual);
        if (actual > reservation.amount) throw new AgentRunFailure("INTERNAL_FAILURE");
      },
    };
  }

  async doGenerate(options: LanguageModelV3CallOptions) {
    options = { ...options, maxOutputTokens: Math.min(options.maxOutputTokens ?? this.model.maxOutputTokens, this.model.maxOutputTokens) };
    const call = this.call(options);
    await call.prepare();
    const result = await call.delegate.doGenerate(options);
    await call.settle(result.usage);
    return result;
  }

  async doStream(options: LanguageModelV3CallOptions) {
    options = { ...options, maxOutputTokens: Math.min(options.maxOutputTokens ?? this.model.maxOutputTokens, this.model.maxOutputTokens) };
    const call = this.call(options);
    await call.prepare();
    const result = await call.delegate.doStream(options);
    return { ...result, stream: result.stream.pipeThrough(new TransformStream<LanguageModelV3StreamPart, LanguageModelV3StreamPart>({
      async transform(part, controller) {
        if (part.type === "finish") await call.settle(part.usage);
        controller.enqueue(part);
      },
    })) };
  }
}

const COUNT_FIELDS = new Set(["model", "input", "instructions", "tools", "tool_choice", "text",
  "reasoning", "previous_response_id", "conversation", "truncation", "parallel_tool_calls"]);

function tokenCountRequest(model: RegisteredModel, requestUrl: URL, body: Record<string, unknown>) {
  const url = new URL(requestUrl);
  const select = (keys: Set<string>) => Object.fromEntries(Object.entries(body).filter(([key]) => keys.has(key)));
  if (model.providerAdapter === "openai" && url.pathname.endsWith("/responses")) {
    url.pathname += "/input_tokens";
    return { url, body: select(COUNT_FIELDS), field: "input_tokens" };
  }
  if (model.providerAdapter === "anthropic" && url.pathname.endsWith("/messages")) {
    url.pathname += "/count_tokens";
    return { url, body: select(new Set(["model", "messages", "system", "tools", "tool_choice", "thinking"])), field: "input_tokens" };
  }
  if (model.providerAdapter === "google" && /:(streamGenerateContent|generateContent)$/.test(url.pathname)) {
    url.pathname = url.pathname.replace(/:(streamGenerateContent|generateContent)$/, ":countTokens");
    url.searchParams.delete("alt");
    return { url, body: { generateContentRequest: { ...body, model: `models/${model.providerModelId}` } }, field: "totalTokens" };
  }
  throw new AgentRunFailure("INVALID_MODEL");
}
