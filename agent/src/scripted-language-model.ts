import type {
  LanguageModelV3,
  LanguageModelV3CallOptions,
  LanguageModelV3GenerateResult,
  LanguageModelV3StreamPart,
  LanguageModelV3Usage,
} from "@ai-sdk/provider";

import {
  scriptedResearchDecision,
  type ScriptedResearchDecision,
} from "./scripted-research-model.js";

export {
  SCRIPTED_ADMISSION_REPAIR_IDEA_PROMPT,
  SCRIPTED_AMBIGUOUS_IDEA_PROMPT,
  SCRIPTED_FACTOR_IDEA_PROMPT,
  SCRIPTED_FORMULA_REPAIR_IDEA_PROMPT,
  SCRIPTED_RETRY_INTERRUPTED_PROMPT,
  SCRIPTED_RESUME_RESEARCH_PROMPT,
  SCRIPTED_STRATEGY_IDEA_PROMPT,
  SCRIPTED_SUBMIT_ONLY_IDEA_PROMPT,
} from "./scripted-research-model.js";

export type ScriptedLanguageModelMode = "reply" | "throw-before-stream";
export const SCRIPTED_FAILURE_MODEL_ID = "scripted-failure-v1";
export const SCRIPTED_TOOL_PROMPT = "[scripted-tool-turn] Inspect the available research context.";

export type ScriptedGuidanceWait = (
  seconds: number,
  signal: AbortSignal | undefined,
) => Promise<void>;

const responseText = "I can help turn that idea into a testable Alpha.";
const toolResponseText = "I checked the available ThesisTrace research data and can now refine the Alpha.";
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
    private readonly guidanceWait: ScriptedGuidanceWait = waitForGuidance,
  ) {}

  async doGenerate(
    options: LanguageModelV3CallOptions,
  ): Promise<LanguageModelV3GenerateResult> {
    this.assertAvailable();
    const response = scriptedResponse(options);
    if (response.waitSeconds !== undefined) {
      await this.guidanceWait(response.waitSeconds, options.abortSignal);
    }
    const tool = response.tool;
    if (tool !== null) {
      const toolCallId = nextScriptedToolCallId(options);
      return {
        content: [{
          input: JSON.stringify(tool.input),
          toolCallId,
          toolName: tool.name,
          type: "tool-call",
        }],
        finishReason: { unified: "tool-calls", raw: "scripted-tool-call" },
        response: responseMetadata(this.modelId),
        usage,
        warnings: [],
      };
    }
    return {
      content: [{
        type: "text",
        text: response.text,
      }],
      finishReason: { unified: "stop", raw: "scripted-stop" },
      response: responseMetadata(this.modelId),
      usage,
      warnings: [],
    };
  }

  async doStream(
    options: LanguageModelV3CallOptions,
  ): Promise<{ stream: ReadableStream<LanguageModelV3StreamPart> }> {
    this.assertAvailable();
    const modelId = this.modelId;
    const response = scriptedResponse(options);
    if (response.waitSeconds !== undefined) {
      await this.guidanceWait(response.waitSeconds, options.abortSignal);
    }
    const tool = response.tool;
    const toolCallId = tool === null ? null : nextScriptedToolCallId(options);
    const selectedChunks = response.chunks;
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
          if (tool !== null && toolCallId !== null) {
            controller.enqueue({
              input: JSON.stringify(tool.input),
              toolCallId,
              toolName: tool.name,
              type: "tool-call",
            });
            controller.enqueue({
              type: "finish",
              finishReason: {
                unified: "tool-calls",
                raw: "scripted-tool-call",
              },
              usage,
            });
            controller.close();
            return;
          }
          controller.enqueue({ type: "text-start", id: "scripted-text" });
          for (const delta of selectedChunks) {
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

type ScriptedResponse = Readonly<{
  chunks: readonly string[];
  text: string;
  tool: Readonly<{
    input: Readonly<Record<string, unknown>>;
    name: string;
  }> | null;
  waitSeconds?: number;
}>;

function scriptedResponse(options: LanguageModelV3CallOptions): ScriptedResponse {
  const research = scriptedResearchDecision(options);
  if (research !== null) return responseFromResearchDecision(research);
  const tool = scriptedTool(options);
  if (tool !== null) {
    return {
      chunks: [],
      text: "",
      tool: { input: {}, name: tool.name },
    };
  }
  const selectedText = hasScriptedToolResult(options) ? toolResponseText : responseText;
  return {
    chunks: selectedText === toolResponseText
      ? ["I checked the available ThesisTrace research data ", "and can now refine the Alpha."]
      : responseChunks,
    text: selectedText,
    tool: null,
  };
}

function responseFromResearchDecision(
  decision: ScriptedResearchDecision,
): ScriptedResponse {
  if (decision.kind === "text") {
    return {
      chunks: chunkResponse(decision.text),
      text: decision.text,
      tool: null,
    };
  }
  return {
    chunks: [],
    text: "",
    tool: { input: decision.input, name: decision.name },
    ...(decision.waitSeconds === undefined
      ? {}
      : { waitSeconds: decision.waitSeconds }),
  };
}

function chunkResponse(text: string): readonly string[] {
  if (text.length <= 256) return [text];
  const chunks: string[] = [];
  for (let offset = 0; offset < text.length; offset += 256) {
    chunks.push(text.slice(offset, offset + 256));
  }
  return chunks;
}

function waitForGuidance(
  seconds: number,
  signal: AbortSignal | undefined,
): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted === true) {
      reject(signal.reason ?? new Error("SCRIPTED_GUIDANCE_WAIT_ABORTED"));
      return;
    }
    const timer = setTimeout(finish, seconds * 1_000);
    const abort = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      reject(signal?.reason ?? new Error("SCRIPTED_GUIDANCE_WAIT_ABORTED"));
    };
    function finish() {
      signal?.removeEventListener("abort", abort);
      resolve();
    }
    signal?.addEventListener("abort", abort, { once: true });
  });
}

function scriptedTool(
  options: LanguageModelV3CallOptions,
): Readonly<{ name: string }> | null {
  if (
    latestScriptedToolPromptIndex(options) < 0
    || hasScriptedToolResult(options)
  ) {
    return null;
  }
  const tool = options.tools?.find((candidate) => (
    candidate.type === "function"
    && (!Array.isArray(candidate.inputSchema.required)
      || candidate.inputSchema.required.length === 0)
  ));
  return tool?.type === "function" ? { name: tool.name } : null;
}

function hasScriptedToolResult(options: LanguageModelV3CallOptions): boolean {
  const promptIndex = latestScriptedToolPromptIndex(options);
  if (promptIndex < 0) return false;
  return options.prompt.slice(promptIndex + 1).some((message) => (
    (message.role === "tool" || message.role === "assistant")
    && message.content.some((part) => part.type === "tool-result")
  ));
}

function latestScriptedToolPromptIndex(
  options: LanguageModelV3CallOptions,
): number {
  for (let index = options.prompt.length - 1; index >= 0; index -= 1) {
    const message = options.prompt[index];
    if (
      message?.role === "user"
      && Array.isArray(message.content)
      && message.content.some((part) => (
        part.type === "text" && part.text.includes(SCRIPTED_TOOL_PROMPT)
      ))
    ) {
      return index;
    }
  }
  return -1;
}

function nextScriptedToolCallId(options: LanguageModelV3CallOptions): string {
  const priorCalls = options.prompt.reduce(
    (count, message) => count + (
      Array.isArray(message.content)
        ? message.content.filter((part) => part.type === "tool-call").length
        : 0
    ),
    0,
  );
  return `scripted-tool-call-${priorCalls + 1}`;
}

function responseMetadata(modelId: string): Readonly<{
  id: string;
  modelId: string;
  timestamp: Date;
}> {
  return {
    id: "scripted-response",
    modelId,
    timestamp: new Date(0),
  };
}
