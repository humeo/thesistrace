import type { MastraAgentConfig } from "@ag-ui/mastra";
import type { RunAgentInput } from "@ag-ui/core";
import { RequestContext } from "@mastra/core/request-context";
import { lastValueFrom, toArray } from "rxjs";
import { afterEach, expect, test, vi } from "vitest";

import type { ValidatedChatRun } from "./chat-request.js";
import type { McpRun } from "./mcp-run.js";
import { ResearchMastraAgent } from "./research-mastra-agent.js";
import {
  SAFE_TOOL_COMPLETED,
  SAFE_TOOL_FAILED,
} from "./safe-tool-result.js";
import type {
  PreparedRun,
  ResearchSessionRepository,
} from "./session-repository.js";

afterEach(() => {
  vi.useRealTimers();
});

test("subscriber disposal terminates a new Run whose preparation is still pending", async () => {
  const preparationStarted = deferred<void>();
  const prepared = deferred<PreparedRun>();
  const failurePersisted = deferred<void>();
  const mcpRun = vi.fn(async () => ({
    close: vi.fn(async () => undefined),
    hasFatalToolFailure: () => false,
    toolFailure: () => undefined,
    tools: {},
  }));
  const { agent, input, repository } = testAgent({
    mcpRun,
    prepareRun: async () => {
      preparationStarted.resolve();
      return prepared.promise;
    },
    runMaxWallMs: 1_000,
  });
  repository.markFailed.mockImplementation(async () => {
    failurePersisted.resolve();
    return undefined;
  });
  const subscription = agent.run(input).subscribe();

  await preparationStarted.promise;
  subscription.unsubscribe();
  prepared.resolve({
    durableMessages: [],
    generateTitle: false,
    kind: "new",
    status: "running",
  });
  await failurePersisted.promise;

  expect(repository.markFailed).toHaveBeenCalledOnce();
  await vi.waitFor(() => {
    expect(repository.awaitFrameworkRunSettled).toHaveBeenCalledOnce();
  });
  expect(mcpRun).not.toHaveBeenCalled();
});

test("subscriber disposal closes an MCP client that is still being prepared", async () => {
  const mcpStarted = deferred<void>();
  const mcpPrepared = deferred<McpRun>();
  const disconnected = deferred<void>();
  const close = vi.fn(async () => disconnected.resolve());
  const { agent, input, requestContext, repository } = testAgent({
    mcpRun: async () => {
      mcpStarted.resolve();
      return mcpPrepared.promise;
    },
    runMaxWallMs: 1_000,
  });
  const events: unknown[] = [];
  const subscription = agent.run(input).subscribe({
    error: (error) => events.push(error),
    next: (event) => events.push(event),
  });

  await mcpStarted.promise;
  subscription.unsubscribe();
  mcpPrepared.resolve({
    close,
    hasFatalToolFailure: () => false,
    toolFailure: () => undefined,
    tools: {},
  });
  await disconnected.promise;

  expect(close).toHaveBeenCalledOnce();
  expect(requestContext.get("mcpTools")).toEqual({});
  expect(repository.markCompleted).not.toHaveBeenCalled();
  await vi.waitFor(() => {
    expect(repository.markFailed).toHaveBeenCalledOnce();
    expect(repository.awaitFrameworkRunSettled).toHaveBeenCalledOnce();
  });
  expect(JSON.stringify(events)).not.toContain("AGENT_RUN_DISPOSED");
});

test("the total Run timeout persists failure and awaits MCP disconnect", async () => {
  vi.useFakeTimers();
  const streamStarted = deferred<void>();
  const close = vi.fn(async () => undefined);
  const { agent, input, repository } = testAgent({
    agentStream: async () => {
      streamStarted.resolve();
      return new Promise<never>(() => undefined);
    },
    mcpRun: async () => ({
      close,
      hasFatalToolFailure: () => false,
      toolFailure: () => undefined,
      tools: {},
    }),
    runMaxWallMs: 25,
  });
  const result = lastValueFrom(agent.run(input).pipe(toArray()));

  await streamStarted.promise;
  await vi.advanceTimersByTimeAsync(25);
  const events = await result;

  expect(events.map((event) => event.type)).toEqual(["RUN_STARTED", "RUN_ERROR"]);
  expect(events.at(-1)).toMatchObject({
    code: "AGENT_RUN_FAILED",
    message: "The Research Agent could not complete this run.",
  });
  expect(repository.markFailed).toHaveBeenCalledOnce();
  expect(repository.awaitFrameworkRunSettled).toHaveBeenCalledOnce();
  expect(close).toHaveBeenCalledOnce();
});

test("one MCP Tool failure terminates the Run before later model output", async () => {
  const close = vi.fn(async () => undefined);
  const { agent, input, repository } = testAgent({
    agentStream: async () => ({
      processDataStream: async ({
        onChunk,
      }: {
        onChunk: (chunk: unknown) => Promise<void>;
      }) => {
        await onChunk({
          payload: {
            args: {},
            toolCallId: "provider-tool-call-1",
            toolName: "get_research_context",
          },
          type: "tool-call",
        });
        await onChunk({
          payload: {
            result: { error: "raw transport failure with result-canary" },
            toolCallId: "provider-tool-call-1",
          },
          type: "tool-result",
        });
        await onChunk({
          payload: { text: "This explanation must not reach the browser." },
          type: "text-delta",
        });
      },
    }),
    mcpRun: async () => ({
      close,
      hasFatalToolFailure: () => true,
      toolFailure: (toolCallId) => (
        toolCallId === "provider-tool-call-1" ? "transport" : undefined
      ),
      tools: {},
    }),
    runMaxWallMs: 1_000,
  });

  const events = await lastValueFrom(agent.run(input).pipe(toArray()));

  expect(events.map((event) => event.type)).toEqual([
    "RUN_STARTED",
    "TOOL_CALL_START",
    "TOOL_CALL_ARGS",
    "TOOL_CALL_END",
    "TOOL_CALL_RESULT",
    "RUN_ERROR",
  ]);
  expect(events.find((event) => event.type === "TOOL_CALL_RESULT")).toMatchObject({
    content: SAFE_TOOL_FAILED,
  });
  expect(JSON.stringify(events)).not.toContain("result-canary");
  expect(JSON.stringify(events)).not.toContain("must not reach");
  expect(repository.markCompleted).not.toHaveBeenCalled();
  expect(repository.markFailed).toHaveBeenCalledOnce();
  expect(repository.awaitDurableToolResult).toHaveBeenCalledWith(
    input.threadId,
    "00000000-0000-4000-8000-000000000010",
    "provider-tool-call-1",
  );
  expect(close).toHaveBeenCalledOnce();
});

test("cancellation drains the bridge reader even after the browser terminal failure", async () => {
  const streaming = deferred<void>();
  const drained = deferred<void>();
  let tailCompleted = false;
  const { agent, input, pendingBridges } = testAgent({
    agentStream: async () => ({
      processDataStream: async () => {
        streaming.resolve();
        await drained.promise;
        tailCompleted = true;
      },
    }),
    mcpRun: async () => ({
      close: async () => undefined,
      hasFatalToolFailure: () => false,
      toolFailure: () => undefined,
      tools: {},
    }),
    runMaxWallMs: 1_000,
  });
  const result = lastValueFrom(agent.run(input).pipe(toArray()));
  await streaming.promise;
  agent.abortRun();
  expect((await result).at(-1)?.type).toBe("RUN_ERROR");
  expect(tailCompleted).toBe(false);
  expect(pendingBridges.size).toBe(1);
  const settled = Promise.all(pendingBridges);
  drained.resolve();
  await settled;
  expect(tailCompleted).toBe(true);
  expect(pendingBridges.size).toBe(0);
});

test("a Core business rejection is a failed Tool but the Agent Run may continue", async () => {
  const close = vi.fn(async () => undefined);
  const { agent, input, repository } = testAgent({
    agentStream: async () => ({
      processDataStream: async ({
        onChunk,
      }: {
        onChunk: (chunk: unknown) => Promise<void>;
      }) => {
        await onChunk({
          payload: {
            args: {},
            toolCallId: "business-call",
            toolName: "get_research_context",
          },
          type: "tool-call",
        });
        await onChunk({
          payload: {
            result: { code: "TEMPORARILY_UNAVAILABLE" },
            toolCallId: "business-call",
          },
          type: "tool-result",
        });
        await onChunk({
          payload: { text: "The Agent can revise its research request." },
          type: "text-delta",
        });
      },
    }),
    mcpRun: async () => ({
      close,
      hasFatalToolFailure: () => false,
      toolFailure: (toolCallId) => (
        toolCallId === "business-call" ? "business" : undefined
      ),
      tools: {},
    }),
    runMaxWallMs: 1_000,
  });

  const events = await lastValueFrom(agent.run(input).pipe(toArray()));

  expect(events.map((event) => event.type)).toEqual([
    "RUN_STARTED",
    "TOOL_CALL_START",
    "TOOL_CALL_ARGS",
    "TOOL_CALL_END",
    "TOOL_CALL_RESULT",
    "TEXT_MESSAGE_CHUNK",
    "RUN_FINISHED",
  ]);
  expect(events.find((event) => event.type === "TOOL_CALL_RESULT")).toMatchObject({
    content: SAFE_TOOL_FAILED,
    toolCallId: "business-call",
  });
  expect(repository.markFailed).not.toHaveBeenCalled();
  expect(repository.awaitDurableToolResult).not.toHaveBeenCalled();
  expect(repository.markCompleted).toHaveBeenCalledOnce();
  expect(close).toHaveBeenCalledOnce();
});

test("parallel Tool results cannot transfer one call's transport failure to another", async () => {
  const close = vi.fn(async () => undefined);
  const { agent, input, repository } = testAgent({
    agentStream: async () => ({
      processDataStream: async ({
        onChunk,
      }: {
        onChunk: (chunk: unknown) => Promise<void>;
      }) => {
        for (const toolCallId of ["successful-call", "failed-call"]) {
          await onChunk({
            payload: {
              args: {},
              toolCallId,
              toolName: "get_research_context",
            },
            type: "tool-call",
          });
        }
        await onChunk({
          payload: { result: { status: "ok" }, toolCallId: "successful-call" },
          type: "tool-result",
        });
        await onChunk({
          payload: { result: { isError: true }, toolCallId: "failed-call" },
          type: "tool-result",
        });
        await onChunk({
          payload: { text: "This must be discarded." },
          type: "text-delta",
        });
      },
    }),
    mcpRun: async () => ({
      close,
      hasFatalToolFailure: () => true,
      toolFailure: (toolCallId) => (
        toolCallId === "failed-call" ? "transport" : undefined
      ),
      tools: {},
    }),
    runMaxWallMs: 1_000,
  });

  const events = await lastValueFrom(agent.run(input).pipe(toArray()));
  const results = events.filter((event) => event.type === "TOOL_CALL_RESULT");

  expect(results).toEqual([
    expect.objectContaining({
      content: SAFE_TOOL_COMPLETED,
      toolCallId: "successful-call",
    }),
    expect.objectContaining({
      content: SAFE_TOOL_FAILED,
      toolCallId: "failed-call",
    }),
  ]);
  expect(events.at(-1)?.type).toBe("RUN_ERROR");
  expect(JSON.stringify(events)).not.toContain("must be discarded");
  expect(repository.awaitDurableToolResult).toHaveBeenCalledWith(
    input.threadId,
    "00000000-0000-4000-8000-000000000010",
    "failed-call",
  );
  expect(repository.markCompleted).not.toHaveBeenCalled();
});

test("a newly accepted Untitled session schedules title generation once", async () => {
  const { agent, input, scheduleTitle } = testAgent({
    agentStream: async () => ({
      processDataStream: async ({
        onChunk,
      }: {
        onChunk: (chunk: unknown) => Promise<void>;
      }) => {
        await onChunk({ payload: { text: "A research response." }, type: "text-delta" });
      },
    }),
    mcpRun: async () => ({
      close: async () => undefined,
      hasFatalToolFailure: () => false,
      toolFailure: () => undefined,
      tools: {},
    }),
    prepareRun: async () => ({
      durableMessages: [],
      generateTitle: true,
      kind: "new",
      status: "running",
    }),
    runMaxWallMs: 1_000,
  });

  await lastValueFrom(agent.run(input).pipe(toArray()));

  expect(scheduleTitle).toHaveBeenCalledOnce();
});

test("a slow title never delays the terminal event or Runner release", async () => {
  vi.useFakeTimers();
  const { agent, input, repository, scheduleTitle } = testAgent({
    agentStream: async () => ({
      processDataStream: async ({
        onChunk,
      }: {
        onChunk: (chunk: unknown) => Promise<void>;
      }) => {
        await onChunk({ payload: { text: "A research response." }, type: "text-delta" });
      },
    }),
    mcpRun: async () => ({
      close: async () => undefined,
      hasFatalToolFailure: () => false,
      toolFailure: () => undefined,
      tools: {},
    }),
    prepareRun: async () => ({
      durableMessages: [],
      generateTitle: true,
      kind: "new",
      status: "running",
    }),
    runMaxWallMs: 50,
  });
  let titleCompleted = false;
  scheduleTitle.mockImplementation(async () => {
    await new Promise<void>((resolve) => setTimeout(resolve, 100));
    titleCompleted = true;
  });

  const events = await lastValueFrom(agent.run(input).pipe(toArray()));

  expect(repository.markCompleted).toHaveBeenCalledOnce();
  expect(repository.markFailed).not.toHaveBeenCalled();
  expect(events.map((event) => event.type)).toEqual([
    "RUN_STARTED",
    "TEXT_MESSAGE_CHUNK",
    "RUN_FINISHED",
  ]);
  expect(titleCompleted).toBe(false);
  expect(repository.markFailed).not.toHaveBeenCalled();
  expect(scheduleTitle).toHaveBeenCalledOnce();

  await vi.advanceTimersByTimeAsync(100);
  expect(titleCompleted).toBe(true);
});

function testAgent(options: Readonly<{
  agentStream?: () => Promise<unknown>;
  mcpRun: () => Promise<McpRun>;
  prepareRun?: () => Promise<PreparedRun>;
  runMaxWallMs: number;
}>) {
  const input: RunAgentInput = {
    context: [],
    forwardedProps: {},
    messages: [{
      content: "Inspect the current research context.",
      id: "00000000-0000-4000-8000-000000000003",
      role: "user",
    }],
    runId: "00000000-0000-4000-8000-000000000002",
    state: {},
    threadId: "00000000-0000-4000-8000-000000000001",
    tools: [],
  };
  const run: ValidatedChatRun = {
    input,
    latestUserMessage: {
      content: "Inspect the current research context.",
      id: "00000000-0000-4000-8000-000000000003",
      role: "user",
    },
    modelKey: "scripted",
    reasoningEffort: "medium",
    sessionMode: "new",
  };
  const repository = {
    awaitDurableToolResult: vi.fn(async () => undefined),
    awaitFrameworkRunSettled: vi.fn(async () => undefined),
    markCompleted: vi.fn(async () => undefined),
    markFailed: vi.fn(async () => undefined),
    prepareRun: vi.fn(options.prepareRun ?? (async () => ({
      durableMessages: [],
      generateTitle: false,
      kind: "new" as const,
      status: "running" as const,
    }))),
  };
  const requestContext = new RequestContext();
  const bridgeConfig = {
    agent: {
      stream: options.agentStream ?? (async () => new Promise<never>(() => undefined)),
    },
    agentId: "research",
    requestContext,
    resourceId: "00000000-0000-4000-8000-000000000010",
  } as unknown as MastraAgentConfig;
  const scheduleTitle = vi.fn(async () => undefined);
  const pendingBridges = new Set<Promise<void>>();
  const agent = new ResearchMastraAgent(bridgeConfig, {
    agentBuildRevision: "test-build",
    mcpRun: options.mcpRun,
    pendingBridges,
    providerModelId: "scripted-v1",
    repository: repository as unknown as ResearchSessionRepository,
    requestContext,
    researcherId: "00000000-0000-4000-8000-000000000010",
    run,
    runMaxWallMs: options.runMaxWallMs,
    scheduleTitle,
    usage: () => undefined,
  });
  return { agent, input, pendingBridges, repository, requestContext, scheduleTitle };
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((selected) => {
    resolve = selected;
  });
  return { promise, resolve };
}
