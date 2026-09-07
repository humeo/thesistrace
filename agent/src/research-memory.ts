import { parseMemoryRequestContext } from "@mastra/core/memory";
import type { Processor } from "@mastra/core/processors";
import { Memory } from "@mastra/memory";
import type { MastraCompositeStore } from "@mastra/core/storage";

/** Raw Session history only; the context controller owns all compaction scheduling. */
export function createResearchMemory(storage: MastraCompositeStore): Memory {
  return new ResearchMemory({ storage, vector: false, options: {
    lastMessages: false, semanticRecall: false, workingMemory: { enabled: false }, observationalMemory: false,
  } });
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
    return [completeHistory, ...processors.filter((processor) => !("id" in processor && processor.id === "message-history"))];
  }
}
