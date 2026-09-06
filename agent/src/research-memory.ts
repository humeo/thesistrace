import { parseMemoryRequestContext } from "@mastra/core/memory";
import type { Processor } from "@mastra/core/processors";
import { Memory } from "@mastra/memory";
import type { MastraCompositeStore } from "@mastra/core/storage";

import { AGENT_LIMITS } from "./guarded-language-model.js";
import type { ResolvedModelSelection } from "./model-runtime.js";

/** Session-scoped native compression, with budgets derived from the selected model. */
export function createResearchMemory(storage: MastraCompositeStore, selection: ResolvedModelSelection): Memory {
  const inputTokens = Math.floor(selection.model.contextWindow * 0.9);
  const modelSettings = {
    maxOutputTokens: selection.model.maxOutputTokens,
    timeout: { stepMs: AGENT_LIMITS.providerCallMs },
  };
  return new ResearchMemory({
    storage,
    vector: false,
    options: {
      // Native tool-resume hydration needs recent history. OM independently
      // loads every unobserved message before constructing the model context.
      lastMessages: 50,
      semanticRecall: false,
      workingMemory: { enabled: false },
      observationalMemory: selection.compactionEnabled ? {
        scope: "thread",
        // Mastra propagates the Run's request context to Observer/Reflector.
        // Keep usage, cancellation and failure accounting on that exact Run.
        model: ({ requestContext }) => requestContext.get<string, ResolvedModelSelection>("selection").memoryLanguageModel,
        observation: {
          messageTokens: Math.floor(inputTokens / 2),
          // Complete compression inside the Run before the next model call.
          bufferTokens: false,
          continuationHints: { suggestedResponse: false },
          modelSettings,
          providerOptions: selection.providerOptions,
        },
        reflection: {
          // Leave the rest for instructions, Tool schemas and new Tool results.
          observationTokens: Math.floor(inputTokens / 8),
          modelSettings,
          providerOptions: selection.providerOptions,
        },
      } : false,
    },
  });
}

/** Raw history must never acquire a message-count cutoff when OM is disabled. */
class ResearchMemory extends Memory {
  override async getInputProcessors(...args: Parameters<Memory["getInputProcessors"]>) {
    const processors = await super.getInputProcessors(...args);
    const completeHistory = {
      id: "message-history",
      processInput: async ({ messageList, requestContext }) => {
        const context = parseMemoryRequestContext(requestContext);
        const memoryInfo = messageList.serialize().memoryInfo;
        const threadId = context?.thread?.id ?? memoryInfo?.threadId;
        const resourceId = context?.resourceId ?? memoryInfo?.resourceId;
        if (!threadId || !resourceId) throw new Error("Session history requires thread and resource identity");
        const { messages } = await this.recall({ threadId, resourceId, perPage: false,
          orderBy: { field: "createdAt", direction: "ASC" } });
        // In-flight resume results take precedence over older stored versions.
        const present = new Set(messageList.get.all.db().map((message) => message.id));
        for (const message of messages) {
          if (message.role !== "system" && !present.has(message.id)) messageList.add(message, "memory");
        }
        return messageList;
      },
    } satisfies Processor;
    return processors.map((processor) => "id" in processor && processor.id === "message-history" ? completeHistory : processor);
  }
}
