import type { MastraDBMessage } from "@mastra/core/agent";
import { ModelInputTokenCounter } from "./model-context.js";
import { contextSourceMatches, freezeContextSource, type ContextPartReference, type ContextSourceStamp } from "./session-context-state.js";

type Boundary = Readonly<{ sourceWatermark: readonly ContextSourceStamp[]; retainedParts: readonly ContextPartReference[] }>;
type Part = Readonly<{ message: MastraDBMessage; reference: ContextPartReference; index: number }>;

/** Select once at compaction; ordinary requests must use restoreContextTail instead. */
export function selectContextHistory(
  messages: readonly MastraDBMessage[],
  options: Readonly<{ recentTokens: number; currentRequestId?: string; fixedMessageIds?: readonly string[]; excludedMessageIds?: readonly string[]; previous?: Boundary }>,
  counter = new ModelInputTokenCounter(),
): Readonly<{ retainedParts: ContextPartReference[]; removedParts: ContextPartReference[]; retained: MastraDBMessage[]; removed: MastraDBMessage[] }> {
  if (!Number.isSafeInteger(options.recentTokens) || options.recentTokens < 1) throw new Error("CONTEXT_TAIL_BUDGET_INVALID");
  const active = options.previous ? effectiveReferences(messages, options.previous) : undefined;
  const keys = active ? new Set(active.map(referenceKey)) : undefined;
  const parts = flatten(messages).filter((item) => !options.excludedMessageIds?.includes(item.message.id) && (!keys || keys.has(referenceKey(item.reference))))
    .map((item, index) => ({ ...item, index }));
  if (options.currentRequestId && !parts.some((item) => item.message.id === options.currentRequestId && item.message.role === "user")) {
    throw new Error("CONTEXT_CURRENT_REQUEST_MISSING");
  }
  const retained = new Set<number>();
  // A reasoning/tool step is one replay unit. Tool identity also binds any
  // representations of the same call across separate durable messages.
  const groups: number[][] = [];
  const calls = new Map<string, number[]>();
  const byMessage = new Map<string, Part[]>();
  for (const item of parts) {
    const group = byMessage.get(item.message.id) ?? [];
    group.push(item); byMessage.set(item.message.id, group);
  }
  for (const message of messages) {
    const messageParts = byMessage.get(message.id) ?? [];
    let step: number[] = [];
    let protocol = false;
    const finish = () => { if (protocol && step.length) groups.push(step); step = []; protocol = false; };
    for (const item of messageParts) {
      const part = message.content.parts[item.reference.partIndex]!;
      if (part.type === "step-start") finish();
      step.push(item.index);
      protocol ||= part.type === "reasoning" || part.type === "tool-invocation" || part.type === "step-start";
      if (part.type === "tool-invocation") {
        const group = calls.get(part.toolInvocation.toolCallId) ?? [];
        group.push(item.index); calls.set(part.toolInvocation.toolCallId, group);
      }
    }
    finish();
    // Top-level attachments/provider data cannot be assigned to a single part.
    // Preserve this whole message rather than duplicating its envelope in E/R.
    if (Object.keys(message.content).some((key) => !["format", "parts", "metadata"].includes(key))) {
      groups.push(messageParts.map((item) => item.index));
    }
  }
  groups.push(...calls.values());
  function closeGroups(set: Set<number>): void {
  let changed = true;
  while (changed) {
    changed = false;
    for (const group of groups) {
      if (!group.some((index) => set.has(index))) continue;
      for (const index of group) if (!set.has(index)) { set.add(index); changed = true; }
    }
  }
  }
  const costs = parts.map((item) => counter.estimateSerialized(item.message.content.parts[item.reference.partIndex]));
  for (let index = parts.length - 1; index >= 0; index--) {
    if (retained.has(index)) continue;
    const candidate = new Set(retained); candidate.add(index); closeGroups(candidate);
    const total = [...candidate].reduce((sum, partIndex) => sum + costs[partIndex]!, 0);
    if (total > options.recentTokens) break;
    for (const partIndex of candidate) retained.add(partIndex);
  }
  for (const item of parts) {
    const part = item.message.content.parts[item.reference.partIndex]!;
    if (item.message.id === options.currentRequestId || options.fixedMessageIds?.includes(item.message.id) || (part.type === "tool-invocation"
      && !["result", "output-error", "output-denied"].includes(part.toolInvocation.state))) retained.add(item.index);
  }
  closeGroups(retained);
  const retainedParts = parts.filter((item) => retained.has(item.index)).map((item) => item.reference);
  const removedParts = parts.filter((item) => !retained.has(item.index)).map((item) => item.reference);
  return { retainedParts, removedParts, retained: project(messages, retainedParts), removed: project(messages, removedParts) };
}

/** R stays fixed; only source parts/messages appended after publication enter N. */
export function restoreContextTail(messages: readonly MastraDBMessage[], boundary: Boundary, excludedMessageIds: readonly string[] = []): MastraDBMessage[] {
  return project(messages, effectiveReferences(messages, boundary).filter((part) => !excludedMessageIds.includes(part.messageId)));
}

/** References always address the immutable source, never a projected message's indices. */
function effectiveReferences(messages: readonly MastraDBMessage[], boundary: Boundary): ContextPartReference[] {
  if (!contextSourceMatches(boundary.sourceWatermark, freezeContextSource(messages))) throw new Error("CONTEXT_SOURCE_CHANGED");
  const counts = new Map(boundary.sourceWatermark.map((stamp) => [stamp.messageId, stamp.partHashes.length]));
  const references = [...boundary.retainedParts];
  for (const message of messages) {
    for (let partIndex = counts.get(message.id) ?? 0; partIndex < message.content.parts.length; partIndex++) {
      references.push({ messageId: message.id, partIndex });
    }
  }
  project(messages, references); // Validate every durable reference before filtering source parts.
  return references;
}

function referenceKey(reference: ContextPartReference): string {
  return JSON.stringify([reference.messageId, reference.partIndex]);
}

function flatten(messages: readonly MastraDBMessage[]): Part[] {
  if (new Set(messages.map((m) => m.id)).size !== messages.length) throw new Error("CONTEXT_DUPLICATE_MESSAGE");
  const parts: Part[] = [];
  for (const message of messages) for (let partIndex = 0; partIndex < message.content.parts.length; partIndex++) {
    parts.push({ message, reference: { messageId: message.id, partIndex }, index: parts.length });
  }
  return parts;
}

function project(messages: readonly MastraDBMessage[], references: readonly ContextPartReference[]): MastraDBMessage[] {
  const messageIds = new Set(messages.map((message) => message.id));
  const selected = new Map<string, Set<number>>();
  for (const reference of references) {
    if (!messageIds.has(reference.messageId)) throw new Error("CONTEXT_RETAINED_REFERENCE_INVALID");
    const indices = selected.get(reference.messageId) ?? new Set<number>();
    indices.add(reference.partIndex); selected.set(reference.messageId, indices);
  }
  return messages.flatMap((message) => {
    const indices = selected.get(message.id);
    if (!indices?.size) return [];
    const parts = message.content.parts.filter((_, index) => indices.has(index));
    if (parts.length !== indices.size) throw new Error("CONTEXT_RETAINED_REFERENCE_INVALID");
    return [{ ...message, content: { ...message.content, parts } }];
  });
}
