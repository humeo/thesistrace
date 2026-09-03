import type { Agent } from "@mastra/core/agent";
import { describe, expect, it, vi } from "vitest";

import { ChatControlError, type CommandReceipt, type SteerInput, type StopInput } from "./chat-control.js";
import type { DurableResearchAgentRunner } from "./durable-agent-runner.js";
import { MastraTurnControl } from "./mastra-turn-control.js";
import type { ResearchSessionRepository } from "./session-repository.js";

const THREAD_ID = "00000000-0000-4000-8000-000000000001";
const TURN_ID = "00000000-0000-4000-8000-000000000002";
const COMMAND_ID = "00000000-0000-4000-8000-000000000003";

describe("Mastra Turn control", () => {
  it("delivers Steer as one user signal to the exact active Run", async () => {
    const acceptSteer = vi.fn(async () => receipt("steer", "accepted"));
    const sendSignal = vi.fn(() => ({
      accepted: Promise.resolve({ action: "deliver" as const, runId: TURN_ID }),
    }));
    const control = createControl({ acceptSteer, sendSignal });

    await expect(control.steer(THREAD_ID, "researcher", steerInput()))
      .resolves.toEqual(receipt("steer", "accepted"));
    expect(sendSignal).toHaveBeenCalledWith({
      contents: "Compare turnover.",
      id: COMMAND_ID,
      type: "user",
    }, {
      ifActive: { behavior: "deliver" },
      resourceId: "researcher",
      runId: TURN_ID,
      threadId: THREAD_ID,
    });
    expect(acceptSteer).toHaveBeenCalledOnce();
  });

  it("rejects a deliver decision for any other authoritative Run", async () => {
    const rejectPendingCommand = vi.fn(async () => undefined);
    const control = createControl({
      rejectPendingCommand,
      sendSignal: vi.fn(() => ({
        accepted: Promise.resolve({
          action: "deliver" as const,
          runId: "00000000-0000-4000-8000-000000000099",
        }),
      })),
    });

    await expect(control.steer(THREAD_ID, "researcher", steerInput()))
      .rejects.toMatchObject({ code: "CHAT_TURN_NOT_STEERABLE", status: 409 });
    expect(rejectPendingCommand).toHaveBeenCalledWith(
      THREAD_ID,
      COMMAND_ID,
      "CHAT_TURN_NOT_STEERABLE",
    );
  });

  it("does not inject a duplicate accepted Steer", async () => {
    const sendSignal = vi.fn();
    const control = createControl({
      prepareSteer: vi.fn(async () => ({
        duplicate: true,
        receipt: receipt("steer", "accepted"),
      })),
      sendSignal,
    });
    await expect(control.steer(THREAD_ID, "researcher", steerInput()))
      .resolves.toEqual(receipt("steer", "accepted"));
    expect(sendSignal).not.toHaveBeenCalled();
  });

  it("leaves a delivered Steer pending when its durable acceptance cannot be recorded", async () => {
    const rejectPendingCommand = vi.fn(async () => undefined);
    const control = createControl({
      acceptSteer: vi.fn(async () => { throw new Error("storage unavailable"); }),
      rejectPendingCommand,
      sendSignal: vi.fn(() => ({
        accepted: Promise.resolve({ action: "deliver" as const, runId: TURN_ID }),
      })),
    });

    await expect(control.steer(THREAD_ID, "researcher", steerInput()))
      .rejects.toThrow("storage unavailable");
    expect(rejectPendingCommand).not.toHaveBeenCalled();
  });

  it("closes a Stop won by durable CAS even if the in-memory Run already left", async () => {
    const stopTurn = vi.fn(async () => false);
    const finishStop = vi.fn(async () => receipt("stop", "accepted"));
    const control = createControl({ finishStop, stopTurn });

    await expect(control.stop(THREAD_ID, "researcher", stopInput()))
      .resolves.toEqual(receipt("stop", "accepted"));
    expect(stopTurn).toHaveBeenCalledWith(THREAD_ID, TURN_ID);
    expect(finishStop).toHaveBeenCalledWith(THREAD_ID, "researcher", COMMAND_ID, TURN_ID);
  });

  it("finishes a recovered pending Stop and discards a suspended snapshot", async () => {
    const abortRunStream = vi.fn();
    const discardSuspendedRun = vi.fn(async () => undefined);
    const finishStop = vi.fn(async () => receipt("stop", "accepted"));
    const control = createControl({
      abortRunStream,
      discardSuspendedRun,
      finishStop,
      prepareStop: vi.fn(async () => ({
        duplicate: true,
        previousStatus: "waiting_for_user" as const,
        receipt: receipt("stop", "pending"),
      })),
    });

    await expect(control.stop(THREAD_ID, "researcher", stopInput()))
      .resolves.toEqual(receipt("stop", "accepted"));
    expect(abortRunStream).toHaveBeenCalledWith(TURN_ID);
    expect(finishStop).toHaveBeenCalledOnce();
    expect(discardSuspendedRun).toHaveBeenCalledWith(TURN_ID);
  });
});

function createControl(overrides: Record<string, unknown> = {}): MastraTurnControl {
  const repository = {
    acceptSteer: vi.fn(async () => receipt("steer", "accepted")),
    discardSuspendedRun: vi.fn(async () => undefined),
    finishStop: vi.fn(async () => receipt("stop", "accepted")),
    prepareSteer: vi.fn(async () => ({ duplicate: false, receipt: receipt("steer", "pending") })),
    prepareStop: vi.fn(async () => ({
      duplicate: false,
      previousStatus: "running" as const,
      receipt: receipt("stop", "pending"),
    })),
    rejectPendingCommand: vi.fn(async () => undefined),
    ...overrides,
  } as unknown as ResearchSessionRepository;
  const agent = {
    abortRunStream: vi.fn(),
    sendSignal: vi.fn(),
    ...overrides,
  } as unknown as Agent;
  const runner = {
    stopTurn: vi.fn(async () => true),
    ...overrides,
  } as unknown as DurableResearchAgentRunner;
  return new MastraTurnControl(agent, runner, repository);
}

function receipt(kind: "steer" | "stop", status: "pending" | "accepted"): CommandReceipt {
  return { commandId: COMMAND_ID, errorCode: null, kind, status, turnId: TURN_ID };
}

function steerInput(): SteerInput {
  return {
    content: "Compare turnover.",
    expectedTurnId: TURN_ID,
    fingerprint: Buffer.alloc(32),
    inputId: COMMAND_ID,
  };
}

function stopInput(): StopInput {
  return { commandId: COMMAND_ID, expectedTurnId: TURN_ID, fingerprint: Buffer.alloc(32) };
}
