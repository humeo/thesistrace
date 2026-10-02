import type { ActivityMessage, Message } from "@ag-ui/core";
import type { TimelineEntry, TimelineTurn } from "./chatProtocol";
import { progressHistory } from "./progressHistory";

export const WORK_ACTIVITY = "quantgrove-work-history";
export const ENTRY_ACTIVITY = "quantgrove-timeline-entry";
export type ChatViewMessage = Message & { entry?: TimelineEntry; timestamp?: string };
export type WorkContent = { turn: TimelineTurn; entries: readonly TimelineEntry[] };
export type EntryContent = { entry: TimelineEntry; answer?: { content: string } };

/** Adapt the persisted product timeline to the chat library's current message contract. */
export function chatViewMessages(turns: readonly TimelineTurn[]): ChatViewMessage[] {
  return turns.flatMap(turn => {
    const hidden = progressHistory(turn);
    const entries = turn.entries.filter(entry => !hidden.has(entry.entry_id));
    const lastTool = entries.reduce((last, entry, index) => entry.kind === "tool_activity" || entry.kind === "question" && entry.payload.status !== "pending" ? index : last, -1);
    const ended = ["completed", "failed", "stopped"].includes(turn.status);
    const process = entries.filter((entry, index) => entry.kind === "tool_activity"
      || entry.kind === "question" && entry.payload.status !== "pending"
      || entry.kind === "user_input" && entry.payload.source === "answer"
      || entry.kind === "assistant_message" && !entry.payload.recovery && (index < lastTool || !ended && lastTool >= 0));
    const processIds = new Set(process.map(entry => entry.entry_id));
    const result = entries.filter(entry => !processIds.has(entry.entry_id));
    const firstResponse = result.findIndex(entry => entry.kind !== "user_input");
    const split = firstResponse === -1 ? result.length : firstResponse;
    const finalAssistant = [...result].reverse().find(entry => entry.kind === "assistant_message");
    const work: ActivityMessage = { id: `work:${turn.id}`, role: "activity", activityType: WORK_ACTIVITY, content: { turn, entries: process } };
    return [
      ...projectChatEntries(result.slice(0, split)),
      ...(process.length > 0 || firstResponse !== -1 ? [work] : []),
      ...projectChatEntries(result.slice(split)).map(message => message.id === finalAssistant?.entry_id
        ? { ...message, timestamp: turn.completed_at ?? undefined } : message),
    ];
  });
}

export function projectChatEntries(entries: readonly TimelineEntry[]): ChatViewMessage[] {
  const answers = new Map<string, string>();
  let questionId: string | undefined;
  for (const entry of entries) {
    if (entry.kind === "question") questionId = entry.entry_id;
    if (entry.kind === "user_input" && entry.payload.source === "answer" && questionId !== undefined) {
      answers.set(questionId, entry.payload.content);
      questionId = undefined;
    }
  }
  return entries.flatMap((entry): ChatViewMessage[] => {
    if (entry.kind === "user_input") {
      if (entry.payload.source === "answer") return [];
      return [{ id: entry.entry_id, role: "user", content: entry.payload.content, entry, timestamp: entry.created_at }];
    }
    if (entry.kind === "assistant_message") {
      return [{ id: entry.entry_id, role: "assistant", content: entry.payload.content, entry }];
    }
    if (entry.kind === "a2ui") return [{ id: entry.entry_id, role: "activity", activityType: entry.payload.activityType, content: entry.payload.content }];
    if (entry.kind === "turn_outcome" && entry.payload.status === "completed") return [];
    return [{ id: entry.entry_id, role: "activity", activityType: ENTRY_ACTIVITY, content: { entry, answer: entry.kind === "question" && answers.has(entry.entry_id) ? { content: answers.get(entry.entry_id) } : undefined } }];
  });
}
