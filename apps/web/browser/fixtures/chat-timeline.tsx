import { useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Toaster } from "../../src/components/ui/toast";
import { ChatTestProvider } from "../../src/chat/chatTestProvider";
import { ChatConversationView } from "../../src/chat/ChatConversation";
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
        { component: "ResearchRun", id: "run", runId },
      ] } },
    ] },
  } };
}

// Production timeline, deterministic local state; no Auth, Agent or network effects.
function TimelineFixture() {
  const initial = new URLSearchParams(location.search).get("initial");
  const [historyLoaded, setHistoryLoaded] = useState(initial !== "history");
  const [state, setState] = useState("running");
  const [toolRunning, setToolRunning] = useState(false);
  const [sentTurns, setSentTurns] = useState<TimelineTurn[]>(() => initial ? [{
    id: "sent-1", started_at: time, completed_at: initial === "history" ? time : null,
    status: initial === "history" ? "completed" : "running", entries: [
      { entry_id: "sent-1-prompt", turn_id: "sent-1", created_at: time, kind: "user_input", payload: { source: "prompt", content: "Hi", inputId: "sent-1" } },
      ...(initial === "history" ? [{ ...text("sent-1-response", "Hello. How can I help?"), turn_id: "sent-1" }] : []),
    ],
  }] : []);
  const streamedParagraphs = useRef(60);
  const entries = [text("before", "Checking the research context."), tool("first-tool"),
    text("between", "The context is ready. Checking the results."), surface("progress", "running"), tool("second-tool"),
    { entry_id: "question", turn_id: turnId, created_at: time, kind: "question" as const, payload: {
      interrupt_id: turnId + "::ask", status: "answered" as const, question: "Which approach?", options: null, selection_mode: "free_text" as const,
    } },
    { entry_id: "answer", turn_id: turnId, created_at: time, kind: "user_input" as const, payload: {
      source: "answer" as const, content: "Default approach", inputId: turnId,
    } }];
  if (toolRunning) entries.push({ entry_id: "live-tool", turn_id: turnId, created_at: time,
    kind: "tool_activity", payload: { name: "submit_research_run", status: state === "running" ? "running" : "complete" } });
  if (state === "completed") entries.push(surface("result", "succeeded"),
    surface("other-result", "succeeded", "run_abcdef0123456789abcd"), text("final", "Both research tasks finished."), { entry_id: "outcome", turn_id: turnId, created_at: time, kind: "turn_outcome", payload: { status: "completed" } });
  const turn: TimelineTurn = { id: turnId, started_at: time, completed_at: state === "running" ? null : time,
    status: state as TimelineTurn["status"], entries };
  const controller = {
    turns: historyLoaded ? [...(initial ? [] : [turn]), ...sentTurns] : [], phase: (sentTurns.at(-1)?.status ?? state) === "running" ? "active" : "idle", currentTurnId: sentTurns.at(-1)?.id ?? turnId,
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
  return <main style={{ height: "100vh", display: "grid", gridTemplateRows: "auto minmax(0, 1fr)" }}>
    <nav aria-label="Fixture state"><button onClick={() => setState("running")}>Running</button>
      <button onClick={() => setState("completed")}>Complete</button>
      <button onClick={() => setHistoryLoaded(true)}>Load history</button>
      <button onClick={() => setToolRunning(true)}>Start tool</button>
      <button onClick={() => setToolRunning(false)}>Finish tool</button>
      <button onClick={() => setState("failed")}>Fail</button>
      <button onClick={sendNext}>Send next</button>
      <button onClick={() => respond("Hello. How can I help?")}>Short reply</button>
      <button onClick={() => respond("**数据截至：**2026-08-27\n\n`**原文：**保持`", true)}>CJK reply</button>
      <button onClick={() => respond("Hello. How can I help?", true)}>Finish reply</button>
      <button onClick={() => respond("First **paragraph**.\n\nSecond paragraph.\n\n### Section\n\nSection content.\n\n- First item\n- Second item\n\n## Summary\n\nSummary content.", true)}>Typography reply</button>
      <button onClick={() => respond("[X](/research-runs/run_0123456789abcdef0123)", true)}>Run link reply</button>
      <button onClick={() => respond("A longer streamed paragraph.\n\n".repeat(++streamedParagraphs.current))}>Long reply</button></nav>
    <ChatTestProvider controller={controller}><ChatConversationView controller={{ ...controller, action: { enabled: false, kind: "send", label: "Send" }, queue: [], error: null, errorCode: null, draft: "", draftBytes: 0, textareaRef: { current: null }, setDraft: () => {} }} existingSession agentId="default" threadId="fixture" modelControls={null} /></ChatTestProvider><Toaster />
  </main>;
}
function RecoveryFixture() {
  const initial = new URLSearchParams(location.search).get("status");
  const [status, setStatus] = useState<"recovering" | "succeeded" | "failed">(initial === "succeeded" || initial === "failed" ? initial : "recovering");
  const replacementId = "00000000-0000-4000-8000-000000000003";
  const originalId = "00000000-0000-4000-8000-000000000002";
  const entries: TimelineEntry[] = [tool("successful-operation"), { entry_id: `assistant:${originalId}`, turn_id: turnId, created_at: time,
    kind: "assistant_message", payload: { content: "This is the retained partial answer.", status: "complete", recovery: {
      status, cause: "OUTPUT_LIMIT", attempts: 1, replacementMessageId: replacementId, errorCode: status === "failed" ? "RECOVERY_FAILED" : null,
    } } }];
  if (status === "succeeded") entries.push({ entry_id: `assistant:${replacementId}`, turn_id: turnId, created_at: time,
    kind: "assistant_message", payload: { content: "This is the complete replacement answer.", status: "complete", supersedes: originalId } });
  const turn: TimelineTurn = { id: turnId, started_at: time, completed_at: status === "recovering" ? null : time,
    status: status === "recovering" ? "running" : status === "succeeded" ? "completed" : "failed", entries };
  const controller = { turns: [turn], phase: status === "recovering" ? "active" : "idle", currentTurnId: turnId,
    hasFirstAssistantText: true, nextCursor: null, loadingOlder: false, timelineError: false, question: null,
    loadOlder: async () => false, retryTimeline: async () => undefined } as unknown as ChatConversationController;
  const change = (value: typeof status) => { history.replaceState(null, "", `?mode=recovery&status=${value}`); setStatus(value); };
  return <main style={{ height: "100vh", maxWidth: 900, margin: "auto", display: "grid", gridTemplateRows: "auto minmax(0, 1fr)" }}>
    <nav aria-label="Recovery fixture state">
      <button onClick={() => change("recovering")}>Recovering</button><button onClick={() => change("succeeded")}>Recovery succeeded</button>
      <button onClick={() => change("failed")}>Recovery failed</button>
    </nav><ChatTestProvider controller={controller}><ChatTimeline controller={controller} /></ChatTestProvider>
  </main>;
}
createRoot(document.getElementById("root")!).render(new URLSearchParams(location.search).get("mode") === "recovery" ? <RecoveryFixture /> : <TimelineFixture />);
