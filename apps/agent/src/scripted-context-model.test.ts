import { expect, test } from "vitest";
import type { LanguageModelV3CallOptions, LanguageModelV3StreamPart } from "@ai-sdk/provider";
import { ScriptedLanguageModel } from "./scripted-language-model.js";

async function response(prompt: LanguageModelV3CallOptions["prompt"]) {
  const model = new ScriptedLanguageModel("scripted-v1");
  const result = await model.doStream({ prompt, tools: [{ type: "function", name: "get_research_context", inputSchema: { type: "object", properties: {} } }] });
  const parts: LanguageModelV3StreamPart[] = [];
  const reader = result.stream.getReader();
  for (;;) { const next = await reader.read(); if (next.done) break; parts.push(next.value); }
  return parts;
}
const user = (text: string) => ({ role: "user" as const, content: [{ type: "text" as const, text }] });

test("Scripted compression supports native empty observations and exact handoff references", async () => {
  const observations = await response([{ role: "system", content: "You are the memory consciousness" }, user("fixed evidence")]);
  expect(observations).toContainEqual({ type: "text-delta", id: "scripted-context", delta: "<observations></observations>" });
  const parts = await response([{ role: "system", content: "Produce a structured handoff summary" },
    user('Summarize the evidence.\n{"requiredReferences":["run_browser_exact","cursor_browser_exact"]}')]);
  const text = parts.filter(part => part.type === "text-delta").map(part => part.delta).join("");
  expect(text).toContain("## Critical context\nrun_browser_exact cursor_browser_exact");
  expect(text.match(/^## /gm)).toHaveLength(6);
});

test("Scripted recovery stops the original and distinguishes successful or failed replacements", async () => {
  const prompt = user("[scripted-context-recovery] Continue the research.");
  const original = await response([prompt]);
  expect(original.at(-1)).toMatchObject({ type: "finish", finishReason: { unified: "length" } });
  expect(original.some(part => part.type === "tool-input-delta")).toBe(true);
  const snapshot = { role: "system" as const, content: "## Goal\nScripted context checkpoint." };
  const replacement = await response([snapshot, prompt]);
  expect(replacement.at(-1)).toMatchObject({ type: "finish", finishReason: { unified: "stop" } });
  expect(replacement.some(part => part.type === "tool-call")).toBe(false);
  const failed = await response([snapshot, user("[scripted-context-recovery-fails] Continue the research.")]);
  expect(failed.at(-1)).toMatchObject({ type: "finish", finishReason: { unified: "length" } });
});

test("Scripted context batches retain distinct Core reads and exact continuation cursors", async () => {
  const model = new ScriptedLanguageModel("scripted-v1");
  const tools: NonNullable<LanguageModelV3CallOptions["tools"]> = ["get_research_context", "get_alpha_catalog"].map(name => ({ type: "function", name, inputSchema: { type: "object", properties: {} } }));
  const prompt: LanguageModelV3CallOptions["prompt"] = [user("[scripted-context-tool-batch] Read pages.")];
  const read = async () => {
    const result = await model.doStream({ prompt, tools });
    const reader = result.stream.getReader();
    const parts: LanguageModelV3StreamPart[] = [];
    for (;;) { const next = await reader.read(); if (next.done) break; parts.push(next.value); }
    return parts.filter(part => part.type === "tool-call");
  };
  const first = await read();
  expect(first.map(call => call.toolName)).toEqual(["get_research_context", "get_alpha_catalog"]);
  expect(new Set(first.map(call => call.toolCallId)).size).toBe(2);
  prompt.push({ role: "assistant", content: first.map(call => ({ type: "tool-call", toolCallId: call.toolCallId, toolName: call.toolName, input: {} })) });
  prompt.push({ role: "tool", content: first.map(call => ({ type: "tool-result", toolCallId: call.toolCallId, toolName: call.toolName,
    output: { type: "json", value: call.toolName === "get_research_context" ? { folders: { items: [], next_cursor: "folders-exact" } } : { fields: [], builtins: [], next_cursor: "catalog-exact" } } })) });
  expect((await read()).map(call => ({ name: call.toolName, input: JSON.parse(call.input) }))).toEqual([
    { name: "get_research_context", input: { folder_cursor: "folders-exact" } },
    { name: "get_alpha_catalog", input: { cursor: "catalog-exact" } },
  ]);
});

test("Scripted Observer can wait for an explicit Run cancellation without a timer", async () => {
  const cancellation = new AbortController();
  const model = new ScriptedLanguageModel("scripted-v1");
  const result = await model.doStream({ abortSignal: cancellation.signal, prompt: [
    { role: "system", content: "You are the memory consciousness" }, user("[scripted-observer-await-cancel] synthetic evidence"),
  ] });
  cancellation.abort();
  const reader = result.stream.getReader();
  expect((await reader.read()).value).toMatchObject({ type: "error" });
  expect((await reader.read()).done).toBe(true);
});
