import { randomUUID } from "node:crypto";

import { AbstractAgent, verifyEvents } from "@ag-ui/client";
import { EventType, type BaseEvent, type RunAgentInput } from "@ag-ui/core";
import { firstValueFrom, Subject, toArray } from "rxjs";
import { describe, expect, it, vi } from "vitest";

import {
  RESEARCH_A2UI_ACTIVITY_TYPE,
  RESEARCH_A2UI_CATALOG_ID,
  RESEARCH_A2UI_PROTOCOL_VERSION,
} from "../../contracts/research-a2ui.mjs";
import { DurableResearchAgentRunner } from "./durable-agent-runner.js";
import {
  SessionActiveRunError,
  type ResearchSessionRepository,
} from "./session-repository.js";

class HoldingAgent extends AbstractAgent {
  readonly events = new Subject<BaseEvent>();

  run(): Subject<BaseEvent> {
    return this.events;
  }
}

describe("DurableResearchAgentRunner", () => {
  it("keeps raw storage failures out of the framework SSE logger", async () => {
    const runner = new DurableResearchAgentRunner({
      connectionSnapshot: async () => { throw new Error("runner-private-storage-canary"); },
    } as unknown as ResearchSessionRepository);
    const result = await firstValueFrom(runner.connect({
      threadId: randomUUID(), headers: { "x-thesistrace-agent-researcher-id": randomUUID() },
    }).pipe(toArray())).then((events) => ({ failed: false, events }), () => ({ failed: true, events: [] }));
    expect(result.failed, "raw storage exception escaped the public Runner stream").toBe(false);
    expect(result.events).toMatchObject([{ type: "RUN_ERROR", code: "AGENT_UNAVAILABLE" }]);
  });

  it("a failed projection stays attached until native execution terminates", async () => {
    const threadId = randomUUID(), runId = randomUUID();
    const runner = new DurableResearchAgentRunner({
      durableBrowserMessagesForThread: async () => { throw new Error("private-projection-canary"); },
    } as unknown as ResearchSessionRepository);
    const agent = new HoldingAgent();
    const events: BaseEvent[] = [];
    const done = new Promise<void>((resolve, reject) => runner.run({ agent, input: input(threadId, runId), threadId }).subscribe({ next: (event) => events.push(event), complete: resolve, error: reject }));
    await vi.waitFor(() => expect(agent.events.observed).toBe(true));
    agent.events.next({ type: EventType.RUN_STARTED, threadId, runId });
    agent.events.next({ type: EventType.MESSAGES_SNAPSHOT, messages: [] });
    await vi.waitFor(() => expect(events.at(-1)?.type).toBe("RUN_ERROR"));
    await expect(runner.mutateSessionWhenIdle(threadId, async () => undefined)).rejects.toBeInstanceOf(SessionActiveRunError);
    agent.events.next({ type: EventType.RUN_FINISHED, threadId, runId });
    agent.events.complete();
    await done;
    expect(events.map((event) => event.type)).toEqual(["RUN_STARTED", "RUN_ERROR"]);
    await expect(runner.mutateSessionWhenIdle(threadId, async () => true)).resolves.toBe(true);
  });

  it("memoizes the same run and rejects a second active run on the Thread", async () => {
    const runner = new DurableResearchAgentRunner({} as ResearchSessionRepository);
    const agent = new HoldingAgent();
    const threadId = randomUUID();
    const firstInput = input(threadId, randomUUID());
    const first = runner.run({ agent, input: firstInput, threadId });

    expect(runner.run({ agent, input: firstInput, threadId })).toBe(first);
    await expect(firstValueFrom(runner.run({
      agent,
      input: {
        ...firstInput,
        messages: [{
          content: "A different request using the same Run ID.",
          id: randomUUID(),
          role: "user",
        }],
      },
      threadId,
    }).pipe(toArray()))).resolves.toMatchObject([{ type: "RUN_ERROR", code: "AGENT_RUN_CONFLICT" }]);
    await expect(firstValueFrom(runner.run({
      agent: new HoldingAgent(),
      input: input(threadId, randomUUID()),
      threadId,
    }).pipe(toArray()))).resolves.toMatchObject([{ type: "RUN_ERROR", code: "AGENT_RUN_CONFLICT" }]);

    agent.events.complete();
    await vi.waitFor(async () => {
      await expect(runner.isRunning({ threadId })).resolves.toBe(false);
    });
  });

  it("reattaches to the Run captured before durable lookup completes", async () => {
    const threadId = randomUUID();
    const runId = randomUUID();
    let resolveLatestRun: ((value: {
      id: string;
      status: "running";
      terminalErrorCode: null;
    }) => void) | undefined;
    const latestRun = new Promise<{
      id: string;
      status: "running";
      terminalErrorCode: null;
    }>((resolve) => {
      resolveLatestRun = resolve;
    });
    const repository = {
      connectionSnapshot: vi.fn(async () => ({ latestRun: await latestRun, messages: [] })),
    } as unknown as ResearchSessionRepository;
    const runner = new DurableResearchAgentRunner(repository);
    const agent = new HoldingAgent();
    const runEvents = firstValueFrom(
      runner.run({ agent, input: input(threadId, runId), threadId }).pipe(toArray()),
    );
    const replayEvents = firstValueFrom(runner.connect({
      headers: { "x-thesistrace-agent-researcher-id": randomUUID() },
      threadId,
    }).pipe(verifyEvents(), toArray()));

    await vi.waitFor(() => expect(agent.events.observed).toBe(true));
    agent.events.next({ type: EventType.RUN_STARTED, threadId, runId });
    agent.events.next({ type: EventType.RUN_FINISHED, threadId, runId });
    agent.events.complete();
    const completedRunEvents = await runEvents;
    expect(completedRunEvents.map((event) => event.type)).toContain(
      EventType.RUN_FINISHED,
    );
    resolveLatestRun?.({ id: runId, status: "running", terminalErrorCode: null });

    await expect(replayEvents).resolves.toMatchObject([
      { type: "RUN_STARTED", threadId, runId },
      { type: "MESSAGES_SNAPSHOT", messages: [] },
      { type: "RUN_FINISHED", threadId, runId },
    ]);
  });

  it("wraps a durable snapshot in a valid AG-UI replay lifecycle", async () => {
    const threadId = randomUUID();
    const runId = randomUUID();
    const repository = {
      connectionSnapshot: vi.fn(async () => ({
        latestRun: { id: runId, status: "completed" as const, terminalErrorCode: null },
        messages: [{ content: "Persisted idea", id: randomUUID(), role: "user" as const }],
      })),
    } as unknown as ResearchSessionRepository;
    const runner = new DurableResearchAgentRunner(repository);

    const events = await firstValueFrom(runner.connect({
      headers: { "x-thesistrace-agent-researcher-id": randomUUID() },
      threadId,
    }).pipe(verifyEvents(), toArray()));

    expect(events.map((event) => event.type)).toEqual([
      "RUN_STARTED",
      "MESSAGES_SNAPSHOT",
      "RUN_FINISHED",
    ]);
    expect(events[0]).toMatchObject({ runId, threadId });
    expect(events[2]).toMatchObject({ runId, threadId });
  });

  it("persists an A2UI Activity before exposing it and hides its raw Tool events", async () => {
    const threadId = fixedUuid(181);
    const runId = fixedUuid(182);
    let releasePersistence: () => void = () => undefined;
    const persistence = new Promise<void>((resolve) => {
      releasePersistence = resolve;
    });
    const repository = {
      persistA2UIActivity: vi.fn(() => persistence),
    } as unknown as ResearchSessionRepository;
    const runner = new DurableResearchAgentRunner(repository);
    const agent = new HoldingAgent();
    const events: BaseEvent[] = [];
    const completed = new Promise<void>((resolve, reject) => {
      runner.run({ agent, input: input(threadId, runId), threadId }).subscribe({
        complete: resolve,
        error: reject,
        next: (event) => events.push(event),
      });
    });

    await vi.waitFor(() => expect(agent.events.observed).toBe(true));
    agent.events.next({ type: EventType.RUN_STARTED, threadId, runId });
    agent.events.next({
      parentMessageId: "assistant-owner",
      toolCallId: "render-call",
      toolCallName: "render_a2ui",
      type: EventType.TOOL_CALL_START,
    });
    agent.events.next({
      activityType: RESEARCH_A2UI_ACTIVITY_TYPE,
      content: readyA2UIContent(),
      messageId: "a2ui-surface-render-call",
      replace: true,
      type: EventType.ACTIVITY_SNAPSHOT,
    });
    expect(events.some((event) => event.type === EventType.ACTIVITY_SNAPSHOT)).toBe(false);
    agent.events.next({
      content: JSON.stringify(readyA2UIContent()),
      messageId: "render-result",
      role: "tool",
      toolCallId: "render-call",
      type: EventType.TOOL_CALL_RESULT,
    });

    await vi.waitFor(() => expect(repository.persistA2UIActivity).toHaveBeenCalledOnce());
    expect(events.some((event) => event.type === EventType.ACTIVITY_SNAPSHOT)).toBe(false);
    expect(events.some((event) => event.type === EventType.TOOL_CALL_START)).toBe(false);

    releasePersistence();
    await vi.waitFor(() => expect(
      events.some((event) => event.type === EventType.ACTIVITY_SNAPSHOT),
    ).toBe(true));
    expect(repository.persistA2UIActivity).toHaveBeenCalledWith(expect.objectContaining({
      lifecycle: "ready",
      messageId: "a2ui-surface-render-call",
      ownerMessageId: "assistant-owner",
      runId,
      sequence: 1,
      threadId,
    }));

    agent.events.complete();
    await completed;
  });

  it("preserves a safe terminal error when an active Run fails before starting", async () => {
    const threadId = randomUUID();
    const runId = randomUUID();
    const repository = {
      connectionSnapshot: vi.fn(async () => ({
        latestRun: { id: runId, status: "running" as const, terminalErrorCode: null },
        messages: [],
      })),
    } as unknown as ResearchSessionRepository;
    const runner = new DurableResearchAgentRunner(repository);
    const agent = new HoldingAgent();
    const runEvents = firstValueFrom(
      runner.run({ agent, input: input(threadId, runId), threadId }).pipe(toArray()),
    );
    const replayEvents = firstValueFrom(runner.connect({
      headers: { "x-thesistrace-agent-researcher-id": randomUUID() },
      threadId,
    }).pipe(verifyEvents(), toArray()));

    await vi.waitFor(() => expect(agent.events.observed).toBe(true));
    agent.events.next({
      type: EventType.RUN_ERROR,
      code: "AGENT_RUN_FAILED",
      message: "The Research Agent could not complete this run.",
    });
    agent.events.complete();

    await expect(runEvents).resolves.toHaveLength(1);
    await expect(replayEvents).resolves.toMatchObject([
      { type: "RUN_STARTED", threadId, runId },
      { type: "MESSAGES_SNAPSHOT", messages: [] },
      { type: "RUN_ERROR", code: "AGENT_RUN_FAILED" },
    ]);
  });

  it("rejects Session mutation immediately while the Thread Run is active", async () => {
    const runner = new DurableResearchAgentRunner({} as ResearchSessionRepository);
    const agent = new HoldingAgent();
    const threadId = fixedUuid(201);
    const released = new Promise<void>((resolve) => {
      runner.run({ agent, input: input(threadId, fixedUuid(202)), threadId })
        .subscribe({ complete: resolve });
    });

    await expect(runner.mutateSessionWhenIdle(threadId, async () => "deleted"))
      .rejects.toBeInstanceOf(SessionActiveRunError);

    agent.events.complete();
    await released;
    await expect(runner.mutateSessionWhenIdle(threadId, async () => "deleted"))
      .resolves.toBe("deleted");
  });

  it("prevents a new Turn from racing an idle Session mutation", async () => {
    const runner = new DurableResearchAgentRunner({} as ResearchSessionRepository);
    const threadId = fixedUuid(211);
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const mutation = runner.mutateSessionWhenIdle(threadId, async () => {
      await held;
      return "deleted";
    });

    await expect(firstValueFrom(runner.run({
      agent: new HoldingAgent(),
      input: input(threadId, fixedUuid(212)),
      threadId,
    }).pipe(toArray()))).resolves.toMatchObject([{ type: "RUN_ERROR", code: "AGENT_RUN_CONFLICT" }]);

    release();
    await expect(mutation).resolves.toBe("deleted");
    const agent = new HoldingAgent();
    runner.run({ agent, input: input(threadId, fixedUuid(213)), threadId }).subscribe();
    agent.events.complete();
  });
});

function input(threadId: string, runId: string): RunAgentInput {
  return {
    context: [],
    forwardedProps: {},
    messages: [],
    runId,
    state: {},
    threadId,
    tools: [],
  };
}

function fixedUuid(suffix: number): string {
  return `00000000-0000-4000-8000-${suffix.toString().padStart(12, "0")}`;
}

function readyA2UIContent(): Record<string, unknown> {
  return {
    a2ui_operations: [{
      createSurface: {
        catalogId: RESEARCH_A2UI_CATALOG_ID,
        surfaceId: "research-result",
      },
      version: RESEARCH_A2UI_PROTOCOL_VERSION,
    }, {
      updateComponents: {
        components: [{
          component: "Text",
          id: "root",
          text: "Research result available",
        }],
        surfaceId: "research-result",
      },
      version: RESEARCH_A2UI_PROTOCOL_VERSION,
    }],
  };
}
