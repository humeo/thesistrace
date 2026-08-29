import { expect, test } from "vitest";

import { ScriptedLanguageModel } from "./scripted-language-model.js";
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

  expect(parts.filter((part) => part.type === "text-delta")).toEqual([
    { type: "text-delta", id: "scripted-text", delta: "I can help turn that idea " },
    { type: "text-delta", id: "scripted-text", delta: "into a testable Alpha." },
  ]);
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
