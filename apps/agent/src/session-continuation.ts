import { modelRequestBudget } from "./model-context.js";
import type { AgentConfig } from "@mastra/core/agent";
import type { Mastra } from "@mastra/core/mastra";
import type { RequestContext } from "@mastra/core/request-context";
import type { PostgresStore } from "@mastra/pg";
import { ContextLanguageModel } from "./context-language-model.js";
import type { RunModelObservation } from "./guarded-language-model.js";
import { invalidRecoveryMessageIds } from "./model-step-recovery.js";
import type { ResolvedModelSelection } from "./model-runtime.js";
import { createResearchMemory } from "./research-memory.js";
import { isSessionControlMessageId, sessionControlMessage, sessionControlMessageId } from "./session-control-message.js";
import { SessionContextController } from "./session-context-controller.js";
import { SessionModelRecovery } from "./session-model-recovery.js";
import { SessionNotFoundError, type ResearchSessionRepository } from "./session-repository.js";

const stateKey = "sessionContinuation";
type RunIdentity = Readonly<{
  threadId: string;
  researcherId: string;
  runId: string;
  continueIntent: boolean;
  selection: ResolvedModelSelection;
  observation: RunModelObservation;
}>;
type RunState = {
  identity: RunIdentity;
  currentRequestId?: string;
  context?: SessionContextController;
  recovery?: SessionModelRecovery;
};
function stateFrom(requestContext: RequestContext | undefined): RunState | undefined {
  return requestContext?.get<string, RunState | undefined>(stateKey);
}

/** Installs the provider preparation and durable recovery sequence as one run-owned module. */
export function createSessionContinuation(options: Readonly<{
  repository: ResearchSessionRepository;
  storage: PostgresStore;
  mastra: () => Mastra;
  selection: (requestContext: RequestContext) => ResolvedModelSelection;
}>) {
  const { repository, storage } = options;
  const agentOptions: Pick<AgentConfig, "inputProcessors" | "outputProcessors" | "errorProcessors" | "model"> = {
    inputProcessors: () => [{
      id: "session-context-input",
      processInputStep: async ({ messageList, requestContext, rotateResponseMessageId, retryCount }) => {
        const state = stateFrom(requestContext);
        const abortSignal = requestContext?.get<string, AbortSignal>("agentAbortSignal");
        if (!state || !requestContext || !abortSignal) throw new Error("SESSION_CONTEXT_IDENTITY_MISSING");
        const { threadId, researcherId, runId, continueIntent, selection, observation } = state.identity;
        abortSignal.throwIfAborted();
        if (await repository.ownership(threadId, researcherId) !== "owned") throw new SessionNotFoundError();
        const recoveries = await repository.modelStepRecoveries(threadId, researcherId);
        messageList.removeByIds(invalidRecoveryMessageIds(recoveries));
        observation.recoveryAttempts = recoveries.filter(record => record.runId === runId)
          .reduce((total, record) => total + record.attempts, 0);
        if (!messageList.get.all.db().some(message => message.id === sessionControlMessageId(runId))) {
          const lastCreated = Math.max(Date.now(), ...messageList.get.all.db().map(message => message.createdAt.getTime() + 1));
          messageList.add(sessionControlMessage({ runId, threadId, researcherId, createdAt: new Date(lastCreated), continueIntent }), "context", { merge: false });
        }
        if (!rotateResponseMessageId) throw new Error("SESSION_CONTEXT_RESPONSE_BOUNDARY_MISSING");
        const freshResponseId = rotateResponseMessageId();
        const messages = messageList.get.all.db().filter(message => message.role !== "system" && message.content.parts.length > 0);
        if (messages.some(message => message.threadId !== threadId || message.resourceId !== researcherId)) throw new Error("SESSION_CONTEXT_SOURCE_IDENTITY_MISMATCH");
        // Freeze the source watermark only after the complete current tool batch is durable.
        await createResearchMemory(storage).saveMessages({ messages });
        state.currentRequestId = [...messages].reverse().find(message => message.role === "user" && !isSessionControlMessageId(message.id))?.id;
        // A ResearchMastraAgent clone installs its own signal before the first step.
        state.context ??= new SessionContextController({ repository, threadId, researcherId, runId, selection,
          storage, mastra: options.mastra(), requestContext, abortSignal });
        state.recovery ??= new SessionModelRecovery({ repository, memory: createResearchMemory(storage), threadId, researcherId, runId,
          selection, context: state.context, observation, abortSignal,
          notify: claimed => requestContext.get<string, ((claimed: boolean) => void) | undefined>("notifyModelRecovery")?.(claimed) });
        return { messageId: state.recovery.responseMessageId(freshResponseId, retryCount) };
      },
    }],
    outputProcessors: [{ id: "session-replacement-completion", processOutputStep: async ({ requestContext, finishReason, messageList }) => {
      await stateFrom(requestContext)?.recovery?.completeResponse(finishReason);
      return messageList;
    } }],
    errorProcessors: [{ id: "session-model-recovery", processAPIError: async ({ error, messageList, requestContext }) => {
      const state = stateFrom(requestContext);
      if (!state?.recovery) throw error;
      return state.recovery.handle(error, messageList, state.currentRequestId);
    } }],
    model: ({ requestContext }) => new ContextLanguageModel(options.selection(requestContext).languageModel, async request => {
      const state = stateFrom(requestContext);
      if (!state?.context) throw new Error("SESSION_CONTEXT_INPUT_NOT_PREPARED");
      const prepared = await state.context.prepare(request, state.currentRequestId);
      const { selection, threadId, researcherId, runId } = state.identity;
      // Optional UI observations must not fail or retry model execution.
      try {
        await repository.saveContextWindow(
          threadId, researcherId, runId,
          { model_key: selection.model.key, context_window: selection.model.contextWindow,
            input_tokens: modelRequestBudget(prepared, selection.model).inputTokens, measured_at: new Date().toISOString() },
        );
      } catch { /* A failed observation write leaves the previous timestamped snapshot intact. */ }
      return prepared;
    }),
  };
  return {
    agentOptions,
    initialize(requestContext: RequestContext, identity: RunIdentity) {
      if (stateFrom(requestContext)) throw new Error("SESSION_CONTINUATION_ALREADY_INITIALIZED");
      requestContext.set(stateKey, { identity: Object.freeze({ ...identity }) } satisfies RunState);
    },
    compactionStatistics(requestContext: RequestContext) {
      return stateFrom(requestContext)?.context?.compactionStatistics;
    },
  };
}
export type SessionContinuation = ReturnType<typeof createSessionContinuation>;
