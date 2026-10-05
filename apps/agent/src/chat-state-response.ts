import type { TimelinePage } from "./chat-control.js";
import type { SessionSummary } from "./session-repository.js";

/** The same browser-safe public state is used by HTTP history and live AG-UI. */
export function sessionResponse(session: SessionSummary) {
  return {
    activity_at: session.activityAt,
    created_at: session.createdAt,
    current_turn: turnResponse(session.currentTurn),
    id: session.id,
    latest_turn: turnResponse(session.latestTurn),
    message_title: session.messageTitle,
    title: session.title,
    version: session.version,
  };
}

function turnResponse(turn: SessionSummary["latestTurn"]) {
  return turn === null ? null : {
    id: turn.id,
    kind: turn.kind,
    model_key: turn.modelKey,
    question: turn.question === null ? null : {
      interrupt_id: turn.question.interruptId,
      options: turn.question.options,
      question: turn.question.question,
      selection_mode: turn.question.selectionMode,
    },
    reasoning_effort: turn.reasoningEffort,
    started_at: turn.startedAt,
    status: turn.status,
    terminal_error_code: turn.terminalErrorCode,
  };
}

export function timelineResponse(page: TimelinePage) {
  return {
    next_cursor: page.nextCursor,
    turns: page.turns.map((turn) => ({
      completed_at: turn.completedAt,
      entries: turn.entries.map((entry) => ({
        created_at: entry.createdAt,
        entry_id: entry.entryId,
        kind: entry.kind,
        payload: entry.kind !== "question" ? entry.payload : {
          interrupt_id: entry.payload.interruptId,
          options: entry.payload.options,
          question: entry.payload.question,
          selection_mode: entry.payload.selectionMode,
          status: entry.payload.status,
        },
        turn_id: entry.turnId,
      })),
      id: turn.id,
      started_at: turn.startedAt,
      status: turn.status,
    })),
  };
}
