import { useState } from "react";
import { createRoot } from "react-dom/client";
import { ChatTimeline } from "../../src/chat/ChatTimeline";
import type { ChatConversationController } from "../../src/chat/useChatConversation";
import type { TimelineEntry, TimelineTurn } from "../../src/chat/chatProtocol";
import "../../src/styles.css";

const turnId = "00000000-0000-4000-8000-000000000001";
const time = "2026-09-06T00:00:00.000Z";
function text(id: string, content: string): TimelineEntry {
  return { entry_id: id, turn_id: turnId, created_at: time, kind: "assistant_message", payload: { content, status: "complete" } };
}
function tool(id: string): TimelineEntry {
  return { entry_id: id, turn_id: turnId, created_at: time, kind: "tool_activity", payload: { name: "get_research_context", status: "complete" } };
}
function surface(id: string, status: string, runId = "run_0123456789abcdef0123"): TimelineEntry {
  return { entry_id: id, turn_id: turnId, created_at: time, kind: "a2ui", payload: {
    activityType: "a2ui-surface", status: "ready", content: { a2ui_operations: [
      { version: "v0.9", createSurface: { catalogId: "urn:thesistrace:a2ui:research:v0.9", surfaceId: id } },
      { version: "v0.9", updateComponents: { surfaceId: id, components: [
        { id: "root", component: "Column", children: ["run"] },
        { id: "run", component: "ResearchRunStatus", runId, status, formula: "rank(close)" },
      ] } },
    ] },
  } };
}

// Production timeline, deterministic local state; no Auth, Agent or network effects.
function TimelineFixture() {
  const [state, setState] = useState("running");
  const [sentTurns, setSentTurns] = useState<TimelineTurn[]>([]);
  const entries = [text("before", "Checking the research context."), tool("first-tool"),
    text("between", "The context is ready. Checking the results."), surface("progress", "running"), tool("second-tool"),
    { entry_id: "question", turn_id: turnId, created_at: time, kind: "question" as const, payload: {
      interrupt_id: turnId + "::ask", status: "answered" as const, question: "Which approach?", options: null, selection_mode: "free_text" as const,
    } },
    { entry_id: "answer", turn_id: turnId, created_at: time, kind: "user_input" as const, payload: {
      source: "answer" as const, content: "Default approach", inputId: turnId,
    } }];
  if (state === "completed") entries.push(surface("result", "succeeded"),
    surface("other-result", "succeeded", "run_abcdef0123456789abcd"), text("final", "Both research tasks finished."), { entry_id: "outcome", turn_id: turnId, created_at: time, kind: "turn_outcome", payload: { status: "completed" } });
  const turn: TimelineTurn = { id: turnId, started_at: time, completed_at: state === "running" ? null : time,
    status: state as TimelineTurn["status"], entries };
  const controller = {
    turns: [turn, ...sentTurns], phase: (sentTurns.at(-1)?.status ?? state) === "running" ? "active" : "idle", currentTurnId: sentTurns.at(-1)?.id ?? turnId,
    hasFirstAssistantText: true, nextCursor: null, loadingOlder: false, timelineError: false,
    question: null, loadOlder: async () => false, retryTimeline: async () => undefined,
  } as unknown as ChatConversationController;
  function sendNext() {
    const id = `sent-${sentTurns.length + 1}`;
    setSentTurns([...sentTurns, { id, started_at: time, completed_at: null, status: "running", entries: [
      { entry_id: `${id}-prompt`, turn_id: id, created_at: time, kind: "user_input", payload: { source: "prompt", content: "Hi", inputId: id } },
    ] }]);
  }
  function respond(content: string, complete = false) {
    setSentTurns((turns) => turns.map((item, index) => index === turns.length - 1 ? {
      ...item, status: complete ? "completed" : "running", completed_at: complete ? time : null,
      entries: [item.entries[0]!, { ...text(`${item.id}-response`, content), turn_id: item.id }],
    } : item));
  }
  return <main style={{ height: "100vh", maxWidth: 900, margin: "auto", display: "grid", gridTemplateRows: "auto minmax(0, 1fr)" }}>
    <nav aria-label="Fixture state"><button onClick={() => setState("running")}>Running</button>
      <button onClick={() => setState("completed")}>Complete</button>
      <button onClick={() => setState("failed")}>Fail</button>
      <button onClick={sendNext}>Send next</button>
      <button onClick={() => respond("Hello. How can I help?")}>Short reply</button>
      <button onClick={() => respond("Hello. How can I help?", true)}>Finish reply</button>
      <button onClick={() => respond("A longer streamed paragraph.\n\n".repeat(60))}>Long reply</button></nav>
    <ChatTimeline controller={controller} onAnnounce={() => undefined} />
  </main>;
}
createRoot(document.getElementById("root")!).render(<TimelineFixture />);
