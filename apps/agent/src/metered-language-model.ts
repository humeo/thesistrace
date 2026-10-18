import type {
  LanguageModelV3,
  LanguageModelV3CallOptions,
  LanguageModelV3StreamPart,
  LanguageModelV3Usage,
} from "@ai-sdk/provider";
import type { RegisteredModel } from "./model-registry.js";
import {
  ModelBudget,
  modelCost,
  type ModelCall,
} from "./model-budget.js";
import { AgentRunFailure } from "./run-failure.js";

/** Meter every provider invocation, including titles and memory. */
export class MeteredLanguageModel implements LanguageModelV3 {
  readonly specificationVersion = "v3" as const;
  private readonly metadata: LanguageModelV3;
  get supportedUrls() {
    return this.metadata.supportedUrls;
  }
  get modelId() {
    return this.metadata.modelId;
  }
  get provider() {
    return this.metadata.provider;
  }
  constructor(
    private readonly factory: (
      fetch: typeof globalThis.fetch,
    ) => LanguageModelV3,
    private readonly model: RegisteredModel,
    private readonly budget: Pick<ModelBudget, "begin" | "settle" | "absorb">,
    private readonly researcherId: string,
    private readonly runId?: string,
  ) {
    this.metadata = factory(globalThis.fetch);
  }

  private call() {
    let invocation: ModelCall | undefined;
    let known = false;
    const price = this.model.pricing;
    const begin = () =>
      this.runId === undefined
        ? this.budget.begin(this.researcherId)
        : this.budget.begin(this.researcherId, this.runId);
    const meteredFetch: typeof globalThis.fetch = async (input, init) => {
      if (invocation !== undefined)
        throw new AgentRunFailure("INTERNAL_FAILURE");
      invocation = await begin();
      return fetch(input, init);
    };
    return {
      delegate: this.factory(meteredFetch),
      prepare: async () => {
        if (this.model.providerAdapter === "scripted")
          invocation = await begin();
      },
      unknown: async () => {
        if (invocation && !known) await this.budget.absorb(invocation);
      },
      settle: async (usage: LanguageModelV3Usage) => {
        if (invocation === undefined)
          throw new AgentRunFailure("INTERNAL_FAILURE");
        const actual = Object.values(price).every((value) => value === 0)
          ? 0
          : modelCost(usage, price);
        if (actual === null)
          throw new AgentRunFailure("PROVIDER_MALFORMED_STREAM");
        // Set this before awaiting the database: known usage awaiting settlement
        // must retain its charge on DB failure, never be absorbed as unknown.
        known = true;
        await this.budget.settle(invocation, actual);
      },
    };
  }
  private bounded(options: LanguageModelV3CallOptions) {
    return {
      ...options,
      maxOutputTokens: Math.min(
        options.maxOutputTokens ?? this.model.maxOutputTokens,
        this.model.maxOutputTokens,
      ),
    };
  }
  async doGenerate(options: LanguageModelV3CallOptions) {
    options = this.bounded(options);
    const call = this.call();
    try {
      await call.prepare();
      const result = await call.delegate.doGenerate(options);
      await call.settle(result.usage);
      return result;
    } catch (error) {
      await call.unknown();
      throw error;
    }
  }
  async doStream(options: LanguageModelV3CallOptions) {
    options = this.bounded(options);
    const call = this.call();
    try {
      await call.prepare();
      const result = await call.delegate.doStream(options);
      const reader = result.stream.getReader();
      return {
        ...result,
        stream: new ReadableStream<LanguageModelV3StreamPart>(
          {
            async pull(controller) {
              try {
                const part = await reader.read();
                if (part.done) {
                  await call.unknown();
                  controller.close();
                  return;
                }
                if (part.value.type === "finish")
                  await call.settle(part.value.usage);
                controller.enqueue(part.value);
              } catch (error) {
                await call.unknown();
                controller.error(error);
              }
            },
            async cancel(reason) {
              try {
                await reader.cancel(reason);
              } finally {
                await call.unknown();
              }
            },
          },
          { highWaterMark: 0 },
        ),
      };
    } catch (error) {
      await call.unknown();
      throw error;
    }
  }
}
