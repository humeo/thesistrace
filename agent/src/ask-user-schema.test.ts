import { createRequire } from "node:module";

import { createOpenAI } from "@ai-sdk/openai";
import { Agent } from "@mastra/core/agent";
import { noopLogger } from "@mastra/core/logger";
import { askUserTool, createTool } from "@mastra/core/tools";
import { Ajv } from "ajv";
import { expect, test } from "vitest";
import { z } from "zod";

import { openAIToolProvider } from "../test-fixtures/openai-tool-provider.js";

const question = "Which research objective should lead?";
const options = [{ label: "Quality", description: null }, { label: "Risk", description: null }];

test.each([
  { name: "free-text", args: { question, options: null, selectionMode: null }, payload: { question } },
  { name: "single-select", args: { question, options, selectionMode: "single_select" },
    payload: { question, options: [{ label: "Quality" }, { label: "Risk" }], selectionMode: "single_select" } },
  { name: "multi-select", args: { question, options, selectionMode: "multi_select" },
    payload: { question, options: [{ label: "Quality" }, { label: "Risk" }], selectionMode: "multi_select" } },
])("the provider schema and native ask_user both accept $name", async ({ args, payload }) => {
  const provider = openAIToolProvider([{ name: "ask_user", arguments: args }]);
  const agent = new Agent({
    id: "ask-user-schema", name: "Ask user schema", instructions: "Ask the user before proceeding.",
    model: createOpenAI({ apiKey: "fixture-only", fetch: provider.fetch })("gpt-5.6-luna"),
    tools: { ask_user: askUserTool }, maxRetries: 0,
  });
  agent.__setLogger(noopLogger);
  const stream = await agent.stream("Ask me a question.", { maxSteps: 2 });
  const events = [];
  for await (const event of stream.fullStream) events.push(event);
  expect(provider.schemaErrors).toEqual([]);
  expect(events.filter((event) => event.type === "tool-call-suspended"))
    .toMatchObject([{ payload: { toolName: "ask_user", suspendPayload: payload } }]);
  expect(events.filter((event) => event.type === "tool-error" || event.type === "error")).toEqual([]);
});

test.each([null, []])("a selection with %s options remains a tool error the model can correct", async (invalidOptions) => {
  const provider = openAIToolProvider([
    { name: "ask_user", arguments: { question, options: invalidOptions, selectionMode: "single_select" } },
    { name: "ask_user", arguments: { question, options: null, selectionMode: null } },
  ]);
  const agent = new Agent({
    id: "ask-user-repair", name: "Ask user repair", instructions: "Correct invalid tool arguments.",
    model: createOpenAI({ apiKey: "fixture-only", fetch: provider.fetch })("gpt-5.6-luna"),
    tools: { ask_user: askUserTool }, maxRetries: 0,
  });
  agent.__setLogger(noopLogger);
  const stream = await agent.stream("Ask me a question.", { maxSteps: 3 });
  const events = [];
  for await (const event of stream.fullStream) events.push(event);
  expect(events.filter((event) => event.type === "tool-result"))
    .toMatchObject([{ payload: { result: { isError: true, content: "Failed to ask user: selectionMode requires options." } } }]);
  expect(provider.schemaErrors).toEqual([]);
  expect(provider.requests[1]?.input).toContainEqual(expect.objectContaining({
    type: "function_call_output", output: expect.stringContaining("selectionMode requires options"),
  }));
  expect(events.filter((event) => event.type === "tool-call-suspended"))
    .toMatchObject([{ payload: { suspendPayload: { question } } }]);
});

test.each(["esm", "commonjs"])("%s schema conversion preserves optional enum/literal nulls and required values", async (format) => {
  const require = createRequire(import.meta.url);
  const { Agent: NativeAgent } = format === "esm" ? { Agent }
    : require("@mastra/core/agent") as typeof import("@mastra/core/agent");
  const { createTool: nativeTool } = format === "esm" ? { createTool }
    : require("@mastra/core/tools") as typeof import("@mastra/core/tools");
  const provider = openAIToolProvider([{ name: "choice", arguments: { optionalEnum: null, optionalLiteral: null, requiredEnum: "high" } }]);
  const agent = new NativeAgent({
    id: "nullable-choice", name: "Nullable choice", instructions: "Choose a value.", maxRetries: 0,
    model: createOpenAI({ apiKey: "fixture-only", fetch: provider.fetch })("gpt-5.6-luna"),
    tools: { choice: nativeTool({
      id: "choice", description: "Choose typed values.", inputSchema: z.object({
        optionalEnum: z.enum(["single", "multi"]).optional(),
        optionalLiteral: z.literal("known").optional(), requiredEnum: z.enum(["high", "low"]),
      }), execute: async (input) => input,
    }) },
  });
  agent.__setLogger(noopLogger);
  const stream = await agent.stream("Choose a value.", { maxSteps: 2 });
  const events = [];
  for await (const event of stream.fullStream) events.push(event);
  expect(provider.schemaErrors).toEqual([]);
  expect(events.filter((event) => event.type === "tool-result"))
    .toMatchObject([{ payload: { result: { requiredEnum: "high" } } }]);
  const schema = provider.requests[0]?.tools?.find((tool) => tool.name === "choice")?.parameters;
  expect(schema).toBeDefined();
  const validate = new Ajv({ strict: false }).compile(schema!);
  expect(validate({ optionalEnum: "single", optionalLiteral: "known", requiredEnum: "high" })).toBe(true);
  expect(validate({ optionalEnum: "unknown", optionalLiteral: "known", requiredEnum: "high" })).toBe(false);
  expect(validate({ optionalEnum: null, optionalLiteral: "unknown", requiredEnum: "high" })).toBe(false);
  expect(validate({ optionalEnum: null, optionalLiteral: null, requiredEnum: null })).toBe(false);
});
