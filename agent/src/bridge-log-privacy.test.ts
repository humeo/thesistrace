import { MastraAgent, type MastraAgentConfig } from "@ag-ui/mastra";
import type { RunAgentInput } from "@ag-ui/core";
import { lastValueFrom, toArray } from "rxjs";
import { expect, test, vi } from "vitest";

// Exercise the installed bridge through its public run API. These failures
// used to bypass Mastra's noopLogger and print raw storage/provider errors.
test.each(["recall", "working-memory", "tool-list", "trace", "chunk"])(
  "the native bridge does not log private %s values",
  async (failure) => {
    const canary = `bridge-private-${failure}-719e6e46`;
    const writes: unknown[][] = [];
    const spies = ["warn", "error", "log", "info", "debug"].map((method) =>
      vi.spyOn(console, method as "warn").mockImplementation((...values: unknown[]) => { writes.push(values); }),
    );
    const fail = () => { throw new Error(canary); };
    const agent = new MastraAgent({
      agentId: "research",
      resourceId: "00000000-0000-4000-8000-000000000010",
      agent: {
        getMemory: async () => ({
          recall: async () => failure === "recall" ? fail() : { messages: [] },
          getWorkingMemory: async () => failure === "working-memory" ? fail() : null,
        }),
        listTools: async () => failure === "tool-list" ? fail() : {},
        stream: async () => ({
          get traceId() { return failure === "trace" ? Promise.reject(new Error(canary)) : undefined; },
          fullStream: new ReadableStream({ start(controller) {
            if (failure === "chunk") controller.enqueue({ type: canary });
            controller.close();
          } }),
        }),
      },
    } as unknown as MastraAgentConfig);
    const input: RunAgentInput = {
      threadId: "00000000-0000-4000-8000-000000000001",
      runId: "00000000-0000-4000-8000-000000000002",
      messages: [{ id: "00000000-0000-4000-8000-000000000003", role: "user", content: canary }],
      state: {}, tools: [], context: [], forwardedProps: {},
    };
    try {
      const events = await lastValueFrom(agent.run(input).pipe(toArray()));
      expect(events.at(-1)?.type).toBe("RUN_FINISHED");
      // Failure output must not itself echo the canary or raw exception.
      expect(writes.length, "native bridge emitted a content-bearing log").toBe(0);
    } finally { for (const spy of spies) spy.mockRestore(); }
  },
);
