import type { MessageList } from "@mastra/core/agent";
import type { Memory } from "@mastra/memory";
import { ModelRequestFailure, type RunModelObservation } from "./guarded-language-model.js";
import { invalidRecoveryMessageIds, mayRecoverModelStep, type ModelStepRecovery } from "./model-step-recovery.js";
import { AgentRunFailure, providerFailureCode } from "./run-failure.js";
import type { ResolvedModelSelection } from "./model-runtime.js";
import type { SessionContextController } from "./session-context-controller.js";
import type { ResearchSessionRepository } from "./session-repository.js";

/** Coordinates one durable recovery; Mastra owns the actual model retry and stream. */
export class SessionModelRecovery {
  private activeMessageId: string | undefined;
  private pending: ModelStepRecovery | undefined;
  constructor(private readonly options: Readonly<{ repository: ResearchSessionRepository; memory: Memory;
    threadId: string; researcherId: string; runId: string; selection: ResolvedModelSelection;
    context: SessionContextController; observation: RunModelObservation; abortSignal: AbortSignal; notify: (claimed: boolean) => void;
  }>) {}

  responseMessageId(freshId: string, retryCount: number): string {
    if (retryCount && !this.pending?.replacementMessageId) throw new AgentRunFailure("RECOVERY_FAILED");
    this.activeMessageId = retryCount ? this.pending!.replacementMessageId! : freshId;
    return this.activeMessageId;
  }

  /** A replacement stays excluded through cancellation/crash until a valid model step is durable. */
  async completeResponse(finishReason: string | undefined): Promise<void> {
    if (!this.pending || this.activeMessageId !== this.pending.replacementMessageId) return;
    if (finishReason !== "stop" && finishReason !== "tool-calls") return;
    const { repository, threadId, researcherId, runId, abortSignal, observation } = this.options;
    abortSignal.throwIfAborted();
    if (observation.terminalFailure() !== undefined) return;
    await repository.completeModelStepReplacement(threadId, researcherId, runId, this.activeMessageId);
  }

  async handle(error: unknown, messageList: MessageList, currentRequestId?: string): Promise<{ retry: true }> {
    const { repository, memory, threadId, researcherId, runId, observation, abortSignal, selection, context } = this.options;
    abortSignal.throwIfAborted();
    const messageId = this.activeMessageId;
    if (!messageId) throw new AgentRunFailure("RECOVERY_FAILED");
    if (!(error instanceof ModelRequestFailure) || observation.pendingRequestFailure !== error) {
      if (this.pending?.replacementMessageId === messageId) {
        await repository.invalidateModelStepReplacement(threadId, researcherId, runId, messageId);
        await repository.updateModelStepRecovery(threadId, researcherId, runId, this.pending.originalMessageId,
          { status: "failed", errorCode: providerFailureCode(error) });
        throw observation.terminateRequestFailure("RECOVERY_FAILED");
      }
      throw error;
    }
    const messages = messageList.get.all.db().filter((message) => message.role !== "system" && message.content.parts.length > 0);
    if (messages.some((message) => message.threadId !== threadId || message.resourceId !== researcherId)) throw new AgentRunFailure("RECOVERY_FAILED");
    await memory.saveMessages({ messages });
    const claim = await repository.recordModelStepStop({ threadId, researcherId, runId, messageId,
      cause: error.code, budget: error.budget, allowRecovery: mayRecoverModelStep(selection.compactionEnabled, error.code, error.budget) });
    if (claim.claimed) observation.recoveryAttempts++;
    this.options.notify(claim.claimed);
    if (!claim.claimed) {
      if (claim.recovery.status === "recovering" && claim.recovery.replacementMessageId === messageId) {
        await repository.updateModelStepRecovery(threadId, researcherId, runId, claim.recovery.originalMessageId,
          { status: "failed", errorCode: "RECOVERY_FAILED" });
      }
      throw observation.terminateRequestFailure(claim.recovery.attempts ? "RECOVERY_FAILED" : error.code);
    }
    try {
      const replacement = await context.recover(error, currentRequestId);
      abortSignal.throwIfAborted();
      this.pending = await repository.updateModelStepRecovery(threadId, researcherId, runId, claim.recovery.originalMessageId,
        { status: "recovering", budget: replacement.budget });
      observation.acknowledgeRecovery(error, replacement.budget);
      messageList.removeByIds(invalidRecoveryMessageIds(await repository.modelStepRecoveries(threadId, researcherId)));
      return { retry: true };
    } catch (failure) {
      const code = abortSignal.aborted ? providerFailureCode(abortSignal.reason)
        : failure instanceof ModelRequestFailure ? failure.code
        : providerFailureCode(failure) === "PROVIDER_TIMEOUT" ? "PROVIDER_TIMEOUT" : "CONTEXT_COMPACTION_FAILED";
      await repository.updateModelStepRecovery(threadId, researcherId, runId, claim.recovery.originalMessageId, { status: "failed", errorCode: code });
      throw observation.terminateRequestFailure(code);
    }
  }
}
