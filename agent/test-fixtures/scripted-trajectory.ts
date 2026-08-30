import { isJSONValue, type LanguageModelV3CallOptions } from "@ai-sdk/provider";

import { ScriptedLanguageModel } from "../src/scripted-language-model.js";

export type RecordedToolCall = Readonly<{
  input: Record<string, unknown>;
  name: string;
}>;

export async function runScriptedTrajectory(
  options: LanguageModelV3CallOptions,
  output: (call: RecordedToolCall & { occurrence: number }) => unknown,
): Promise<Readonly<{
  calls: readonly RecordedToolCall[];
  text: string;
  waits: readonly number[];
}>> {
  const waits: number[] = [];
  const model = new ScriptedLanguageModel(
    "scripted-v1",
    "reply",
    async (seconds) => {
      waits.push(seconds);
    },
  );
  const calls: RecordedToolCall[] = [];
  const occurrences = new Map<string, number>();
  for (let step = 0; step < 24; step += 1) {
    const generated = await model.doGenerate(options);
    const toolCall = generated.content.find((part) => part.type === "tool-call");
    if (toolCall === undefined || toolCall.type !== "tool-call") {
      const text = generated.content
        .filter((part) => part.type === "text")
        .map((part) => part.text)
        .join("");
      return { calls, text, waits };
    }
    const input = JSON.parse(toolCall.input) as Record<string, unknown>;
    const call = { input, name: toolCall.toolName };
    calls.push(call);
    const occurrence = (occurrences.get(call.name) ?? 0) + 1;
    occurrences.set(call.name, occurrence);
    appendExchange(
      options,
      toolCall.toolCallId,
      call.name,
      input,
      output({ ...call, occurrence }),
    );
  }
  throw new Error("Scripted research trajectory exceeded its test bound");
}

export function scriptedCallOptions(
  prompt: string,
  tools: NonNullable<LanguageModelV3CallOptions["tools"]>,
): LanguageModelV3CallOptions {
  return {
    prompt: [{
      content: "ThesisTrace instructions. Agent Run identity: 00000000-0000-4000-8000-000000000041.",
      role: "system",
    }, {
      content: [{ type: "text", text: prompt }],
      role: "user",
    }],
    tools,
  };
}

export function appendExchange(
  options: LanguageModelV3CallOptions,
  toolCallId: string,
  toolName: string,
  input: Record<string, unknown>,
  output: unknown,
): void {
  if (!isJSONValue(output)) {
    throw new Error(`Test Tool result for ${toolName} is not JSON-safe`);
  }
  options.prompt.push({
    content: [{ input, toolCallId, toolName, type: "tool-call" }],
    role: "assistant",
  });
  options.prompt.push({
    content: [{
      output: { type: "json", value: output },
      toolCallId,
      toolName,
      type: "tool-result",
    }],
    role: "tool",
  });
}
