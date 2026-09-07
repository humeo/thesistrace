import { Memory } from "@mastra/memory";
import type { PostgresStore } from "@mastra/pg";

import { AGENT_LIMITS } from "./guarded-language-model.js";
import type { ResolvedModelSelection } from "./model-runtime.js";

/** Session-scoped native compression, with budgets derived from the selected model. */
export function createResearchMemory(storage: PostgresStore, selection: ResolvedModelSelection): Memory {
  const inputTokens = selection.model.contextWindow - AGENT_LIMITS.outputTokens;
  const modelSettings = {
    maxOutputTokens: AGENT_LIMITS.outputTokens,
    timeout: { stepMs: AGENT_LIMITS.providerCallMs },
  };
  return new Memory({
    storage,
    vector: false,
    options: {
      // Native tool-resume hydration needs recent history. OM independently
      // loads every unobserved message before constructing the model context.
      lastMessages: 50,
      semanticRecall: false,
      workingMemory: { enabled: false },
      observationalMemory: {
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
      },
    },
  });
}
