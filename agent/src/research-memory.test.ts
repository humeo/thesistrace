import { MessageList, type MastraDBMessage } from "@mastra/core/agent";
import { InMemoryStore } from "@mastra/core/storage";
import { Memory } from "@mastra/memory";
import { expect, test } from "vitest";

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
