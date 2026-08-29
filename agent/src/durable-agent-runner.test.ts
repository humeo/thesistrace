import { randomUUID } from "node:crypto";

import { AbstractAgent, verifyEvents } from "@ag-ui/client";
import { EventType, type BaseEvent, type RunAgentInput } from "@ag-ui/core";
import { firstValueFrom, Subject, toArray } from "rxjs";
import { describe, expect, it, vi } from "vitest";

import { DurableResearchAgentRunner } from "./durable-agent-runner.js";
import type { ResearchSessionRepository } from "./session-repository.js";

class HoldingAgent extends AbstractAgent {
  readonly events = new Subject<BaseEvent>();

  run(): Subject<BaseEvent> {
    return this.events;
  }
}

describe("DurableResearchAgentRunner", () => {
  it("memoizes the same run and rejects a second active run on the Thread", async () => {
    const runner = new DurableResearchAgentRunner({} as ResearchSessionRepository);
    const agent = new HoldingAgent();
    const threadId = randomUUID();
    const firstInput = input(threadId, randomUUID());
    const first = runner.run({ agent, input: firstInput, threadId });

    expect(runner.run({ agent, input: firstInput, threadId })).toBe(first);
    expect(() => runner.run({
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
    })).toThrow("ACTIVE_RUN_REQUEST_CONFLICT");
    expect(() => runner.run({
      agent: new HoldingAgent(),
      input: input(threadId, randomUUID()),
      threadId,
    })).toThrow("Thread already running");

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
      durableMessages: vi.fn(async () => []),
      latestRun: vi.fn(() => latestRun),
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
      durableMessages: vi.fn(async () => [{
        content: "Persisted idea",
        id: randomUUID(),
        role: "user" as const,
      }]),
      latestRun: vi.fn(async () => ({
        id: runId,
        status: "completed" as const,
        terminalErrorCode: null,
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

  it("preserves a safe terminal error when an active Run fails before starting", async () => {
    const threadId = randomUUID();
    const runId = randomUUID();
    const repository = {
      durableMessages: vi.fn(async () => []),
      latestRun: vi.fn(async () => ({
        id: runId,
        status: "running" as const,
        terminalErrorCode: null,
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
