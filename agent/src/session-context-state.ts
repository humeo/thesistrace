import { createHash } from "node:crypto";
import type { MastraDBMessage } from "@mastra/core/agent";
import { z } from "zod";

const partReference = z.object({ messageId: z.string().min(1), partIndex: z.number().int().nonnegative() }).strict();
const sourceStamp = z.object({
  messageId: z.string().min(1), headerHash: z.string().regex(/^[a-f0-9]{64}$/),
  partHashes: z.array(z.string().regex(/^[a-f0-9]{64}$/)),
}).strict();

export const sessionContextSnapshotSchema = z.object({
  memory: z.string(), summary: z.string().trim().min(1),
  renderedMemory: z.string(), renderedSummary: z.string().min(1),
  retainedParts: z.array(partReference), sourceWatermark: z.array(sourceStamp),
  statistics: z.object({
    inputTokensBefore: z.number().int().nonnegative(), inputTokensAfter: z.number().int().nonnegative(),
    outputTokensAfter: z.number().int().positive(), elapsedMs: z.number().nonnegative(),
    auxiliaryInputTokens: z.number().int().nonnegative(), auxiliaryOutputTokens: z.number().int().nonnegative(),
  }).strict(),
}).strict().superRefine((value, context) => {
  const source = new Map(value.sourceWatermark.map((item) => [item.messageId, item]));
  const retained = new Set<string>();
  if (source.size !== value.sourceWatermark.length) context.addIssue({ code: "custom", message: "Duplicate source identity" });
  for (const part of value.retainedParts) {
    const key = `${part.messageId}:${part.partIndex}`;
    if (retained.has(key) || part.partIndex >= (source.get(part.messageId)?.partHashes.length ?? 0)) {
      context.addIssue({ code: "custom", message: "Invalid retained reference" });
    }
    retained.add(key);
  }
});

export type ContextPartReference = z.infer<typeof partReference>;
export type ContextSourceStamp = z.infer<typeof sourceStamp>;
export type SessionContextSnapshot = z.infer<typeof sessionContextSnapshotSchema>;
export type SessionContextCheckpoint = Readonly<{ revision: number; snapshot: SessionContextSnapshot }>;
export type SessionContextCycle = Readonly<{
  id: string; threadId: string; researcherId: string; runId: string; revision: number;
  checkpoint: SessionContextCheckpoint | null; sourceWatermark: readonly ContextSourceStamp[];
}>;

/** Hashes hold no second plaintext transcript; prefixes allow concurrent part appends. */
export function freezeContextSource(messages: readonly MastraDBMessage[]): ContextSourceStamp[] {
  return messages.map((message) => {
    const { parts, ...header } = message.content;
    return { messageId: message.id,
      headerHash: hash({ role: message.role, createdAt: message.createdAt.toISOString(), content: header }),
      partHashes: parts.map(hash),
    };
  });
}

export function contextSourceMatches(
  frozen: readonly ContextSourceStamp[], current: readonly ContextSourceStamp[],
): boolean {
  const source = new Map(current.map((item) => [item.messageId, item]));
  return current.length >= frozen.length && frozen.every((stamp, index) => {
    const latest = source.get(stamp.messageId);
    return latest !== undefined && current[index]?.messageId === stamp.messageId
      && latest.headerHash === stamp.headerHash && latest.partHashes.length >= stamp.partHashes.length
      && stamp.partHashes.every((value, partIndex) => latest.partHashes[partIndex] === value);
  });
}

function hash(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}
