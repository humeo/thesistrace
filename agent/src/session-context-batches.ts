import type { MastraDBMessage } from "@mastra/core/agent";
import { AgentRunFailure } from "./run-failure.js";
import type { ContextPartReference } from "./session-context-state.js";

type Fits = (messages: MastraDBMessage[]) => Promise<boolean>;

/** A cycle-local reader. Only auxiliary requests contain fragments; source history stays intact. */
export class ContextEvidenceBatches {
  private readonly groups: MastraDBMessage[][];
  private groupIndex = 0;
  private offset = 0;
  constructor(messages: readonly MastraDBMessage[], private readonly sourceParts?: readonly ContextPartReference[]) {
    this.groups = groupContextEvidence(messages);
  }

  assertComplete(): void {
    if (this.groupIndex !== this.groups.length || this.offset !== 0) throw new AgentRunFailure("CONTEXT_COMPACTION_FAILED");
  }

  async next(fits: Fits, signal: AbortSignal): Promise<MastraDBMessage[] | null> {
    signal.throwIfAborted();
    if (this.groupIndex === this.groups.length) return null;
    if (!(await fits([]))) throw new AgentRunFailure("CONTEXT_COMPACTION_FAILED");
    signal.throwIfAborted();
    if (this.offset) return this.fragment(fits, signal);
    let end = this.groupIndex;
    let batch: MastraDBMessage[] = [];
    while (end < this.groups.length) {
      const candidate = [...batch, ...this.groups[end]!];
      if (!(await fits(candidate))) break;
      signal.throwIfAborted();
      batch = candidate;
      end++;
    }
    if (batch.length) { this.groupIndex = end; return batch; }
    return this.fragment(fits, signal);
  }

  private async fragment(fits: Fits, signal: AbortSignal): Promise<MastraDBMessage[]> {
    const group = this.groups[this.groupIndex]!;
    const source = JSON.stringify(group);
    const ids = new Set(group.map((message) => message.id));
    const sources = this.sourceParts?.filter((part) => ids.has(part.messageId))
      ?? group.flatMap((message) => message.content.parts.map((_, partIndex) => ({ messageId: message.id, partIndex })));
    const build = (end: number): MastraDBMessage[] => [{
      id: `context-source-${this.groupIndex}-${this.offset}`, role: "user", createdAt: group[0]!.createdAt,
      content: { format: 2, parts: [{ type: "text", text: JSON.stringify({
        kind: "session-context-source-fragment", sources, encoding: "JSON with UTF-16 offsets",
        offset: this.offset, end, total: source.length, content: source.slice(this.offset, end),
      }) }] },
    }];
    // Token estimates are monotonic enough for a bounded search; final fit is always checked.
    let lower = this.offset, upper = source.length;
    while (lower < upper) {
      signal.throwIfAborted();
      const middle = Math.ceil((lower + upper) / 2);
      if (await fits(build(unicodeBoundary(source, middle)))) lower = middle;
      else upper = middle - 1;
    }
    const end = unicodeBoundary(source, lower);
    if (end <= this.offset || !(await fits(build(end)))) throw new AgentRunFailure("CONTEXT_COMPACTION_FAILED");
    signal.throwIfAborted();
    const batch = build(end);
    if (end === source.length) { this.groupIndex++; this.offset = 0; }
    else this.offset = end;
    return batch;
  }
}

function unicodeBoundary(text: string, end: number): number {
  const before = text.charCodeAt(end - 1), after = text.charCodeAt(end);
  return before >= 0xd800 && before <= 0xdbff && after >= 0xdc00 && after <= 0xdfff ? end - 1 : end;
}

/** Keep each message and every intervening message of a cross-message tool exchange together. */
export function groupContextEvidence(messages: readonly MastraDBMessage[]): MastraDBMessage[][] {
  const lastCall = new Map<string, number>();
  messages.forEach((message, index) => {
    for (const part of message.content.parts) if (part.type === "tool-invocation") lastCall.set(part.toolInvocation.toolCallId, index);
  });
  const groups: MastraDBMessage[][] = [];
  for (let first = 0; first < messages.length;) {
    let last = first;
    for (let index = first; index <= last; index++) {
      for (const part of messages[index]!.content.parts) if (part.type === "tool-invocation") {
        last = Math.max(last, lastCall.get(part.toolInvocation.toolCallId)!);
      }
    }
    groups.push(messages.slice(first, last + 1));
    first = last + 1;
  }
  return groups;
}
