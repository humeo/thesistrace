import type { LanguageModelV3CallOptions } from "@ai-sdk/provider";
import { expect, test } from "vitest";
import { estimateModelInput, ModelInputTokenCounter } from "./model-context.js";

test("cached estimates preserve input and follow appended and amended message content", () => {
  const counter = new ModelInputTokenCounter();
  const options: LanguageModelV3CallOptions = { prompt: [{ role: "user", content: [{ type: "text", text: "研究目标：长期质量" }] }] };
  const original = structuredClone(options);
  const first = counter.estimate(options);
  expect(options).toEqual(original);
  options.prompt.push({ role: "assistant", content: [{ type: "text", text: "保留资源 ID 与续读游标。" }] });
  expect(counter.estimate(options)).toBeGreaterThan(first);
  expect(counter.estimate(options)).toBe(estimateModelInput(options));
  options.prompt[0] = { role: "user", content: [{ type: "text", text: "Changed constraint. ".repeat(100) }] };
  expect(counter.estimate(options)).toBe(estimateModelInput(options));
  expect(counter.estimate(original)).toBe(first);
});
