import { Alert, Button, Flex, Typography } from "antd";
import { Prompts, Sender, Welcome } from "@ant-design/x";
import { ChartLine, ClockCounterClockwise, Flask, Scales } from "@phosphor-icons/react";
import { ChatUiProvider } from "./ChatUiProvider";
import { HttpAgent } from "@ag-ui/client";
import { UseAgentUpdate, useAgent } from "@copilotkit/react-core/v2/headless";
import { useCopilotKit } from "@copilotkit/react-core/v2/context";
import { useCallback, useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import "../i18n";

import { Brand } from "../brand/Brand";
import { createAgentFetch } from "./agentTransport";
import { ChatComposer } from "./ChatComposer";
import { ChatTimeline } from "./ChatTimeline";
import type { ResolvedModelSelection } from "./chatState";
import type { AgentSessionSummary } from "./sessionHistory";
import type { ChatConversationController } from "./useChatConversation";
import { useChatConversation } from "./useChatConversation";

const RESEARCH_AGENT_ID = "research";
const STARTER_PROMPTS = [
  { key: "factor", Icon: Flask },
  { key: "strategy", Icon: ChartLine },
  { key: "compare", Icon: Scales },
  { key: "tracking", Icon: ClockCounterClockwise },
] as const;

function ChatWelcome() {
  const { t } = useTranslation("chat");
  return <Welcome
    icon={<span className="flex items-center gap-2 text-xl font-semibold"><Brand inverse size={24} /></span>}
    title={t("introTitle")}
    variant="borderless"
    styles={{ root: { flexDirection: "column", alignItems: "center", textAlign: "center", minWidth: 0 }, icon: { height: "auto" } }}
  />;
}

function ChatStarterCards({ disabled = false, onSelect }: {
  disabled?: boolean;
  onSelect?: (prompt: string) => void;
}) {
  const { t } = useTranslation("chat");
  return <Prompts role="region" aria-label={t("starterPromptsLabel")}
    items={STARTER_PROMPTS.map(({ key, Icon }) => ({
      key, disabled,
      label: <Button type="text" block disabled={disabled} aria-label={t(`starterPrompts.${key}.label`)}
        style={{ height: "100%", minHeight: 100, padding: 14, whiteSpace: "normal", textAlign: "left", alignItems: "flex-start", justifyContent: "flex-start" }}>
        <Flex vertical align="start" gap={8}>
          <Flex align="center" gap={8}><Icon size={18} /><Typography.Text strong>{t(`starterPrompts.${key}.label`)}</Typography.Text></Flex>
          <Typography.Text type="secondary" style={{ fontWeight: 400 }}>{t(`starterPrompts.${key}.description`)}</Typography.Text>
        </Flex>
      </Button>,
    }))}
    styles={{
      list: { display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 16 },
      item: { padding: 0, minWidth: 0, alignItems: "stretch" },
      // Stretch the native label wrapper so the Button fills the card's height.
      itemContent: { display: "grid", alignItems: "stretch" },
    }}
    onItemClick={({ data }) => {
      const starter = STARTER_PROMPTS.find(item => item.key === data.key);
      if (starter) onSelect?.(t(`starterPrompts.${starter.key}.prompt`));
    }}
  />;
}

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
  const title = props.initialSession?.title;
  const sessionTitle = props.existingSession
    ? title && title !== "Untitled" ? title : t("session") : undefined;
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
        sessionTitle={sessionTitle}
      />
    );
  }
  return <ConnectedAgentConversation {...props} />;
}

function ConnectedAgentConversation(props: Parameters<typeof AgentConversation>[0]) {
  const { t } = useTranslation("chat");
  const title = props.initialSession?.title;
  const sessionTitle = props.existingSession
    ? title && title !== "Untitled" ? title : t("session") : undefined;
  const { agent, isReady } = useAgent({
    agentId: `research-chat-${props.threadId}`,
    runtimeAgentId: RESEARCH_AGENT_ID,
    threadId: props.threadId,
    throttleMs: 16,
    updates: [UseAgentUpdate.OnMessagesChanged, UseAgentUpdate.OnRunStatusChanged],
  });
  if (!isReady || !(agent instanceof HttpAgent)) {
    return <StaticChatMain modelControls={props.modelControls} opening sessionTitle={sessionTitle} />;
  }
  return <AuthoritativeConversation {...props} agent={agent} />;
}

function AuthoritativeConversation({
  agent,
  ...props
}: Parameters<typeof AgentConversation>[0] & Readonly<{ agent: HttpAgent }>) {
  useEffect(() => {
    const original = agent.fetch;
    agent.fetch = createAgentFetch(original);
    return () => { agent.fetch = original; };
  }, [agent]);
  const controller = useChatConversation({ agent, ...props });
  return <ChatConversationView controller={controller} modelControls={props.modelControls}
    existingSession={props.existingSession} agentId={`research-chat-${props.threadId}`}
    threadId={props.threadId} title={props.initialSession?.title} />;
}

export function ChatConversationView({ controller, modelControls, existingSession, title }: {
  controller: ChatConversationController;
  modelControls: ReactNode;
  existingSession: boolean;
  agentId: string;
  threadId: string;
  title?: string;
}) {
  const { t } = useTranslation("chat");
  const newChat = !existingSession && controller.turns.length === 0;
  return (
    <ChatUiProvider><main className={`quantgrove-chat flex h-full min-h-0 min-w-0 flex-col gap-4 py-6${newChat ? " justify-center" : ""}`} aria-label={title ?? t("session")}
      data-agent-run-id={controller.currentTurnId ?? controller.latestTurnId ?? undefined}
      data-current-turn-id={controller.currentTurnId ?? undefined}>
      {controller.nextCursor || controller.timelineError ? <div className="mx-auto w-full max-w-[808px] shrink-0 px-5">
        {controller.nextCursor ? <Button type="text" loading={controller.loadingOlder} disabled={controller.loadingOlder} onClick={() => void controller.loadOlder()}>{t(controller.loadingOlder ? "loadingEarlier" : "loadMore")}</Button> : null}
        {controller.timelineError ? <Alert type="error" title={t("timelineError")} action={<Button type="text" onClick={() => void controller.retryTimeline()}>{t("retry")}</Button>} /> : null}
      </div> : null}
      {newChat ? <div className="mx-auto mb-6 flex w-full max-w-[808px] shrink-0 justify-center px-5"><ChatWelcome /></div> : <ChatTimeline controller={controller} />}
      <div className="mx-auto w-full max-w-[808px] shrink-0 px-5">
        <ChatComposer controller={controller} modelControls={modelControls} />
      </div>
      {newChat ? <div className="mx-auto mt-6 w-full max-w-[760px] shrink-0 px-5">
        <ChatStarterCards disabled={controller.phase !== "new"} onSelect={prompt => {
          controller.setDraft(prompt);
          controller.focusComposer();
        }} />
      </div> : null}
    </main></ChatUiProvider>
  );
}

export function StaticChatMain({
  error,
  modelControls,
  opening = false,
  sessionTitle,
}: {
  error?: string;
  modelControls: ReactNode;
  opening?: boolean;
  sessionTitle?: string;
}) {
  const { t } = useTranslation("chat");
  const newChat = sessionTitle === undefined;
  return <ChatUiProvider><main className={`quantgrove-chat flex h-full min-h-0 min-w-0 flex-col gap-4 py-6${newChat ? " justify-center" : ""}`} aria-label={sessionTitle ?? t("session")} aria-busy={opening}>
    {error ? <div className="mx-auto w-full max-w-[808px] shrink-0 px-5"><Alert type="error" title={error} action={<Button type="text" onClick={() => window.location.reload()}>{t("reconnect")}</Button>} /></div> : null}
    <div className={`mx-auto flex w-full max-w-[808px] px-5 ${newChat ? "mb-6 shrink-0 justify-center" : "flex-1"}`}>{newChat ? <ChatWelcome /> : null}</div>
    <div className="mx-auto w-full max-w-[808px] shrink-0 px-5">
      <Sender aria-label={t("message")} disabled placeholder={t("newPlaceholder")} footer={modelControls} />
    </div>
    {newChat ? <div className="mx-auto mt-6 w-full max-w-[760px] shrink-0 px-5"><ChatStarterCards disabled /></div> : null}
  </main></ChatUiProvider>;
}
