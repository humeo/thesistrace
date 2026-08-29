import { expect, test } from "vitest";

import {
  ChatRequestError,
  MAX_CHAT_MESSAGE_BYTES,
  readThreadId,
  readValidatedChatRun,
} from "./chat-request.js";
import { readModelRegistry } from "./model-registry.js";

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
      thesistrace: { modelKey: "scripted", reasoningEffort: "medium" },
    },
    ...override,
  };
  return new Request("http://agent.test/agent/research/run", {
    body: JSON.stringify(body),
    headers: { "content-type": "application/json" },
    method: "POST",
  });
}
