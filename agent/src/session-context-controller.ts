import { sessionControlMessageId } from "./session-control-message.js";
import type { LanguageModelV3CallOptions } from "@ai-sdk/provider";
import { MessageList, type MastraDBMessage } from "@mastra/core/agent";
import { noopLogger } from "@mastra/core/logger";
import { ModelRequestFailure } from "./guarded-language-model.js";
import { modelRequestBudget, ModelInputTokenCounter } from "./model-context.js";
import { ContextCandidateError, generateSessionContext } from "./session-context-generation.js";
import { restoreContextTail, selectContextHistory } from "./session-context-selection.js";
import { freezeContextSource, type SessionContextSnapshot } from "./session-context-state.js";
import type { ResearchSessionRepository } from "./session-repository.js";
import { AgentRunFailure, providerFailureCode } from "./run-failure.js";

type GenerationOptions = Parameters<typeof generateSessionContext>[0];
type Repository = Pick<ResearchSessionRepository, "contextCheckpoint" | "rawContextMessages" | "beginContextCycle" | "commitContextCycle" | "releaseContextCycle">;
type ControllerOptions = Omit<GenerationOptions, "removed" | "sourceParts" | "turnPrefixMessageIds" | "currentRequest" | "requiredReferences" | "previous"> & Readonly<{
  repository: Repository; threadId: string; researcherId: string; runId: string;
}>;

/** Owns the publish boundary. The caller supplies the final provider-shaped request. */
export class SessionContextController {
  private latestStatistics: SessionContextSnapshot["statistics"] | undefined;
  get compactionStatistics() { return this.latestStatistics; }
  private readonly counter = new ModelInputTokenCounter();
  constructor(private readonly options: ControllerOptions,
    private readonly generate = generateSessionContext) {}

  async prepare(request: LanguageModelV3CallOptions, currentRequestId?: string): Promise<LanguageModelV3CallOptions> {
    try {
      return await this.prepareContext(request, currentRequestId);
    } catch (error) {
      this.options.abortSignal.throwIfAborted();
      if (error instanceof AgentRunFailure) throw error;
      const code = providerFailureCode(error);
      if (code !== "INTERNAL_FAILURE") throw new AgentRunFailure(code);
      throw new ContextCandidateError();
    }
  }

  private async prepareContext(request: LanguageModelV3CallOptions, currentRequestId?: string): Promise<LanguageModelV3CallOptions> {
    const { repository, threadId, researcherId, runId, selection, abortSignal } = this.options;
    abortSignal.throwIfAborted();
    const checkpoint = await repository.contextCheckpoint(threadId, researcherId);
    const raw = await repository.rawContextMessages(threadId, researcherId);
    let effective = checkpoint ? await this.withSnapshot(request, raw, checkpoint.snapshot) : request;
    const before = modelRequestBudget(effective, selection.model, this.counter);
    const threshold = Math.floor(selection.model.contextWindow * 0.9);
    if (!selection.compactionEnabled || (before.inputTokens < threshold && before.outputTokens > 0)) {
      if (before.outputTokens <= 0) throw new ModelRequestFailure("CONTEXT_TOO_LARGE", before);
      return effective;
    }
    const started = performance.now();
    const cycle = await repository.beginContextCycle(threadId, researcherId, runId);
    try {
      if ((cycle.checkpoint?.revision ?? 0) !== (checkpoint?.revision ?? 0)
        || JSON.stringify(cycle.sourceWatermark) !== JSON.stringify(freezeContextSource(raw))) {
        throw new ContextCandidateError();
      }
      const selected = selectContextHistory(raw, { recentTokens: Math.min(20_000, Math.floor(threshold / 2)), currentRequestId,
        fixedMessageIds: [sessionControlMessageId(runId)], previous: checkpoint?.snapshot }, this.counter);
      const requestPosition = raw.findIndex((message) => message.id === currentRequestId);
      const turnPrefixMessageIds = requestPosition < 0 ? [] : raw.slice(requestPosition + 1).map((message) => message.id);
      const generated = await this.generate({ ...this.options, removed: selected.removed,
        sourceParts: selected.removedParts,
        turnPrefixMessageIds,
        previous: checkpoint ? { memory: checkpoint.snapshot.memory, summary: checkpoint.snapshot.summary } : undefined,
        currentRequest: raw.find((message) => message.id === currentRequestId),
        requiredReferences: continuationReferences(selected.removed) });
      abortSignal.throwIfAborted();
      const date = new Date().toISOString().slice(0, 10);
      const snapshot: SessionContextSnapshot = {
        memory: generated.memory, summary: generated.summary,
        renderedMemory: generated.memory ? `Session memory (recorded ${date})\n${generated.memory}` : "",
        renderedSummary: `Session handoff (recorded ${date})\n${generated.summary}`,
        retainedParts: selected.retainedParts, sourceWatermark: [...cycle.sourceWatermark],
        statistics: { inputTokensBefore: before.inputTokens, inputTokensAfter: 0, outputTokensAfter: 1,
          elapsedMs: 0, auxiliaryInputTokens: generated.auxiliaryInputTokens, auxiliaryOutputTokens: generated.auxiliaryOutputTokens },
      };
      // Include data appended while the auxiliary models were working.
      const latest = await repository.rawContextMessages(threadId, researcherId);
      effective = await this.withSnapshot(request, latest, snapshot);
      const after = modelRequestBudget(effective, selection.model, this.counter);
      if (after.inputTokens >= threshold || after.outputTokens <= 0) throw new ContextCandidateError();
      snapshot.statistics.inputTokensAfter = after.inputTokens;
      snapshot.statistics.outputTokensAfter = after.outputTokens;
      snapshot.statistics.elapsedMs = performance.now() - started;
      abortSignal.throwIfAborted();
      await repository.commitContextCycle(cycle, snapshot, abortSignal);
      this.latestStatistics = { ...snapshot.statistics };
      return effective;
    } finally {
      await repository.releaseContextCycle(cycle);
    }
  }

  private async withSnapshot(request: LanguageModelV3CallOptions, raw: readonly MastraDBMessage[], snapshot: SessionContextSnapshot): Promise<LanguageModelV3CallOptions> {
    const list = new MessageList({ threadId: this.options.threadId, resourceId: this.options.researcherId, logger: noopLogger });
    list.add(restoreContextTail(raw, snapshot), "memory");
    const tail = await list.get.all.aiV6.llmPrompt();
    const prefix = request.prompt.filter((message) => message.role === "system");
    if (snapshot.renderedMemory) prefix.push({ role: "system", content: snapshot.renderedMemory });
    prefix.push({ role: "system", content: snapshot.renderedSummary });
    return { ...request, prompt: [...prefix, ...tail] };
  }
}

/** Exact continuation values are checked after summarization, never reconstructed. */
function continuationReferences(messages: readonly MastraDBMessage[]): string[] {
  const values = new Set<string>();
  function visit(value: unknown): void {
    if (Array.isArray(value)) { value.forEach(visit); return; }
    if (!value || typeof value !== "object") return;
    for (const [key, item] of Object.entries(value)) {
      if (/^(?:run_id|research_run_id|result_id|bundle_id|request_id|dataset_id|release_id|data_generation_id|generation_id|batch_id|track_id|folder_id|cursor|next_cursor|folder_cursor)$/.test(key)
        && typeof item === "string" && item.length) values.add(item);
      else visit(item);
    }
  }
  for (const message of messages) for (const part of message.content.parts) {
    if (part.type === "tool-invocation") { visit(part.toolInvocation.args); visit(part.toolInvocation.result); }
  }
  return [...values];
}
