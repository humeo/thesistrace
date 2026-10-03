import { isJSONObject, type JSONObject, type LanguageModelV3CallOptions } from "@ai-sdk/provider";
import type { MastraDBMessage } from "@mastra/core/agent";

export const RESEARCH_A2UI_TOOL_NAME = "render_a2ui";

/** UI payloads belong to display/replay. Only correctable errors reach models. */
export function researchA2UIModelOutput(output: unknown): { type: "json"; value: JSONObject } | { type: "text"; value: "" } {
  return isJSONObject(output) && output.error === true
    ? { type: "json", value: output }
    : { type: "text", value: "" };
}

/** Project copies at the context boundary; never rewrite durable UI evidence. */
export function modelFacingResearchPart(part: MastraDBMessage["content"]["parts"][number]): typeof part {
  if (part.type !== "tool-invocation" || part.toolInvocation.toolName !== RESEARCH_A2UI_TOOL_NAME
    || part.toolInvocation.state !== "result") return part;
  const output = researchA2UIModelOutput(part.toolInvocation.result);
  if (output.type !== "text") return part;
  return { ...part, toolInvocation: { ...part.toolInvocation, result: output.value },
    providerMetadata: { ...part.providerMetadata, mastra: { ...part.providerMetadata?.mastra, modelOutput: output } } };
}

export function modelFacingResearchMessages(messages: readonly MastraDBMessage[]): MastraDBMessage[] {
  return messages.map(message => ({ ...message, content: { ...message.content, parts: message.content.parts.map(modelFacingResearchPart) } }));
}

/** Also covers provider-shaped history before any checkpoint has been published. */
export function modelFacingResearchRequest(request: LanguageModelV3CallOptions): LanguageModelV3CallOptions {
  let changed = false;
  const prompt = request.prompt.map(message => {
    if (message.role !== "tool") return message;
    const content = message.content.map(part => {
      if (part.type !== "tool-result" || part.toolName !== RESEARCH_A2UI_TOOL_NAME) return part;
      const output = part.output;
      if (output.type === "error-text" || output.type === "error-json" || output.type === "execution-denied"
        || (output.type === "json" && isJSONObject(output.value) && output.value.error === true)
        || (output.type === "text" && output.value === "")) return part;
      changed = true;
      return { ...part, output: researchA2UIModelOutput(undefined) };
    });
    return { ...message, content };
  });
  return changed ? { ...request, prompt } : request;
}
