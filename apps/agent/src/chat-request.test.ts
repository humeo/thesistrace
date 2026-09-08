import { expect, test } from "vitest";

import {
  ChatRequestError,
  MAX_CHAT_MESSAGE_BYTES,
  readThreadId,
  readValidatedChatRun,
} from "./chat-request.js";
import { readModelRegistry } from "./model-registry.js";

const THREAD_ID = "00000000-0000-4000-8000-000000000001";
const RUN_ID = "00000000-0000-4000-8000-000000000002";
const INPUT_ID = "00000000-0000-4000-8000-000000000003";
const INTERRUPT_ID = `${RUN_ID}::provider-call-1`;

const registry = readModelRegistry(JSON.stringify({
  min_compaction_context_window: 65_536, default_model_key: "scripted",
  models: [{
    default_reasoning_effort: "medium",
    display_name: "Scripted",
    enabled: true,
    key: "scripted",
    provider_adapter: "scripted",
    provider_model_id: "scripted-v1",
    reasoning_efforts: ["none", "medium"],
    context_window: 65_536, max_output_tokens: 128_000, pricing_usd_per_million_tokens: { input: 0, cache_read: 0, cache_write: 0, output: 0 }, secret_env: "THESISTRACE_AGENT_SCRIPTED_MODEL_SECRET",
  }],
}), { THESISTRACE_AGENT_SCRIPTED_MODEL_SECRET: "test-secret" });

test("accepts one strict Prompt containing only the new User input", async () => {
  const request = runRequest();
  await expect(readValidatedChatRun(request, registry)).resolves.toMatchObject({
    command: "prompt",
    commandId: INPUT_ID,
    modelKey: "scripted",
    reasoningEffort: "medium",
    sessionMode: "new",
    userMessage: { content: "Build an Alpha.", id: INPUT_ID, role: "user" },
  });
  await expect(readThreadId(request)).resolves.toBe(THREAD_ID);
});

test("accepts Continue only as an empty-message new Run", async () => {
  await expect(readValidatedChatRun(runRequest({
    messages: [],
    forwardedProps: {
      thesistrace: {
        command: "continue",
        modelKey: "scripted",
        reasoningEffort: "medium",
        sessionMode: "existing",
      },
    },
  }), registry)).resolves.toMatchObject({
    command: "continue",
    commandId: RUN_ID,
    sessionMode: "existing",
  });
});

test.each([
  { selections: [], text: "A focused answer" },
  { selections: ["Quality", "Low volatility"], text: "" },
  { selections: ["Quality"], text: "Keep turnover low." },
])("accepts Answer as the sole resolved interrupt payload %#", async (answer) => {
  await expect(readValidatedChatRun(runRequest({
    messages: [],
    resume: [{ interruptId: INTERRUPT_ID, payload: answer, status: "resolved" }],
    forwardedProps: {
      thesistrace: { command: "answer", inputId: INPUT_ID, interruptId: INTERRUPT_ID },
    },
  }), registry)).resolves.toMatchObject({
    answer,
    command: "answer",
    commandId: INPUT_ID,
    interruptId: INTERRUPT_ID,
  });
});

test.each([
  "Legacy answer", ["Quality"], {}, { selections: [], text: "  " },
  { selections: ["Quality", "Quality"], text: "" },
  { selections: [""], text: "A note" },
  { selections: ["界".repeat(67)], text: "" },
  { selections: [], text: "Answer", modelKey: "scripted" },
])("rejects invalid or legacy Answer payloads %#", async (payload) => {
  await expect(readValidatedChatRun(runRequest({
    messages: [],
    resume: [{ interruptId: INTERRUPT_ID, payload, status: "resolved" }],
    forwardedProps: { thesistrace: { command: "answer", inputId: INPUT_ID, interruptId: INTERRUPT_ID } },
  }), registry)).rejects.toMatchObject({ code: "INVALID_CHAT_INPUT", status: 400 });
});

test("bounds the combined UTF-8 answer, including selected options", async () => {
  await expect(readValidatedChatRun(runRequest({
    messages: [],
    resume: [{ interruptId: INTERRUPT_ID, payload: {
      selections: ["Quality"], text: "界".repeat(Math.floor(MAX_CHAT_MESSAGE_BYTES / 3)),
    }, status: "resolved" }],
    forwardedProps: { thesistrace: { command: "answer", inputId: INPUT_ID, interruptId: INTERRUPT_ID } },
  }), registry)).rejects.toMatchObject({ code: "CHAT_INPUT_TOO_LARGE", status: 413 });
});

test.each([
  ["missing", "medium", "INVALID_MODEL"],
  ["scripted", "high", "UNSUPPORTED_REASONING"],
])("distinguishes rejected next-Turn settings %s / %s", async (modelKey, reasoningEffort, code) => {
  await expect(readValidatedChatRun(runRequest({
    forwardedProps: {
      thesistrace: { command: "prompt", modelKey, reasoningEffort, sessionMode: "new" },
    },
  }), registry)).rejects.toMatchObject({ code, status: 400 });
});

test.each([
  { messages: [] },
  { messages: [userMessage(), userMessage("00000000-0000-4000-8000-000000000004")] },
  { state: { browserOwned: true } },
  { tools: [{ name: "browser-tool" }] },
  { context: [{ description: "browser context", value: "unsafe" }] },
  { resume: [{ interruptId: INTERRUPT_ID, payload: "answer", status: "resolved" }] },
])("rejects unsupported Prompt input %#", async (override) => {
  await expect(readValidatedChatRun(runRequest(override), registry)).rejects.toMatchObject({
    code: "INVALID_CHAT_INPUT",
    status: 400,
  } satisfies Partial<ChatRequestError>);
});

test("rejects old browser transcript replay instead of accepting a compatibility path", async () => {
  await expect(readValidatedChatRun(runRequest({
    messages: [
      userMessage("00000000-0000-4000-8000-000000000004"),
      { content: "Prior answer", id: "00000000-0000-4000-8000-000000000005", role: "assistant" },
      userMessage(),
    ],
  }), registry)).rejects.toMatchObject({ code: "INVALID_CHAT_INPUT", status: 400 });
});

test.each([
  {
    forwardedProps: {
      thesistrace: {
        command: "answer",
        inputId: INPUT_ID,
        interruptId: INTERRUPT_ID,
        modelKey: "scripted",
      },
    },
    messages: [],
    resume: [{ interruptId: INTERRUPT_ID, payload: "answer", status: "resolved" }],
  },
  {
    forwardedProps: {
      thesistrace: { command: "answer", inputId: INPUT_ID, interruptId: INTERRUPT_ID },
    },
    messages: [],
    resume: [{ interruptId: "wrong", payload: "answer", status: "resolved" }],
  },
  {
    forwardedProps: {
      thesistrace: { command: "continue", modelKey: "scripted", reasoningEffort: "medium", sessionMode: "existing" },
    },
    messages: [userMessage()],
  },
])("rejects a command that smuggles another command's fields %#", async (override) => {
  await expect(readValidatedChatRun(runRequest(override), registry)).rejects.toMatchObject({
    code: "INVALID_CHAT_INPUT",
    status: 400,
  });
});

test("rejects an oversized UTF-8 Prompt before execution", async () => {
  const content = `${"a".repeat(MAX_CHAT_MESSAGE_BYTES - 2)}低`;
  await expect(readValidatedChatRun(runRequest({ messages: [userMessage(INPUT_ID, content)] }), registry))
    .rejects.toMatchObject({ code: "CHAT_INPUT_TOO_LARGE", status: 413 });
});

test.each([
  { threadId: "00000000-0000-0000-0000-000000000000" },
  { runId: "ffffffff-ffff-ffff-ffff-ffffffffffff" },
  { messages: [userMessage("00000000-0000-4000-8000-00000000000A")] },
])("rejects non-canonical identities %#", async (override) => {
  await expect(readValidatedChatRun(runRequest(override), registry)).rejects.toMatchObject({
    code: "INVALID_CHAT_INPUT",
    status: 400,
  });
});

function userMessage(id = INPUT_ID, content = "Build an Alpha.") {
  return { content, id, role: "user" };
}

function runRequest(override: Record<string, unknown> = {}): Request {
  const body = {
    context: [],
    forwardedProps: {
      thesistrace: {
        command: "prompt",
        modelKey: "scripted",
        reasoningEffort: "medium",
        sessionMode: "new",
      },
    },
    messages: [userMessage()],
    runId: RUN_ID,
    state: {},
    threadId: THREAD_ID,
    tools: [],
    ...override,
  };
  return new Request("http://agent.test/agent/research/run", {
    body: JSON.stringify(body),
    headers: { "content-type": "application/json" },
    method: "POST",
  });
}
