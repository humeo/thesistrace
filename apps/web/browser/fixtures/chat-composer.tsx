import { useRef, useState } from "react";
import { createRoot } from "react-dom/client";

import { ChatComposer } from "../../src/chat/ChatComposer";
import type { ChatConversationController } from "../../src/chat/useChatConversation";
import { formatChatAnswer } from "@thesistrace/contracts/chat-answer";

const noCommand = async () => undefined;

// Mount the production component with browser-local draft state only. This
// fixture has no Agent, persistence, or network commands.
function ComposerFixture() {
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState("normal");
  const [selections, setSelections] = useState<readonly string[]>([]);
  const [receipt, setReceipt] = useState("");
  const question = mode === "normal" ? null : {
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
    editStaged: noCommand,
    error: null,
    errorCode: null,
    executeMainAction: async () => {
      if (!question) return;
      setReceipt(formatChatAnswer({ selections, text: draft }));
      setMode("normal"); setDraft(""); setSelections([]);
    },
    focusComposer: () => textareaRef.current?.focus(),
    hasFirstAssistantText: true,
    loadOlder: async () => true,
    loadingOlder: false,
    latestTurnId: null,
    latestTurnStatus: null,
    nextCursor: null,
    phase: question ? "waiting_for_user" : "new",
    question,
    queue: [],
    queueLocked: false,
    refresh: noCommand,
    removeStaged: noCommand,
    retryRecovery: noCommand,
    retryTimeline: noCommand,
    setAnswerSelections: setSelections,
    setDraft,
    steerStaged: noCommand,
    stopTurn: async () => { setMode("normal"); setDraft(""); setSelections([]); setReceipt("Stopped"); },
    statusAnnouncement: "Ready.",
    textareaRef,
    turns: [],
    timelineError: false,
  };
  return (
    <main className="chat-main">
      <div className="chat-timeline-shell">
        <label>Test question mode <select aria-label="Test question mode" value={mode}
          onChange={(event) => { setMode(event.target.value); setDraft(""); setSelections([]); }}>
          {["normal", "single_select", "multi_select", "free_text", "long"].map((value) => <option key={value}>{value}</option>)}
        </select></label>
        <p data-answer-receipt style={{ whiteSpace: "pre-wrap" }}>{receipt}</p>
      </div>
    <ChatComposer
      announcement=""
      controller={controller}
      modelControls={(
        <div className="chat-model-picker">
          <button aria-label="Model and reasoning" className="chat-model-picker-trigger" type="button">
            <strong>GPT-5.6 Luna</strong><span>High</span>
          </button>
        </div>
      )}
    />
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<ComposerFixture />);
