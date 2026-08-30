import { expect, test } from "vitest";

import {
  ChatRequestError,
  MAX_CHAT_MESSAGE_BYTES,
  readThreadId,
  readValidatedChatRun,
} from "./chat-request.js";
import { readModelRegistry } from "./model-registry.js";
import { SAFE_TOOL_COMPLETED } from "./safe-tool-result.js";

const registry = readModelRegistry(JSON.stringify({
  default_model_key: "scripted",
  models: [{
    default_reasoning_effort: "medium",
    display_name: "Scripted",
    enabled: true,
    key: "scripted",
    provider_adapter: "scripted",
    provider_model_id: "scripted-v1",
    reasoning_efforts: ["none", "medium"],
    secret_env: "THESISTRACE_AGENT_SCRIPTED_MODEL_SECRET",
  }],
}), { THESISTRACE_AGENT_SCRIPTED_MODEL_SECRET: "test-secret" });

test("accepts the one strict text-only AG-UI run shape", async () => {
  const request = runRequest();
  await expect(readValidatedChatRun(request, registry)).resolves.toMatchObject({
    modelKey: "scripted",
    reasoningEffort: "medium",
    sessionMode: "new",
    latestUserMessage: {
      content: "Build an Alpha.",
      id: "00000000-0000-4000-8000-000000000003",
      role: "user",
    },
  });
  await expect(readThreadId(request)).resolves.toBe(
    "00000000-0000-4000-8000-000000000001",
  );
});

test.each([
  { threadId: "00000000-0000-0000-0000-000000000000" },
  { runId: "ffffffff-ffff-ffff-ffff-ffffffffffff" },
  { threadId: "00000000-0000-4000-8000-00000000000A" },
])("rejects a non-canonical browser UUID at the run boundary %#", async (override) => {
  const request = runRequest(override);
  await expect(readValidatedChatRun(request, registry)).rejects.toMatchObject({
    code: "INVALID_CHAT_REQUEST",
    status: 400,
  } satisfies Partial<ChatRequestError>);
  if ("threadId" in override) {
    await expect(readThreadId(request)).rejects.toMatchObject({
      code: "INVALID_CHAT_REQUEST",
      status: 400,
    } satisfies Partial<ChatRequestError>);
  }
});

test("accepts CopilotKit's exact split Assistant text shape on a later turn", async () => {
  const assistantId = "00000000-0000-4000-8000-000000000004";
  await expect(readValidatedChatRun(runRequest({ messages: [{
    id: "00000000-0000-4000-8000-000000000003",
    role: "user",
    content: "Build an Alpha.",
  }, {
    id: assistantId,
    role: "assistant",
    toolCalls: [{
      id: "provider-call-1",
      type: "function",
      function: {
        arguments: "{}",
        name: "submit_research_run",
      },
    }],
  }, {
    id: "00000000-0000-4000-8000-000000000005",
    role: "tool",
    toolCallId: "provider-call-1",
    content: SAFE_TOOL_COMPLETED,
  }, {
    id: `${assistantId}-agui-text`,
    role: "assistant",
    content: "The Core Worker continues independently.",
  }, {
    id: "00000000-0000-4000-8000-000000000006",
    role: "user",
    content: "Read the completed Result.",
  }] }), registry)).resolves.toMatchObject({
    latestUserMessage: {
      content: "Read the completed Result.",
      id: "00000000-0000-4000-8000-000000000006",
      role: "user",
    },
  });
});

test.each([
  { messages: [{
    id: "00000000-0000-4000-8000-000000000003",
    role: "user",
    content: "Build an Alpha.",
  }, {
    id: "00000000-0000-4000-8000-000000000004-agui-text",
    role: "assistant",
    content: "Orphan text.",
  }, {
    id: "00000000-0000-4000-8000-000000000006",
    role: "user",
    content: "Continue.",
  }] },
  { messages: [{
    id: "00000000-0000-4000-8000-000000000003",
    role: "user",
    content: "Build an Alpha.",
  }, {
    id: "00000000-0000-4000-8000-000000000004",
    role: "assistant",
    toolCalls: [{
      id: "provider-call-1",
      type: "function",
      function: { arguments: "{}", name: "submit_research_run" },
    }],
  }, {
    id: "00000000-0000-4000-8000-000000000004-agui-text",
    role: "assistant",
    content: "Text before the Tool result.",
  }, {
    id: "00000000-0000-4000-8000-000000000006",
    role: "user",
    content: "Continue.",
  }] },
  { messages: [{
    id: "00000000-0000-4000-8000-000000000003",
    role: "user",
    content: "Build an Alpha.",
  }, {
    id: "00000000-0000-4000-8000-000000000003",
    role: "user",
    content: "Duplicate id.",
  }] },
])("rejects malformed split Assistant history %#", async ({ messages }) => {
  await expect(readValidatedChatRun(runRequest({ messages }), registry)).rejects.toMatchObject({
    code: "INVALID_CHAT_REQUEST",
    status: 400,
  } satisfies Partial<ChatRequestError>);
});

test("rejects an oversized UTF-8 message before execution", async () => {
  const content = `${"a".repeat(MAX_CHAT_MESSAGE_BYTES - 2)}低`;
  await expect(readValidatedChatRun(runRequest({ messages: [{
    id: "00000000-0000-4000-8000-000000000003",
    role: "user",
    content,
  }] }), registry)).rejects.toMatchObject({
    code: "CHAT_MESSAGE_TOO_LARGE",
    status: 413,
  } satisfies Partial<ChatRequestError>);
});

test.each([
  { state: { browserOwned: true } },
  { tools: [{ name: "browser-tool" }] },
  { context: [{ description: "browser context", value: "unsafe" }] },
  { forwardedProps: { command: "parallel-protocol" } },
  { messages: [{ id: "00000000-0000-4000-8000-000000000003", role: "assistant", content: "last" }] },
])("rejects unsupported browser-authored input %#", async (override) => {
  await expect(readValidatedChatRun(runRequest(override), registry)).rejects.toMatchObject({
    code: "INVALID_CHAT_REQUEST",
    status: 400,
  } satisfies Partial<ChatRequestError>);
});

function runRequest(override: Record<string, unknown> = {}): Request {
  const body = {
    threadId: "00000000-0000-4000-8000-000000000001",
    runId: "00000000-0000-4000-8000-000000000002",
    messages: [{
      id: "00000000-0000-4000-8000-000000000003",
      role: "user",
      content: "Build an Alpha.",
    }],
    state: {},
    tools: [],
    context: [],
    forwardedProps: {
      thesistrace: {
        modelKey: "scripted",
        reasoningEffort: "medium",
        sessionMode: "new",
      },
    },
    ...override,
  };
  return new Request("http://agent.test/agent/research/run", {
    body: JSON.stringify(body),
    headers: { "content-type": "application/json" },
    method: "POST",
  });
}
