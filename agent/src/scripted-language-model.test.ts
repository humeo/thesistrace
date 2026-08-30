import type { LanguageModelV3CallOptions } from "@ai-sdk/provider";
import { expect, test } from "vitest";

import {
  SCRIPTED_TOOL_PROMPT,
  ScriptedLanguageModel,
} from "./scripted-language-model.js";
import {
  RunUsageCapture,
  UsageCapturingLanguageModel,
} from "./usage-capture.js";

const callOptions = {
  prompt: [{ role: "user" as const, content: [{ type: "text" as const, text: "idea" }] }],
};

test("streams deterministic chunks and captures the provider-reported usage", async () => {
  const capture = new RunUsageCapture();
  const model = new UsageCapturingLanguageModel(
    new ScriptedLanguageModel("scripted-v1"),
    capture,
  );
  const result = await model.doStream(callOptions);
  const parts = [];
  const reader = result.stream.getReader();
  for (;;) {
    const part = await reader.read();
    if (part.done) break;
    parts.push(part.value);
  }

  const text = parts
    .filter((part) => part.type === "text-delta")
    .map((part) => part.delta)
    .join("");
  expect(text.trim().length).toBeGreaterThan(0);
  expect(Buffer.byteLength(text, "utf8")).toBeLessThanOrEqual(512);
  expect(capture.value()).toMatchObject({
    inputTokens: { total: 11 },
    outputTokens: { reasoning: 0, text: 12, total: 12 },
  });
});

test("fails deterministically without leaking a synthetic response", async () => {
  const model = new ScriptedLanguageModel("scripted-failure-v1", "throw-before-stream");
  await expect(model.doStream(callOptions)).rejects.toThrow(
    "SCRIPTED_MODEL_FAILURE_INTERNAL_DETAIL",
  );
  await expect(model.doGenerate(callOptions)).rejects.toThrow(
    "SCRIPTED_MODEL_FAILURE_INTERNAL_DETAIL",
  );
});

test("calls a discovered no-argument Tool and then explains its result", async () => {
  const model = new ScriptedLanguageModel("scripted-v1");
  const firstOptions = {
    prompt: [{
      content: [{ type: "text" as const, text: SCRIPTED_TOOL_PROMPT }],
      role: "user" as const,
    }],
    tools: [{
      description: "Read the research context",
      inputSchema: { additionalProperties: false, properties: {}, type: "object" },
      name: "get_research_context",
      type: "function" as const,
    }],
  } satisfies LanguageModelV3CallOptions;
  const first = await readParts(await model.doStream(firstOptions));
  expect(first).toContainEqual({
    input: "{}",
    toolCallId: "scripted-tool-call-1",
    toolName: "get_research_context",
    type: "tool-call",
  });

  const second = await readParts(await model.doStream({
    ...firstOptions,
    prompt: [
      ...firstOptions.prompt,
      {
        content: [{
          input: {},
          toolCallId: "scripted-tool-call-1",
          toolName: "get_research_context",
          type: "tool-call" as const,
        }],
        role: "assistant" as const,
      },
      {
        content: [{
          output: { type: "json" as const, value: { dataset: "secret-server-result" } },
          toolCallId: "scripted-tool-call-1",
          toolName: "get_research_context",
          type: "tool-result" as const,
        }],
        role: "tool" as const,
      },
    ],
  }));
  const explanation = second
    .filter((part) => part.type === "text-delta")
    .map((part) => part.delta)
    .join("");
  expect(explanation.trim().length).toBeGreaterThan(0);
  expect(Buffer.byteLength(explanation, "utf8")).toBeLessThanOrEqual(512);
  expect(explanation).not.toContain("secret-server-result");

  const repeated = await readParts(await model.doStream({
    ...firstOptions,
    prompt: [
      ...firstOptions.prompt,
      {
        content: [{
          input: {},
          toolCallId: "scripted-tool-call-1",
          toolName: "get_research_context",
          type: "tool-call" as const,
        }],
        role: "assistant" as const,
      },
      {
        content: [{
          output: { type: "json" as const, value: { dataset: "first-result" } },
          toolCallId: "scripted-tool-call-1",
          toolName: "get_research_context",
          type: "tool-result" as const,
        }],
        role: "tool" as const,
      },
      {
        content: [{ type: "text" as const, text: SCRIPTED_TOOL_PROMPT }],
        role: "user" as const,
      },
    ],
  }));
  expect(repeated).toContainEqual({
    input: "{}",
    toolCallId: "scripted-tool-call-2",
    toolName: "get_research_context",
    type: "tool-call",
  });
});

async function readParts(
  result: Awaited<ReturnType<ScriptedLanguageModel["doStream"]>>,
) {
  const parts = [];
  const reader = result.stream.getReader();
  for (;;) {
    const part = await reader.read();
    if (part.done) return parts;
    parts.push(part.value);
  }
}
