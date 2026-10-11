import { HttpAgent } from "@ag-ui/client";
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { useChatConversation } from "../../src/chat/useChatConversation";
import type { TimelineTurn } from "../../src/chat/chatProtocol";
import type { AgentSessionSummary } from "../../src/chat/sessionHistory";
import { StagedInputStore } from "../../src/chat/stagedInputStore";

const threadId = "00000000-0000-4000-8000-000000000801";
const researcherId = "00000000-0000-4000-8000-000000000802";
const query = new URLSearchParams(location.search);
const observerRun = query.get("observe");
const time = "2026-10-09T00:00:00.000000Z";
let current: TimelineTurn | null = observerRun ? { id: observerRun, status: "running", started_at: time, completed_at: null, entries: [] } : null;
let completeStream: (() => void) | null = null;
const probe = { prompts: [] as { runId: string; inputId: string; content: string }[], metadataReads: 0 };
Object.assign(window, { queueCompletionProbe: probe });
let releaseAcceptance = () => {};
if (query.has("hold-accepted")) {
  const gate = new Promise<void>(resolve => { releaseAcceptance = resolve; });
  const removeAccepted = StagedInputStore.prototype.removeAccepted;
  StagedInputStore.prototype.removeAccepted = async function (item) {
    await gate;
    await removeAccepted.call(this, item);
  };
}

function summary(): AgentSessionSummary {
  const turn = current && { id: current.id, kind: "prompt" as const, model_key: "fixture", reasoning_effort: "low", question: null,
    status: current.status, started_at: current.started_at, terminal_error_code: null };
  return { id: threadId, title: "Queued research", message_title: null, created_at: time, activity_at: time, version: "2026-10-09T00:00:00.000Z",
    current_turn: current?.status === "running" ? turn : null, latest_turn: turn };
}
const originalFetch = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const url = String(input);
  if (!url.includes(`/api/agent/sessions/${threadId}`)) return originalFetch(input, init);
  if (!url.includes("/timeline")) probe.metadataReads++;
  // Normal transport completion must not wait for this unavailable read endpoint.
  if (!observerRun && probe.prompts.length) return new Promise<Response>(() => {});
  return Response.json(url.includes("/timeline") ? { next_cursor: null, turns: current ? [current] : [] } : summary());
};

function Fixture() {
  const [agent] = useState(() => new HttpAgent({ threadId, url: "/queue-agent", fetch: async (_url, init) => {
    const request = JSON.parse(String(init.body));
    const input = request.messages.at(-1);
    probe.prompts.push({ runId: request.runId, inputId: input.id, content: input.content });
    current = { id: request.runId, status: "running", started_at: time, completed_at: null, entries: [{
      entry_id: `user:${input.id}`, turn_id: request.runId, created_at: time, kind: "user_input",
      payload: { content: input.content, inputId: input.id, source: "prompt" },
    }] };
    const encoder = new TextEncoder();
    return new Response(new ReadableStream<Uint8Array>({ start(stream) {
      const emit = (event: Record<string, unknown>) => stream.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
      const project = () => emit({ type: "CUSTOM", name: "chat_timeline_update", value: {
        session: summary(), timeline: { next_cursor: null, turns: [current] },
      } });
      emit({ type: "RUN_STARTED", threadId, runId: request.runId });
      project();
      completeStream = () => {
        current = { ...current!, status: "completed", completed_at: time };
        project();
        project(); // Duplicate completion notification must not send twice.
        emit({ type: "RUN_FINISHED", threadId, runId: request.runId });
        stream.close();
        completeStream = null;
      };
      if (query.has("fast") && probe.prompts.length > 1) completeStream();
    } }), { headers: { "content-type": "text/event-stream" } });
  } }));
  const controller = useChatConversation({ agent, existingSession: true, initialSession: summary(), researcherId, threadId,
    selection: { model: { key: "fixture", display_name: "Fixture", default_reasoning_effort: "low", reasoning_efforts: ["low"] },
      reasoningEffort: "low", selectionMode: "manual" },
    onAccepted: () => {}, onSessionChanged: () => {}, onTitleMaySettle: () => {}, titleMaySettle: false });
  return <main>
    <h1>Queued research</h1>
    <p role="status">{controller.phase}</p>
    <span aria-label="Latest turn">{controller.latestTurnStatus}</span>
    <label>Message<textarea value={controller.draft} onChange={event => controller.setDraft(event.target.value)} /></label>
    <button disabled={!controller.action.enabled} onClick={() => { void controller.executeMainAction(); }}>{controller.action.kind}</button>
    <ul aria-label="Queue">{controller.queue.map(item => <li key={item.inputId}>{item.content}</li>)}</ul>
    <button onClick={() => {
      if (completeStream) completeStream();
      else if (current) { current = { ...current, status: "completed", completed_at: time }; void controller.refresh(); }
    }}>Complete current run</button>
    <button onClick={releaseAcceptance}>Finish accepted-input cleanup</button>
    {controller.error ? <p role="alert">{controller.error}</p> : null}
  </main>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
