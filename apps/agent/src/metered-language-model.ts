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
  type ModelReservation,
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
    private readonly budget: Pick<ModelBudget, "reserve" | "settle" | "absorb">,
    private readonly researcherId: string,
    private readonly runId?: string,
  ) {
    this.metadata = factory(globalThis.fetch);
  }

  private call(options: LanguageModelV3CallOptions) {
    let reservation: ModelReservation | undefined;
    let known = false;
    const price = this.model.pricing;
    const reserve = (amount: number) =>
      this.runId === undefined
        ? this.budget.reserve(this.researcherId, amount)
        : this.budget.reserve(this.researcherId, amount, this.runId);
    const meteredFetch: typeof globalThis.fetch = async (input, init) => {
      if (reservation !== undefined)
        throw new AgentRunFailure("INTERNAL_FAILURE");
      const output = options.maxOutputTokens ?? this.model.maxOutputTokens;
      reservation = await reserve(
        this.model.contextWindow *
          Math.max(price.input, price.cacheRead, price.cacheWrite) +
          output * price.output,
      );
      return fetch(input, init);
    };
    return {
      delegate: this.factory(meteredFetch),
      prepare: async () => {
        if (this.model.providerAdapter === "scripted")
          reservation = await reserve(0);
      },
      unknown: async () => {
        if (reservation && !known) await this.budget.absorb(reservation);
      },
      settle: async (usage: LanguageModelV3Usage) => {
        if (reservation === undefined)
          throw new AgentRunFailure("INTERNAL_FAILURE");
        const actual = Object.values(price).every((value) => value === 0)
          ? 0
          : modelCost(usage, price);
        if (actual === null)
          throw new AgentRunFailure("PROVIDER_MALFORMED_STREAM");
        // Set this before awaiting the database: known usage awaiting settlement
        // must retain its reservation on DB failure, never be absorbed as unknown.
        known = true;
        await this.budget.settle(reservation, actual);
        if (actual > reservation.amount)
          throw new AgentRunFailure("INTERNAL_FAILURE");
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
    const call = this.call(options);
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
    const call = this.call(options);
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
