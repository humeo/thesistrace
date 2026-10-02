import "../../src/styles.css";
import { ModelPicker } from "../../src/chat/ModelPicker";
import { resolveModelSelection } from "../../src/chat/chatState";
import type { AgentModelCatalog } from "../../src/chat/modelCatalog";
import { useRef, useState } from "react";
import { createRoot } from "react-dom/client";

import { ChatTestProvider } from "../../src/chat/chatTestProvider";
import { ChatConversationView } from "../../src/chat/ChatConversation";
import type { ChatConversationController } from "../../src/chat/useChatConversation";
import { formatChatAnswer } from "@thesistrace/contracts/chat-answer";
import { LanguageControls } from "./language-controls";
import type { StagedInput } from "../../src/chat/stagedInputStore";

const noCommand = async () => undefined;

// Mount the production component with browser-local draft state only. This
// fixture has no Agent, persistence, or network commands.
const catalog: AgentModelCatalog = { default_model_key: "luna", models: [
  { key: "luna", display_name: "GPT-5.6 Luna", default_reasoning_effort: "high", reasoning_efforts: ["low", "medium", "high", "xhigh", "max"] },
  { key: "sol", display_name: "GPT-5.6 Sol", default_reasoning_effort: "xhigh", reasoning_efforts: ["low", "medium", "high", "xhigh"] },
] };
function ComposerFixture() {
  const [modelKey, setModelKey] = useState("luna");
  const [effort, setEffort] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState("normal");
  const [selections, setSelections] = useState<readonly string[]>([]);
  const [receipt, setReceipt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [queue, setQueue] = useState<readonly StagedInput[]>([]);
  const question = ["normal", "rejected", "queue"].includes(mode) ? null : {
    interrupt_id: "fixture::question",
    question: mode === "long" ? "Which objective should lead? ".repeat(20) : "Which objective should lead?",
    selection_mode: mode === "multi_select" || mode === "long" ? "multi_select" as const : mode === "free_text" ? "free_text" as const : "single_select" as const,
    options: mode === "free_text" ? null : mode === "long"
      ? Array.from({ length: 20 }, (_, index) => ({ label: `Objective ${index + 1}`, description: "A research objective with enough detail to wrap on a narrow screen." }))
      : [{ label: "Quality", description: "Prioritize durable fundamentals" }, { label: "Risk", description: "Prioritize drawdown control" }],
  };
  const valid = draft.trim().length > 0 || selections.length > 0;
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const controller: ChatConversationController = {
    action: question ? { enabled: valid, kind: "answer", label: "Send answer" } : { enabled: valid, kind: "send", label: "Send" },
    answerSelections: selections,
    currentTurnId: null,
    draft,
    draftBytes: new TextEncoder().encode(draft).byteLength,
    editStaged: async item => { setDraft(item.content); setQueue(items => items.filter(value => value.inputId !== item.inputId)); },
    error,
    errorCode: null,
    executeMainAction: async () => {
      if (mode === "rejected") { setError("Prompt rejected"); return; }
      setReceipt(question ? formatChatAnswer({ selections, text: draft }) : draft);
      setMode("normal"); setDraft(""); setSelections([]);
    },
    focusComposer: () => textareaRef.current?.focus(),
    hasFirstAssistantText: true,
    loadOlder: async () => true,
    loadingOlder: false,
    latestTurnId: null,
    latestTurnStatus: null,
    nextCursor: null,
    phase: question ? "waiting_for_user" : mode === "queue" ? "active" : "new",
    question,
    queue,
    queueLocked: false,
    refresh: noCommand,
    removeStaged: async item => { setQueue(items => items.filter(value => value.inputId !== item.inputId)); },
    retryRecovery: noCommand,
    retryTimeline: noCommand,
    setAnswerSelections: setSelections,
    setDraft,
    steerStaged: async item => { setReceipt(`Steered: ${item.content}`); setQueue(items => items.filter(value => value.inputId !== item.inputId)); },
    stopTurn: async () => { setMode("normal"); setDraft(""); setSelections([]); setReceipt("Stopped"); },
    statusAnnouncement: "Ready.",
    textareaRef,
    turns: [],
    timelineError: false,
  };
  return (
    <>
    <div style={{ position: "absolute", right: 0, top: 0, zIndex: 10 }}><LanguageControls /></div>
    <main style={{ height: "100vh", display: "grid", gridTemplateRows: "auto minmax(0, 1fr)" }}>
      <div>
        <label>Test question mode <select aria-label="Test question mode" value={mode}
          onChange={(event) => { setMode(event.target.value); setDraft(""); setSelections([]); setError(null);
            setQueue(event.target.value === "queue" ? ["First staged prompt\nWith context", "Second staged prompt"].map((content, index) => ({
              content, inputId: `fixture-${index}`, createdAt: "2026-01-01T00:00:00Z", leaseOwner: null, leaseUntil: null,
              researcherId: "fixture", sessionId: "fixture", sequence: index, status: "staged",
            })) : []); }}>
          {["normal", "rejected", "queue", "single_select", "multi_select", "free_text", "long"].map((value) => <option key={value}>{value}</option>)}
        </select></label>
        <p data-answer-receipt style={{ whiteSpace: "pre-wrap" }}>{receipt}</p>
      </div>
    <ChatTestProvider controller={controller}><ChatConversationView
      controller={controller} existingSession={false} agentId="default" threadId="fixture"
      modelControls={<ModelPicker catalog={catalog} selection={resolveModelSelection(catalog, modelKey, effort)}
        onModelChange={key => { setModelKey(key); setEffort(null); }} onReasoningChange={setEffort} />}
    /></ChatTestProvider>
    </main>
    </>
  );
}

createRoot(document.getElementById("root")!).render(<ComposerFixture />);
