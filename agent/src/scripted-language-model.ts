import type {
  LanguageModelV3,
  LanguageModelV3CallOptions,
  LanguageModelV3GenerateResult,
  LanguageModelV3StreamPart,
  LanguageModelV3Usage,
} from "@ai-sdk/provider";

export type ScriptedLanguageModelMode = "reply" | "throw-before-stream";
export const SCRIPTED_FAILURE_MODEL_ID = "scripted-failure-v1";

const responseText = "I can help turn that idea into a testable Alpha.";
const responseChunks = [
  "I can help turn that idea ",
  "into a testable Alpha.",
] as const;
const usage: LanguageModelV3Usage = {
  inputTokens: {
    total: 11,
    noCache: 11,
    cacheRead: 0,
    cacheWrite: 0,
  },
  outputTokens: {
    total: 12,
    text: 12,
    reasoning: 0,
  },
  raw: {
    scripted: true,
  },
};

export class ScriptedLanguageModel implements LanguageModelV3 {
  readonly specificationVersion = "v3" as const;
  readonly provider = "thesistrace.scripted";
  readonly supportedUrls = {};

  constructor(
    readonly modelId: string,
    private readonly mode: ScriptedLanguageModelMode = "reply",
  ) {}

  async doGenerate(
    _options: LanguageModelV3CallOptions,
  ): Promise<LanguageModelV3GenerateResult> {
    this.assertAvailable();
    return {
      content: [{ type: "text", text: responseText }],
      finishReason: { unified: "stop", raw: "scripted-stop" },
      response: {
        id: "scripted-response",
        modelId: this.modelId,
        timestamp: new Date(0),
      },
      usage,
      warnings: [],
    };
  }

  async doStream(
    _options: LanguageModelV3CallOptions,
  ): Promise<{ stream: ReadableStream<LanguageModelV3StreamPart> }> {
    this.assertAvailable();
    const modelId = this.modelId;
    return {
      stream: new ReadableStream<LanguageModelV3StreamPart>({
        start(controller) {
          controller.enqueue({ type: "stream-start", warnings: [] });
          controller.enqueue({
            type: "response-metadata",
            id: "scripted-response",
            modelId,
            timestamp: new Date(0),
          });
          controller.enqueue({ type: "text-start", id: "scripted-text" });
          for (const delta of responseChunks) {
            controller.enqueue({ type: "text-delta", id: "scripted-text", delta });
          }
          controller.enqueue({ type: "text-end", id: "scripted-text" });
          controller.enqueue({
            type: "finish",
            finishReason: { unified: "stop", raw: "scripted-stop" },
            usage,
          });
          controller.close();
        },
      }),
    };
  }

  private assertAvailable(): void {
    if (this.mode === "throw-before-stream") {
      throw new Error("SCRIPTED_MODEL_FAILURE_INTERNAL_DETAIL");
    }
  }
}
