import { HttpAgent } from "@ag-ui/client";
import { UseAgentUpdate, useAgent } from "@copilotkit/react-core/v2/headless";
import { useCopilotKit } from "@copilotkit/react-core/v2/context";
import { ArrowUp, WarningCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import "../i18n";

import { createAgentFetch } from "./agentTransport";
import { ChatComposer } from "./ChatComposer";
import { ChatIntroduction, ChatTimeline, type ChatAnnouncement } from "./ChatTimeline";
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
  const { t } = useTranslation("chat");
  const { copilotkit } = useCopilotKit();
  const subscribe = useCallback((notify: () => void) => copilotkit.subscribe({
    onRuntimeConnectionStatusChanged: notify,
  }).unsubscribe, [copilotkit]);
  const snapshot = useCallback(() => copilotkit.runtimeConnectionStatus, [copilotkit]);
  const runtimeStatus = useSyncExternalStore(subscribe, snapshot, snapshot);
  const [hasConnected, setHasConnected] = useState(runtimeStatus === "connected");
  useEffect(() => {
    if (runtimeStatus === "connected") setHasConnected(true);
  }, [runtimeStatus]);
  // Once mounted, the conversation owns drafts and authoritative rejection
  // state. A later discovery failure must not discard that local state.
  if (!hasConnected && runtimeStatus !== "connected") {
    return (
      <StaticChatMain
        error={runtimeStatus === "error" ? t("agentUnreachable") : undefined}
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
  const { t } = useTranslation("chat");
  const [announcement, setAnnouncement] = useState<ChatAnnouncement | null>(null);
  const announcementTimerRef = useRef<number | null>(null);
  const announce = useCallback((message: ChatAnnouncement) => {
    if (announcementTimerRef.current !== null) window.clearTimeout(announcementTimerRef.current);
    setAnnouncement(message);
    announcementTimerRef.current = window.setTimeout(() => {
      setAnnouncement(null);
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
  const newChat = controller.turns.length === 0 && controller.phase === "new";

  if (newChat) {
    return (
      <main className="chat-main chat-main-new">
        <div className="chat-new-chat-start">
          <ChatIntroduction />
          <ChatComposer announcement={announcement === null ? "" : t(announcement)} controller={controller} modelControls={props.modelControls} />
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
      <ChatComposer announcement={announcement === null ? "" : t(announcement)} controller={controller} modelControls={props.modelControls} />
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
  const { t } = useTranslation("chat");
  return (
    <main className="chat-main chat-main-new">
      <div className="chat-new-chat-start">
        <ChatIntroduction opening={opening} />
        <div className="chat-composer-dock chat-composer-static">
          {error === undefined ? null : (
            <div className="chat-run-error" role="alert">
              <WarningCircle aria-hidden="true" size={15} />
              <span>{error}</span>
              <button className="button-quiet" onClick={() => window.location.reload()} type="button">{t("reconnect")}</button>
            </div>
          )}
          <div className="chat-composer-surface chat-composer-surface-locked">
            <textarea aria-label={t("message")} disabled placeholder={t("newPlaceholder")} rows={2} />
            <div className="chat-composer-toolbar">
              <div className="chat-composer-toolbar-actions">
                {modelControls}
                <button aria-label={t("send")} className="chat-main-action" disabled type="button">
                  <ArrowUp aria-hidden="true" size={18} weight="bold" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
