import { MessageList, type MastraDBMessage } from "@mastra/core/agent";
import { InMemoryStore } from "@mastra/core/storage";
import { Memory } from "@mastra/memory";
import { expect, test } from "vitest";
import { createResearchMemory } from "./research-memory.js";

test("raw Session history never starts a native observation engine", async () => {
  const memory = createResearchMemory(new InMemoryStore());
  expect(await memory.omEngine).toBeNull();
});

test("native observation context preserves a resumed Tool result over its stored pending call", async () => {
  const storage = new InMemoryStore();
  const memory = new Memory({ storage, options: {
    observationalMemory: { model: "openai/fixture", observation: { bufferTokens: false } },
  } });
  await memory.createThread({ threadId: "session", resourceId: "researcher" });
  const pending: MastraDBMessage = {
    id: "question", role: "assistant", threadId: "session", resourceId: "researcher",
    createdAt: new Date("2026-09-06T00:00:01.000Z"),
    content: { format: 2, parts: [{ type: "tool-invocation", toolInvocation: {
      state: "call", toolCallId: "ask-objective", toolName: "ask_user", args: { question: "Choose the objective" },
    } }] },
  };
  await memory.saveMessages({ messages: [structuredClone(pending)] });
  const resolved = structuredClone(pending);
  resolved.createdAt = new Date("2026-09-06T00:00:00.999Z");
  resolved.content.parts = [{ type: "tool-invocation", toolInvocation: {
    state: "result", toolCallId: "ask-objective", toolName: "ask_user",
    args: { question: "Choose the objective" }, result: "Quality, with low turnover",
  } }];
  const messageList = new MessageList({ threadId: "session", resourceId: "researcher" }).add(resolved, "response");
  const engine = (await memory.omEngine)!;
  const turn = engine.beginTurn({ threadId: "session", resourceId: "researcher", messageList });
  await turn.start(memory);
  expect(messageList.get.all.db()[0]?.content.parts).toMatchObject([{ toolInvocation: {
    state: "result", result: "Quality, with low turnover",
  } }]);
  await turn.end();
  await memory.settled();
});

test("small-window input retains more than fifty messages and the latest resumed result", async () => {
  const memory = createResearchMemory(new InMemoryStore());
  await memory.createThread({ threadId: "long-session", resourceId: "owner" });
  const history: MastraDBMessage[] = Array.from({ length: 72 }, (_, i) => ({
    id: `message-${i}`, threadId: "long-session", resourceId: "owner", role: i % 2 === 0 ? "user" : "assistant",
    createdAt: new Date(Date.UTC(2026, 8, 7, 0, 0, i)), content: { format: 2, parts: [{ type: "text", text: `Fact ${i}` }] },
  }));
  await memory.saveMessages({ messages: structuredClone(history) });
  const current = structuredClone(history[71]!);
  current.content.parts = [{ type: "text", text: "Most recent resolved response" }];
  const list = new MessageList({ threadId: "long-session", resourceId: "owner" }).add(current, "response");
  for (const processor of await memory.getInputProcessors()) {
    if ("processInput" in processor && processor.processInput) await processor.processInput({
      messageList: list, messages: list.get.all.db(), systemMessages: [], state: {}, retryCount: 0, abort: () => { throw new Error("unexpected abort"); },
    });
  }
  expect(list.get.all.db().map((message) => message.id)).toEqual(history.map((message) => message.id));
  expect(list.get.all.db().at(-1)?.content.parts).toEqual(current.content.parts);
  expect(await memory.omEngine).toBeNull();
});
