import { APICallError, type LanguageModelV3CallOptions, type LanguageModelV3StreamPart } from "@ai-sdk/provider";
import { latestUserText, toolObservations } from "./scripted-research-support.js";
import { SCRIPTED_FAILURE_AFTER_ADMISSION_PROMPT } from "./scripted-research-model.js";
import { PRIVACY_CANARIES } from "./scripted-privacy-model.js";

export const SCRIPTED_FAILURE_PROMPTS = Object.freeze({
  PROVIDER_TIMEOUT: "[scripted-provider-timeout] Test a bounded provider timeout.",
  PROVIDER_RATE_LIMIT: "[scripted-provider-rate-limit] Test provider rate limiting.",
  PROVIDER_AUTHENTICATION: "[scripted-provider-authentication] Test a rejected provider credential.",
  PROVIDER_REFUSAL: "[scripted-provider-refusal] Test a provider refusal.",
  PROVIDER_MALFORMED_STREAM: "[scripted-provider-malformed] Test an invalid provider stream.",
  AGENT_LIMIT: "[scripted-provider-output-limit] Test a bounded provider output.",
  INTERNAL_FAILURE: "[scripted-provider-unexpected] Test an unexpected provider error.",
});
export const SCRIPTED_LONG_TOOL_LOOP_PROMPT = "[scripted-long-tool-loop] Inspect research context twenty times, then finish.";
export const SCRIPTED_FAILURE_AFTER_TOOL_PROMPT = "[scripted-failure-after-tool] Inspect research context, then test a provider timeout.";
export const SCRIPTED_INVALID_USAGE_PROMPT = "[scripted-invalid-usage] Complete an answer with invalid accounting.";
export const SCRIPTED_MULTI_STEP_OUTPUT_PROMPT = "[scripted-multi-step-output] Produce two bounded outputs around a research context inspection.";
export const SCRIPTED_TIMELINE_PROMPT = "[scripted-timeline] Explain before, between and after two context reads.";

/** Faults and envelope controls exist only in the test-only Scripted Provider. */
export function scriptedFailureStream(options: LanguageModelV3CallOptions) {
  if (options.prompt.some((message) => message.role === "system" && message.content.includes("[thesistrace-session-title]"))) return undefined;
  const user = latestUserText(options);
  const text = user?.text;
  if (text === SCRIPTED_TIMELINE_PROMPT && user !== undefined) {
    const reads = toolObservations(options, user.index).filter((item) => item.name === "get_research_context").length;
    return parts([
      textStart,
      { ...textDelta, delta: ["Checking.", "Read the context.", "Finished."][reads] ?? "Finished." },
      textEnd,
      ...(reads < 2 ? [{ type: "tool-call" as const, toolCallId: `timeline-read-${reads}`, toolName: "get_research_context", input: "{}" }] : []),
      { ...finish, finishReason: { unified: reads < 2 ? "tool-calls" : "stop", raw: "scripted" } },
    ]);
  }
  if (text === SCRIPTED_MULTI_STEP_OUTPUT_PROMPT && user !== undefined) {
    const contextInspected = toolObservations(options, user.index).some((item) => item.name === "get_research_context");
    const id = contextInspected ? "scripted-output-after-tool" : "scripted-output-before-tool";
    const word = contextInspected ? "bravo" : "alpha";
    return parts([
      { type: "text-start", id },
      { type: "text-delta", id, delta: `${`${word} `.repeat(4_499)}${word}.` },
      { type: "text-end", id },
      ...(contextInspected ? [] : [{ type: "tool-call" as const, toolCallId: "scripted-output-context", toolName: "get_research_context", input: "{}" }]),
      {
        ...finish,
        finishReason: { unified: contextInspected ? "stop" : "tool-calls", raw: "scripted" },
        usage: { ...finish.usage, outputTokens: { total: 4_500, text: 4_500, reasoning: 0 } },
      },
    ]);
  }
  if (text === SCRIPTED_FAILURE_AFTER_ADMISSION_PROMPT && toolObservations(options, 0).some((item) => item.name === "submit_research_run" && typeof item.output.run_id === "string")) {
    throw new DOMException("private-after-admission-canary", "TimeoutError");
  }
  if (text === SCRIPTED_LONG_TOOL_LOOP_PROMPT || text === SCRIPTED_FAILURE_AFTER_TOOL_PROMPT) {
    const toolResults = options.prompt.filter((message) => message.role === "tool").length;
    if (text === SCRIPTED_LONG_TOOL_LOOP_PROMPT && toolResults >= 20) return parts([textStart, textDelta, textEnd, finish]);
    if (text === SCRIPTED_FAILURE_AFTER_TOOL_PROMPT && toolResults > 0) throw new DOMException("private-timeout-canary", "TimeoutError");
    return parts([
      { type: "tool-call", toolCallId: `scripted-fault-call-${toolResults + 1}`, toolName: "get_research_context", input: "{}" },
      { ...finish, finishReason: { unified: "tool-calls", raw: "scripted" } },
    ]);
  }
  if (text === SCRIPTED_INVALID_USAGE_PROMPT) {
    return parts([textStart, textDelta, textEnd, { ...finish, usage: undefined } as unknown as LanguageModelV3StreamPart]);
  }
  const code = Object.entries(SCRIPTED_FAILURE_PROMPTS).find(([, prompt]) => text === prompt)?.[0];
  if (code === undefined) return undefined;
  if (code === "PROVIDER_TIMEOUT") throw new DOMException("private-timeout-canary", "TimeoutError");
  if (code === "PROVIDER_AUTHENTICATION" || code === "PROVIDER_RATE_LIMIT") {
    throw new APICallError({ message: "private-provider-canary", url: "https://private.invalid", requestBodyValues: "private-prompt-canary", statusCode: code === "PROVIDER_AUTHENTICATION" ? 401 : 429 });
  }
  if (code === "INTERNAL_FAILURE") throw new Error(`${PRIVACY_CANARIES.provider_error} ${PRIVACY_CANARIES.path}`);
  if (code === "PROVIDER_MALFORMED_STREAM") return parts([{ type: "malformed", private: "private-stream-canary" } as unknown as LanguageModelV3StreamPart]);
  return parts([textStart, textDelta, textEnd, {
    ...finish, finishReason: { unified: code === "AGENT_LIMIT" ? "length" : "content-filter", raw: "scripted" },
  }]);
}

const textStart = { type: "text-start", id: "scripted-fault-text" } as const;
const textDelta = { type: "text-delta", id: "scripted-fault-text", delta: "This is a scripted test response." } as const;
const textEnd = { type: "text-end", id: "scripted-fault-text" } as const;
const finish = {
  type: "finish", finishReason: { unified: "stop", raw: "scripted" },
  usage: { inputTokens: { total: 4, noCache: 4, cacheRead: 0, cacheWrite: 0 }, outputTokens: { total: 3, text: 3, reasoning: 0 } },
} satisfies LanguageModelV3StreamPart;
function parts(values: LanguageModelV3StreamPart[]) {
  return { stream: new ReadableStream<LanguageModelV3StreamPart>({ start(controller) {
    for (const value of values) controller.enqueue(value);
    controller.close();
  } }) };
}
