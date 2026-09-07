import type { MastraDBMessage } from "@mastra/core/agent";
import { isCanonicalUuid } from "./uuid.js";

const prefix = "session-run-context:";
export function sessionControlMessageId(runId: string): string { return `${prefix}${runId}`; }
export function isSessionControlMessageId(id: string): boolean {
  return id.startsWith(prefix) && isCanonicalUuid(id.slice(prefix.length));
}
export function sessionControlMessage(options: Readonly<{ runId: string; threadId: string; researcherId: string;
  continueIntent: boolean; createdAt: Date }>): MastraDBMessage {
  return { id: sessionControlMessageId(options.runId), role: "assistant", threadId: options.threadId,
    resourceId: options.researcherId, createdAt: options.createdAt,
    content: { format: 2, parts: [{ type: "text", text: `Agent Run identity: ${options.runId}.` + (options.continueIntent
      ? "\nContinue the work the user explicitly stopped. Reconstruct the next useful step from authoritative memory; do not invent a new user message." : "") }] } };
}
