import { useRef, useState } from "react";
import { createRoot } from "react-dom/client";

import { ChatComposer } from "../../src/chat/ChatComposer";
import type { ChatConversationController } from "../../src/chat/useChatConversation";

const noCommand = async () => undefined;

// Mount the production component with browser-local draft state only. This
// fixture has no Agent, persistence, or network commands.
function ComposerFixture() {
  const [draft, setDraft] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const controller: ChatConversationController = {
    action: { enabled: draft.trim().length > 0, kind: "send", label: "Send" },
    answerSelections: [],
    currentTurnId: null,
    draft,
    draftBytes: new TextEncoder().encode(draft).byteLength,
    editStaged: noCommand,
    error: null,
    errorCode: null,
    executeMainAction: noCommand,
    focusComposer: () => textareaRef.current?.focus(),
    hasFirstAssistantText: true,
    loadOlder: async () => true,
    loadingOlder: false,
    latestTurnId: null,
    latestTurnStatus: null,
    nextCursor: null,
    phase: "new",
    question: null,
    queue: [],
    queueLocked: false,
    refresh: noCommand,
    removeStaged: noCommand,
    retryRecovery: noCommand,
    retryTimeline: noCommand,
    setAnswerSelections: () => undefined,
    setDraft,
    steerStaged: noCommand,
    statusAnnouncement: "Ready.",
    textareaRef,
    turns: [],
    timelineError: false,
  };
  return (
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
  );
}

createRoot(document.getElementById("root")!).render(<ComposerFixture />);
