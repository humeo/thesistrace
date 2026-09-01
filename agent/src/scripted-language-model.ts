import type {
  LanguageModelV3,
  LanguageModelV3CallOptions,
  LanguageModelV3GenerateResult,
  LanguageModelV3StreamPart,
  LanguageModelV3Usage,
} from "@ai-sdk/provider";

import {
  scriptedResearchDecision,
} from "./scripted-research-model.js";
import { latestUserText, type ScriptedResearchDecision } from "./scripted-research-support.js";
import { scriptedBatchDecision } from "./scripted-batch-model.js";
import { scriptedDailyTrackDecision } from "./scripted-daily-track-model.js";
import { scriptedFailureStream } from "./scripted-failure-model.js";
import { scriptedPrivacyDecision } from "./scripted-privacy-model.js";

export {
  SCRIPTED_START_DAILY_TRACK_PROMPT,
  SCRIPTED_RELOAD_DAILY_TRACK_PROMPT,
  SCRIPTED_REFRESH_DAILY_TRACK_PROMPT,
  SCRIPTED_RETRY_DAILY_TRACK_PROMPT,
  SCRIPTED_RESUME_DAILY_TRACK_PROMPT,
  SCRIPTED_LIST_DAILY_TRACKS_PROMPT,
  SCRIPTED_STOP_DAILY_TRACK_PROMPT,
} from "./scripted-daily-track-model.js";

export {
  SCRIPTED_FACTOR_BATCH_PROMPT,
  SCRIPTED_STRATEGY_SWEEP_PROMPT,
  SCRIPTED_RESUME_BATCH_PROMPT,
  SCRIPTED_BATCH_LIST_PROMPT,
  SCRIPTED_BATCH_OBSERVATIONS_PROMPT,
  SCRIPTED_AMBIGUOUS_BATCH_PROMPT,
} from "./scripted-batch-model.js";

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
export const SCRIPTED_DISCOVERY_PROMPT = "List the authenticated capabilities available in this Chat.";
export const SCRIPTED_INVALID_A2UI_PROMPT =
  "[scripted-invalid-a2ui] Attempt one unsafe research surface.";
export const SCRIPTED_INVALID_A2UI_TOP_LEVEL_PROMPT =
  "[scripted-invalid-a2ui-top-level] Attempt an unknown top-level render field.";
export const SCRIPTED_INVALID_A2UI_DATA_PROMPT =
  "[scripted-invalid-a2ui-data] Attempt non-empty render data.";
export const SCRIPTED_LARGE_A2UI_TABLE_PROMPT =
  "[scripted-a2ui-table] Show a large renderer acceptance sample, not research evidence.";

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
    const failure = scriptedFailureStream(options);
    if (failure !== undefined) return failure;
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
  const sessionTitle = scriptedSessionTitle(options);
  if (sessionTitle !== null) {
    return {
      chunks: [sessionTitle],
      text: sessionTitle,
      tool: null,
    };
  }
  const research = scriptedPrivacyDecision(options) ?? scriptedResearchDecision(options);
  if (research !== null) return responseFromResearchDecision(research);
  const batch = scriptedBatchDecision(options);
  if (batch !== null) return responseFromResearchDecision(batch);
  const track = scriptedDailyTrackDecision(options);
  if (track !== null) return responseFromResearchDecision(track);
  if (latestUserText(options)?.text === SCRIPTED_DISCOVERY_PROMPT) {
    return responseFromResearchDecision({
      kind: "text",
      text: `Available capabilities: ${(options.tools ?? []).map((tool) => tool.name).sort().join(", ")}`,
    });
  }
  const invalidA2UI = scriptedInvalidA2UI(options);
  if (invalidA2UI !== null) return invalidA2UI;
  const tableA2UI = scriptedLargeA2UITable(options);
  if (tableA2UI !== null) return tableA2UI;
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

function scriptedInvalidA2UI(
  options: LanguageModelV3CallOptions,
): ScriptedResponse | null {
  const scenario = [
    { kind: "component", prompt: SCRIPTED_INVALID_A2UI_PROMPT },
    { kind: "top-level", prompt: SCRIPTED_INVALID_A2UI_TOP_LEVEL_PROMPT },
    { kind: "data", prompt: SCRIPTED_INVALID_A2UI_DATA_PROMPT },
  ].map((candidate) => ({
    ...candidate,
    promptIndex: latestExactUserPromptIndex(options, candidate.prompt),
  })).find((candidate) => candidate.promptIndex >= 0);
  if (scenario === undefined) return null;
  const { promptIndex } = scenario;
  const observedResult = options.prompt.slice(promptIndex + 1).some((message) => (
    message.role === "tool"
    && message.content.some((part) => (
      part.type === "tool-result" && part.toolName === "render_a2ui"
    ))
  ));
  if (observedResult) {
    const text = "The unsafe research surface was rejected. This Chat remains usable, and no action was executed.";
    return { chunks: [text], text, tool: null };
  }
  const available = options.tools?.some((tool) => (
    tool.type === "function" && tool.name === "render_a2ui"
  )) === true;
  if (!available) {
    const text = "The registered Agent tools do not include the required research renderer.";
    return { chunks: [text], text, tool: null };
  }
  return {
    chunks: [],
    text: "",
    tool: {
      input: {
        components: [{
          ...(scenario.kind === "component" ? { action: { name: "delete_research" } } : {}),
          component: "Text",
          id: "root",
          text: "MALICIOUS_A2UI_SHOULD_NOT_RENDER",
        }],
        data: scenario.kind === "data" ? { private: "MALICIOUS_A2UI_SHOULD_NOT_RENDER" } : {},
        surfaceId: "unsafe-research-surface",
        ...(scenario.kind === "top-level" ? { unexpected: true } : {}),
      },
      name: "render_a2ui",
    },
  };
}

function scriptedLargeA2UITable(options: LanguageModelV3CallOptions): ScriptedResponse | null {
  const promptIndex = latestExactUserPromptIndex(options, SCRIPTED_LARGE_A2UI_TABLE_PROMPT);
  if (promptIndex < 0) return null;
  const rendered = options.prompt.slice(promptIndex + 1).some((message) => (
    message.role === "tool" && message.content.some((part) => (
      part.type === "tool-result" && part.toolName === "render_a2ui"
    ))
  ));
  const available = options.tools?.some((tool) => (
    tool.type === "function" && tool.name === "render_a2ui"
  )) === true;
  // The rendered table is the complete answer; exercise the native empty-stop
  // continuation instead of requiring an additional prose message.
  if (rendered) return { chunks: [], text: "", tool: null };
  if (!available) {
    const text = "The registered Agent tools do not include the required research renderer.";
    return { chunks: [text], text, tool: null };
  }
  return {
    chunks: [],
    text: "",
    tool: {
      name: "render_a2ui",
      input: {
        components: [{
          caption: "Renderer acceptance sample — not research evidence",
          columns: Array.from({ length: 12 }, (_, index) => `Field ${index + 1}`),
          component: "Table",
          id: "root",
          rows: Array.from({ length: 100 }, (_, row) => (
            Array.from({ length: 12 }, (_, column) => (
              `Sample ${row + 1}:${column + 1} ${"x".repeat(36)}`
            ))
          )),
          summary: "Inspect 100 sample rows",
        }],
        data: {},
        surfaceId: "large-table-acceptance-sample",
      },
    },
  };
}

function scriptedSessionTitle(options: LanguageModelV3CallOptions): string | null {
  const titleRequest = options.prompt.some((message) => (
    message.role === "system"
    && typeof message.content === "string"
    && message.content.includes("[thesistrace-session-title]")
  ));
  if (!titleRequest) return null;
  for (let index = options.prompt.length - 1; index >= 0; index -= 1) {
    const message = options.prompt[index];
    if (message?.role !== "user" || !Array.isArray(message.content)) continue;
    const text = message.content
      .filter((part) => part.type === "text")
      .map((part) => part.text)
      .join(" ")
      .toLowerCase();
    if (/low[- ]volatility/u.test(text) && text.includes("quality")) {
      return "Low-volatility quality Alpha";
    }
    return "Research Alpha idea";
  }
  return "Research Alpha idea";
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

function latestExactUserPromptIndex(
  options: LanguageModelV3CallOptions,
  expected: string,
): number {
  for (let index = options.prompt.length - 1; index >= 0; index -= 1) {
    const message = options.prompt[index];
    if (message?.role !== "user") continue;
    return Array.isArray(message.content)
      && message.content.some((part) => part.type === "text" && part.text === expected)
      ? index
      : -1;
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
