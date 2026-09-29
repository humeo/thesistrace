import { cn } from "cn";
import { chatLayout } from "./chatLayout";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
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
      <main className={cn("chat-main chat-main-new", chatLayout.main, chatLayout.newMain)}>
        <div className={cn("chat-new-chat-start", chatLayout.start)}>
          <ChatIntroduction />
          <ChatComposer announcement={announcement === null ? "" : t(announcement)} controller={controller} modelControls={props.modelControls} />
        </div>
      </main>
    );
  }
  return (
    <main
      className={cn("chat-main", chatLayout.main, chatLayout.conversationMain)}
      data-agent-run-id={controller.currentTurnId ?? controller.latestTurnId ?? undefined}
      data-current-turn-id={controller.currentTurnId ?? undefined}
    >
      <header className={chatLayout.header}>
        <h1 className="min-w-0 truncate text-base leading-6 font-semibold" title={props.initialSession?.title}>{props.initialSession?.title && props.initialSession.title !== "Untitled" ? props.initialSession.title : t("session")}</h1>
      </header>
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
    <main className={cn("chat-main chat-main-new", chatLayout.main, chatLayout.newMain)}>
      <div className={cn("chat-new-chat-start", chatLayout.start)}>
        <ChatIntroduction opening={opening} />
        <div className={cn("chat-composer-dock", chatLayout.dock)}>
          {error === undefined ? null : (
            <div className="mb-3 flex items-center gap-3 rounded-lg border border-destructive p-3 text-sm text-destructive" role="alert">
              <WarningCircle aria-hidden="true" size={15} />
              <span>{error}</span>
              <Button variant="ghost" onClick={() => window.location.reload()} type="button">{t("reconnect")}</Button>
            </div>
          )}
          <div className={cn(chatLayout.surface, "opacity-60")}>
            <Textarea className={chatLayout.input} aria-label={t("message")} disabled placeholder={t("newPlaceholder")} rows={1} />
            <div className="flex min-h-12 items-center justify-between gap-3 px-3 pb-2 min-[769px]:min-h-10">
              <div className="ml-auto flex min-w-0 items-center gap-2">
                {modelControls}
                <Button size="icon" aria-label={t("send")} disabled type="button">
                  <ArrowUp aria-hidden="true" size={18} weight="bold" />
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
