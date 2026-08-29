import type {
  LanguageModelV3,
  LanguageModelV3CallOptions,
  LanguageModelV3GenerateResult,
  LanguageModelV3StreamPart,
  LanguageModelV3Usage,
} from "@ai-sdk/provider";

export class RunUsageCapture {
  private usage: PersistedTokenUsage | undefined;

  capture(usage: LanguageModelV3Usage): void {
    this.usage = normalizeTokenUsage(usage);
  }

  value(): PersistedTokenUsage | undefined {
    return this.usage === undefined ? undefined : structuredClone(this.usage);
  }
}

export type PersistedTokenUsage = Readonly<{
  reported: true;
  inputTokens: Readonly<{
    cacheRead: number | null;
    cacheWrite: number | null;
    noCache: number | null;
    total: number | null;
  }>;
  outputTokens: Readonly<{
    reasoning: number | null;
    text: number | null;
    total: number | null;
  }>;
}>;

export class UsageCapturingLanguageModel implements LanguageModelV3 {
  readonly specificationVersion = "v3" as const;

  constructor(
    private readonly delegate: LanguageModelV3,
    private readonly capture: RunUsageCapture,
  ) {}

  get modelId(): string {
    return this.delegate.modelId;
  }

  get provider(): string {
    return this.delegate.provider;
  }

  get supportedUrls(): LanguageModelV3["supportedUrls"] {
    return this.delegate.supportedUrls;
  }

  async doGenerate(
    options: LanguageModelV3CallOptions,
  ): Promise<LanguageModelV3GenerateResult> {
    const result = await this.delegate.doGenerate(options);
    this.capture.capture(result.usage);
    return result;
  }

  async doStream(
    options: LanguageModelV3CallOptions,
  ): Promise<{ stream: ReadableStream<LanguageModelV3StreamPart> }> {
    const result = await this.delegate.doStream(options);
    const capture = this.capture;
    return {
      ...result,
      stream: result.stream.pipeThrough(new TransformStream({
        transform(part, controller) {
          if (part.type === "finish") capture.capture(part.usage);
          controller.enqueue(part);
        },
      })),
    };
  }
}

function normalizeTokenUsage(usage: LanguageModelV3Usage): PersistedTokenUsage {
  return {
    reported: true,
    inputTokens: {
      cacheRead: tokenCount(usage.inputTokens.cacheRead),
      cacheWrite: tokenCount(usage.inputTokens.cacheWrite),
      noCache: tokenCount(usage.inputTokens.noCache),
      total: tokenCount(usage.inputTokens.total),
    },
    outputTokens: {
      reasoning: tokenCount(usage.outputTokens.reasoning),
      text: tokenCount(usage.outputTokens.text),
      total: tokenCount(usage.outputTokens.total),
    },
  };
}

function tokenCount(value: number | undefined): number | null {
  return Number.isSafeInteger(value) && (value ?? -1) >= 0 ? value ?? null : null;
}
