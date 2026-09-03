import { HttpAgent } from "@ag-ui/client";
import { UseAgentUpdate, useAgent } from "@copilotkit/react-core/v2/headless";
import { useCopilotKit } from "@copilotkit/react-core/v2/context";
import { ArrowUp, WarningCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";

import { createAgentFetch } from "./agentTransport";
import { ChatComposer } from "./ChatComposer";
import { ChatIntroduction, ChatTimeline } from "./ChatTimeline";
import type { ResolvedModelSelection } from "./chatState";
import type { AgentSessionSummary } from "./sessionHistory";
import { useChatConversation } from "./useChatConversation";

const RESEARCH_AGENT_ID = "research";

export function AgentConversation(props: Readonly<{
  existingSession: boolean;
  initialSession?: AgentSessionSummary;
  modelControls: ReactNode;
  onAccepted: () => void;
  onSessionChanged: () => void;
  onTitleMaySettle: (threadId: string) => void;
  researcherId: string;
  selection: ResolvedModelSelection | null;
  titleMaySettle: boolean;
  threadId: string;
}>) {
  const { copilotkit } = useCopilotKit();
  const subscribe = useCallback((notify: () => void) => copilotkit.subscribe({
    onRuntimeConnectionStatusChanged: notify,
  }).unsubscribe, [copilotkit]);
  const snapshot = useCallback(() => copilotkit.runtimeConnectionStatus, [copilotkit]);
  const runtimeStatus = useSyncExternalStore(subscribe, snapshot, snapshot);
  if (runtimeStatus !== "connected") {
    return (
      <StaticChatMain
        error={runtimeStatus === "error" ? "The Research Agent could not be reached." : undefined}
        modelControls={props.modelControls}
        opening={runtimeStatus !== "error"}
      />
    );
  }
  return <ConnectedAgentConversation {...props} />;
}

function ConnectedAgentConversation(props: Parameters<typeof AgentConversation>[0]) {
  const { agent, isReady } = useAgent({
    agentId: `research-chat-${props.threadId}`,
    runtimeAgentId: RESEARCH_AGENT_ID,
    threadId: props.threadId,
    throttleMs: 16,
    updates: [UseAgentUpdate.OnMessagesChanged, UseAgentUpdate.OnRunStatusChanged],
  });
  if (!isReady || !(agent instanceof HttpAgent)) {
    return <StaticChatMain modelControls={props.modelControls} opening />;
  }
  return <AuthoritativeConversation {...props} agent={agent} />;
}

function AuthoritativeConversation({
  agent,
  ...props
}: Parameters<typeof AgentConversation>[0] & Readonly<{ agent: HttpAgent }>) {
  const [announcement, setAnnouncement] = useState("");
  const announcementTimerRef = useRef<number | null>(null);
  const announce = useCallback((message: string) => {
    if (announcementTimerRef.current !== null) window.clearTimeout(announcementTimerRef.current);
    setAnnouncement(message);
    announcementTimerRef.current = window.setTimeout(() => {
      setAnnouncement("");
      announcementTimerRef.current = null;
    }, 2_000);
  }, []);
  useEffect(() => {
    const original = agent.fetch;
    agent.fetch = createAgentFetch(original);
    return () => { agent.fetch = original; };
  }, [agent]);
  useEffect(() => () => {
    if (announcementTimerRef.current !== null) window.clearTimeout(announcementTimerRef.current);
  }, []);
  const controller = useChatConversation({ agent, ...props });
  const newChat = controller.timeline.length === 0 && controller.phase === "new";

  if (newChat) {
    return (
      <main className="chat-main chat-main-new">
        <div className="chat-new-chat-start">
          <ChatIntroduction />
          <ChatComposer announcement={announcement} controller={controller} modelControls={props.modelControls} />
        </div>
      </main>
    );
  }
  return (
    <main
      className="chat-main"
      data-agent-run-id={controller.currentTurnId ?? controller.latestTurnId ?? undefined}
      data-current-turn-id={controller.currentTurnId ?? undefined}
    >
      <ChatTimeline controller={controller} onAnnounce={announce} />
      <ChatComposer announcement={announcement} controller={controller} modelControls={props.modelControls} />
    </main>
  );
}

export function StaticChatMain({
  error,
  modelControls,
  opening = false,
}: {
  error?: string;
  modelControls: ReactNode;
  opening?: boolean;
}) {
  return (
    <main className="chat-main chat-main-new">
      <div className="chat-new-chat-start">
        <ChatIntroduction opening={opening} />
        <div className="chat-composer-dock chat-composer-static">
          <section aria-label="Next Turn settings" className="chat-next-turn-settings">{modelControls}</section>
          {error === undefined ? null : (
            <div className="chat-run-error">
              <WarningCircle aria-hidden="true" size={15} />
              <span>{error}</span>
              <button className="button-quiet" onClick={() => window.location.reload()} type="button">Reconnect</button>
            </div>
          )}
          <div className="chat-composer-input chat-composer-input-locked">
            <textarea aria-label="Message" disabled placeholder="Ask about an investment idea…" rows={2} />
            <button aria-label="Send" className="chat-main-action" disabled type="button">
              <ArrowUp aria-hidden="true" size={18} weight="bold" />
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}
