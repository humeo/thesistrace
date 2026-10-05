import { HttpAgent } from "@ag-ui/client";
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { ChatConversationView } from "../../src/chat/ChatConversation";
import { ChatTestProvider } from "../../src/chat/chatTestProvider";
import { useChatConversation } from "../../src/chat/useChatConversation";
import type { TimelineTurn } from "../../src/chat/chatProtocol";
import type { AgentSessionSummary } from "../../src/chat/sessionHistory";
import "../../src/styles.css";

const threadId = "00000000-0000-4000-8000-000000000501";
const researcherId = "00000000-0000-4000-8000-000000000502";
const time = "2026-10-04T00:00:00.000000Z";
const query = new URLSearchParams(location.search);
const historySize = Number(query.get("history") ?? 0);
const timelineDelay = Number(query.get("timelineDelay") ?? 600);
const firstSnapshotDelay = Number(query.get("firstSnapshotDelay") ?? 0);
const newSession = query.get("new") === "true";
const formatted = query.get("format") === "markdown";
const withTool = query.get("tool") === "true";
const cardCount = Number(query.get("cards") ?? 0);
const researchIds = Array.from({ length: cardCount }, (_, index) => `run_${String(index + 1).repeat(20)}`);
const historyText = "A research finding with **emphasis** and `rank(close)`.\n\n".repeat(32);
const history: TimelineTurn[] = Array.from({ length: historySize }, (_, index) => {
  const id = `00000000-0000-4000-8000-${String(index + 600).padStart(12, "0")}`;
  return { id, status: "completed", started_at: time, completed_at: time, entries: [
    { entry_id: `prompt-${id}`, turn_id: id, created_at: time, kind: "user_input", payload: { content: `Research question ${index}`, inputId: id, source: "prompt" } },
    ...(index === historySize - 1 && cardCount ? [{ entry_id: `research-${id}`, turn_id: id, created_at: time, kind: "a2ui" as const,
      payload: { activityType: "a2ui-surface", status: "ready", content: { a2ui_operations: [
        { version: "v0.9", createSurface: { catalogId: "urn:thesistrace:a2ui:research:v0.9", surfaceId: "performance-research" } },
        { version: "v0.9", updateComponents: { surfaceId: "performance-research", components: [
          { component: "ResearchComparison", id: "root", runIds: researchIds },
        ] } },
      ] } } }] : []),
    { entry_id: `assistant:${id}`, turn_id: id, created_at: time, kind: "assistant_message", payload: { content: historyText, status: "complete" } },
  ] };
});
let current: TimelineTurn | null = null;
const metrics = { acceptedAt: 0, firstChunkAt: 0, finishedAt: 0, timelineRequests: 0, chunks: 0, previewAt: 0, formattedTextEndAt: 0 };
Object.assign(window, { chatPerformanceSource: metrics });

function summary(): AgentSessionSummary {
  const turn = current === null ? null : { id: current.id, kind: "prompt" as const, model_key: "fixture", reasoning_effort: "low",
    question: null, started_at: current.started_at, status: current.status, terminal_error_code: null };
  return { id: threadId, title: "Performance fixture", created_at: time, activity_at: time, version: "2026-10-04T00:00:00.000Z",
    message_title: null, current_turn: current?.status === "running" ? turn : null, latest_turn: turn };
}

// Public HTTP contracts and a deterministic SSE source, without a model or server.
const originalFetch = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const url = String(input);
  if (url.includes("/api/research-runs/")) return Response.json({ id: url.split("/").at(-1), name: "Research result",
    status: "succeeded", research_kind: "strategy_backtest", formula_summary: "rank(close)", start_date: "2026-01-01", end_date: "2026-09-01" });
  if (!url.includes(`/api/agent/sessions/${threadId}`)) return originalFetch(input, init);
  if (url.includes("/timeline")) {
    metrics.timelineRequests++;
    const snapshot = JSON.stringify({ next_cursor: null, turns: [...history, ...(current ? [current] : [])].slice(-20) });
    await new Promise(resolve => setTimeout(resolve, timelineDelay));
    return new Response(snapshot, { headers: { "content-type": "application/json" } });
  }
  return Response.json(summary());
};

function Fixture() {
  const [existingSession, setExistingSession] = useState(!newSession);
  const [agent] = useState(() => new HttpAgent({ threadId, url: "/deterministic-agent", fetch: async (_url, init) => {
    const request = JSON.parse(String(init.body));
    const runId = request.runId;
    const input = request.messages.at(-1);
    const messageId = "00000000-0000-4000-8000-000000000503";
    const startedAt = new Date().toISOString().replace("Z", "000Z");
    current = { id: runId, status: "running", started_at: startedAt, completed_at: null, entries: [
      { entry_id: `user:${input.id}`, turn_id: runId, created_at: startedAt, kind: "user_input", payload: { content: input.content, inputId: input.id, source: "prompt" } },
      ...(withTool ? [{ entry_id: "tool:read", turn_id: runId, created_at: startedAt, kind: "tool_activity" as const,
        payload: { name: "get_research_context", status: "complete" as const } }] : []),
    ] };
    const encoder = new TextEncoder();
    return new Response(new ReadableStream<Uint8Array>({ start(stream) {
      const emit = (event: Record<string, unknown>) => stream.enqueue(encoder.encode(`data: ${JSON.stringify({ timestamp: Date.now(), ...event })}\n\n`));
      metrics.acceptedAt = performance.now();
      emit({ type: "RUN_STARTED", threadId, runId });
      setTimeout(() => {
      emit({ type: "CUSTOM", name: "chat_timeline_update", value: { session: summary(), timeline: { next_cursor: null, turns: [current] } } });
      emit({ type: "TEXT_MESSAGE_START", messageId, role: "assistant" });
      let content = "";
      const answer = "First reply.\n\n- **Incremental formatted reply " + "with a longer explanation that remains readable as it arrives. ".repeat(6).trimEnd()
        + "**\n\n| Research | Status |\n| --- | --- |\n| Momentum | Completed |\n\n[View research](/research-runs/run_11111111111111111111)";
      const parts = formatted ? answer.match(/[\s\S]{1,12}/g)!
        : ["First reply. ", ...Array.from({ length: 49 }, (_, index) => `Part ${index + 1} of the streamed answer. `)];
      const timer = setInterval(() => {
        const delta = parts.shift();
        if (delta !== undefined) {
          if (!metrics.firstChunkAt) metrics.firstChunkAt = performance.now();
          metrics.chunks++;
          content += delta;
          if (!metrics.previewAt && content.includes("Incremental formatted reply")) metrics.previewAt = performance.now();
          if (!metrics.formattedTextEndAt && content.includes("arrives.**")) metrics.formattedTextEndAt = performance.now();
          current = { ...current!, entries: [...current!.entries.filter(entry => entry.kind !== "assistant_message"), { entry_id: `assistant:${messageId}`, turn_id: runId,
            created_at: startedAt, kind: "assistant_message", payload: { content, status: "streaming" } }] };
          emit({ type: "TEXT_MESSAGE_CONTENT", messageId, delta });
          emit({ type: "CUSTOM", name: "chat_timeline_update", value: { session: summary(), timeline: { next_cursor: null, turns: [current] } } });
        } else {
          clearInterval(timer);
          current = { ...current!, status: "completed", completed_at: new Date().toISOString().replace("Z", "000Z"),
            entries: current!.entries.map(entry => entry.kind === "assistant_message" ? { ...entry, payload: { ...entry.payload, status: "complete" } } : entry) };
          metrics.finishedAt = performance.now();
          emit({ type: "TEXT_MESSAGE_END", messageId });
          emit({ type: "CUSTOM", name: "chat_timeline_update", value: { session: summary(), timeline: { next_cursor: null, turns: [current] } } });
          emit({ type: "RUN_FINISHED", threadId, runId });
          stream.close();
        }
      }, formatted ? 75 : 40);
      }, firstSnapshotDelay);
    } }), { headers: { "content-type": "text/event-stream" } });
  } }));
  const controller = useChatConversation({ agent, existingSession, initialSession: newSession ? undefined : summary(), researcherId, threadId,
    selection: { model: { key: "fixture", display_name: "Fixture", default_reasoning_effort: "low", reasoning_efforts: ["low"] }, reasoningEffort: "low", selectionMode: "manual" },
    onAccepted: () => setExistingSession(true), onSessionChanged: () => {}, onTitleMaySettle: () => {}, titleMaySettle: false });
  return <ChatTestProvider><div style={{ height: "100vh" }}><ChatConversationView controller={controller} modelControls={null}
    existingSession={existingSession} agentId="default" threadId={threadId} /></div></ChatTestProvider>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
