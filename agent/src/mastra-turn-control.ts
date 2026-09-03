import type { Agent } from "@mastra/core/agent";

import { ChatControlError, type CommandReceipt, type SteerInput, type StopInput } from "./chat-control.js";
import type { DurableResearchAgentRunner } from "./durable-agent-runner.js";
import type { ResearchSessionRepository } from "./session-repository.js";

/** Thin quarantine around Mastra's experimental signal API. */
export class MastraTurnControl {
  constructor(
    private readonly agent: Agent,
    private readonly runner: DurableResearchAgentRunner,
    private readonly repository: ResearchSessionRepository,
  ) {}

  async steer(
    threadId: string,
    researcherId: string,
    input: SteerInput,
  ): Promise<CommandReceipt> {
    const prepared = await this.repository.prepareSteer(threadId, researcherId, input);
    if (prepared.duplicate) return prepared.receipt;
    let accepted: Awaited<ReturnType<Agent["sendSignal"]>["accepted"]>;
    try {
      const result = this.agent.sendSignal({
        contents: input.content,
        id: input.inputId,
        type: "user",
      }, {
        ifActive: { behavior: "deliver" },
        resourceId: researcherId,
        runId: input.expectedTurnId,
        threadId,
      });
      accepted = await result.accepted;
    } catch (error) {
      if (error instanceof ChatControlError) throw error;
      await this.repository.rejectPendingCommand(
        threadId,
        input.inputId,
        "CHAT_CAPABILITY_UNAVAILABLE",
      ).catch(() => undefined);
      throw new ChatControlError("CHAT_CAPABILITY_UNAVAILABLE", 409);
    }
    if (accepted.action !== "deliver" || accepted.runId !== input.expectedTurnId) {
      await this.repository.rejectPendingCommand(
        threadId,
        input.inputId,
        "CHAT_TURN_NOT_STEERABLE",
      );
      throw new ChatControlError("CHAT_TURN_NOT_STEERABLE", 409);
    }
    // Once Mastra confirms delivery, a storage failure is an unknown
    // acceptance outcome. Leave the receipt pending so the client can
    // reconcile it instead of releasing and possibly duplicating the input.
    return await this.repository.acceptSteer(threadId, researcherId, input);
  }

  async stop(
    threadId: string,
    researcherId: string,
    input: StopInput,
  ): Promise<CommandReceipt> {
    const prepared = await this.repository.prepareStop(threadId, researcherId, input);
    if (prepared.duplicate && prepared.receipt.status !== "pending") {
      return prepared.receipt;
    }

    // prepareStop's row-level CAS is the authority: once it wins, a natural
    // completion may no longer turn this run into "completed". The in-memory
    // stream can already have left the runner registry at that exact boundary,
    // so a missing abort target must not strand the durable row in "stopping".
    if (prepared.previousStatus === "waiting_for_user") {
      try {
        this.agent.abortRunStream(input.expectedTurnId);
      } catch {
        // The suspended stream may already have been released by Mastra.
      }
    } else {
      await this.runner.stopTurn(threadId, input.expectedTurnId).catch(() => false);
    }

    const receipt = await this.repository.finishStop(
      threadId,
      researcherId,
      input.commandId,
      input.expectedTurnId,
    );
    if (prepared.previousStatus === "waiting_for_user") {
      await this.repository.discardSuspendedRun(input.expectedTurnId).catch(() => undefined);
    }
    return receipt;
  }
}
