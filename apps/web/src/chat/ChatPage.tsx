import { Alert, Button, Flex, Result, Typography } from "antd";
import { ContextWindowIndicator } from "./ContextWindowIndicator";
import { ChatUiProvider } from "./ChatUiProvider";
import { useQuery } from "@tanstack/react-query";
import { useChatSessionViewState, type ChatSessionViewState } from "./chatSessionViewState";
import { type MouseEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useWorkspace } from "../shell/AppShell";
import { handleWorkspaceNavigation, type WorkspaceNavigate } from "../shell/navigation";
import {
  AgentConversation as AuthoritativeAgentConversation,
  StaticChatMain as AuthoritativeStaticChatMain,
} from "./ChatConversation";
export { AssistantMarkdown } from "./ChatTimeline";
import { chatSessionHref, type BrowserChatThread } from "./chatNavigation";
import { resolveModelSelection, resolveSessionModelSelection } from "./chatState";
import {
  AgentCatalogAuthenticationRequiredError, AgentCatalogInvalidError, loadAgentModelCatalog,
  type AgentModelCatalog,
} from "./modelCatalog";
import { ModelPicker } from "./ModelPicker";
import { ResearchChatCopilotProvider } from "./ResearchChatCopilotProvider";
import { sessionDisplayTitle } from "./sessionHistory";
import {
  AgentSessionPreferenceInvalidError, AgentSessionPreferenceNotFoundError,
  loadAgentSessionPreference, type AgentSessionPreference,
} from "./sessionPreference";
import {
  useSelectedSession, type SelectedSessionState, type SessionHistoryController,
} from "./useSessionHistory";

export type AgentCatalogState =
  | Readonly<{ status: "loading" }>
  | Readonly<{ catalog: AgentModelCatalog; status: "ready" }>
  | Readonly<{ status: "authentication-required" }>
  | Readonly<{ status: "invalid" }>
  | Readonly<{ status: "unavailable" }>;

export type AgentSessionPreferenceState =
  | Readonly<{ status: "not-required" }>
  | Readonly<{ status: "loading" }>
  | Readonly<{ preference: AgentSessionPreference; status: "ready" }>
  | Readonly<{ status: "not-found" }>
  | Readonly<{ status: "invalid" }>
  | Readonly<{ status: "unavailable" }>;

export function ChatPage({ researcherId, thread }: {
  researcherId: string;
  thread: BrowserChatThread;
}) {
  return <ResearchChatCopilotProvider>
    <SelectedChatPage key={thread.id ?? "invalid"} researcherId={researcherId} thread={thread} />
  </ResearchChatCopilotProvider>;
}

function SelectedChatPage({ researcherId, thread: routedThread }: {
  researcherId: string;
  thread: BrowserChatThread;
}) {
  // The route is keyed by Chat identity. Accepting a new Chat updates its URL,
  // but must not reopen settings or unmount the active conversation.
  const [thread] = useState(routedThread);
  const { reload, state } = useAgentCatalog();
  const viewState = useChatSessionViewState(thread.id);
  const { sessionHistory, navigate } = useWorkspace();
  const listedSession = thread.id === null
    ? undefined
    : sessionHistory.sessions.find((session) => session.id === thread.id);
  const selectedSessionState = useSelectedSession(
    thread.kind === "session" ? thread.id : null,
    listedSession, researcherId, sessionHistory.status, sessionHistory.refreshVersion,
  );
  const preferenceState = useAgentSessionPreference(thread, researcherId);

  return (
    <ChatContent
      catalogState={state}
      navigateChat={navigate}
      preferenceState={preferenceState}
      researcherId={researcherId}
      reloadCatalog={reload}
      selectedSessionState={selectedSessionState}
      sessionHistory={sessionHistory}
      thread={thread}
      viewState={viewState}
    />
  );
}

export function ChatContent({
  catalogState, navigateChat, preferenceState, researcherId,
  reloadCatalog, selectedSessionState, sessionHistory, thread, viewState,
}: {
  catalogState: AgentCatalogState;
  navigateChat: WorkspaceNavigate;
  preferenceState: AgentSessionPreferenceState;
  researcherId: string;
  reloadCatalog: () => void;
  selectedSessionState: SelectedSessionState;
  sessionHistory: SessionHistoryController;
  thread?: BrowserChatThread;
  viewState?: ChatSessionViewState;
}) {
  const { t } = useTranslation("chat");
  const [requestedPreference, setRequestedPreference] = useState<AgentSessionPreference | null>(viewState?.requestedPreference ?? null);
  const [acceptedThreadId, setAcceptedThreadId] = useState<string | null>(null);
  const accepted = thread?.kind === "session"
    || (thread?.kind === "new" && thread.id === acceptedThreadId);
  const storedPreference = preferenceState.status === "ready" ? preferenceState.preference : null;
  const preferenceReady = thread?.kind !== "session" || preferenceState.status === "ready";
  const currentSession = thread?.id === null || thread?.id === undefined
    ? undefined
    : sessionHistory.sessions.find((session) => session.id === thread.id)
      ?? (selectedSessionState.status === "ready" ? selectedSessionState.session : undefined);
  const selection = catalogState.status === "ready" && preferenceReady
    ? requestedPreference === null
      ? resolveSessionModelSelection(catalogState.catalog, storedPreference)
      : resolveModelSelection(catalogState.catalog,
          requestedPreference.selection_mode === "default" ? null : requestedPreference.model_key,
          requestedPreference.selection_mode === "default" ? null : requestedPreference.reasoning_effort)
    : null;

  useEffect(() => {
    if (viewState) viewState.requestedPreference = requestedPreference;
  }, [requestedPreference, viewState]);

  function acceptThread(): void {
    if (thread === undefined || thread.id === null || accepted) return;
    setAcceptedThreadId(thread.id);
    navigateChat(chatSessionHref(thread.id), { replace: true });
  }
  const openChat = (href: string) => navigateChat(href);

  const modelControls = (
    <CatalogControls
      contextThreadId={accepted ? thread?.id ?? null : null}
      catalogState={catalogState}
      onModelChange={(modelKey) => {
        if (catalogState.status !== "ready") return;
        const model = catalogState.catalog.models.find(candidate => candidate.key === modelKey);
        if (model) setRequestedPreference({ model_key: model.key, reasoning_effort: model.default_reasoning_effort, selection_mode: "manual" });
      }}
      onReasoningChange={(reasoningEffort) => {
        if (selection) setRequestedPreference({ model_key: selection.model.key, reasoning_effort: reasoningEffort, selection_mode: "manual" });
      }}
      onDefaultChange={(followDefault) => {
        if (selection) setRequestedPreference({ model_key: selection.model.key, reasoning_effort: selection.reasoningEffort, selection_mode: followDefault ? "default" : "manual" });
      }}
      reloadCatalog={reloadCatalog}
      selection={selection}
      selectionRequired={catalogState.status === "ready"
        && preferenceState.status === "ready"
        && selection === null}
    />
  );

  return (
    <>
        {thread === undefined ? (
          <AuthoritativeStaticChatMain modelControls={modelControls} />
        ) : thread.kind === "invalid"
          || selectedSessionState.status === "not-found"
          || preferenceState.status === "not-found" ? (
          <ChatNotFoundMain navigate={() => openChat("/chat")} />
        ) : thread.kind === "session" && (
          preferenceState.status === "loading"
          || selectedSessionState.status === "loading"
        ) ? (
          <AuthoritativeStaticChatMain
            modelControls={<Typography.Text type="secondary" role="status">{t("loadingSettings")}</Typography.Text>}
            opening
            sessionTitle={sessionDisplayTitle(currentSession, t("session"))}
          />
        ) : thread.kind === "session" && (
          preferenceState.status !== "ready"
          || selectedSessionState.status !== "ready"
        ) ? (
          <AuthoritativeStaticChatMain
            error={t("sessionLoadFailed")}
            modelControls={null}
            sessionTitle={sessionDisplayTitle(currentSession, t("session"))}
          />
        ) : (
          <AuthoritativeAgentConversation
            key={thread.id}
            existingSession={accepted}
            initialSession={currentSession}
            modelControls={modelControls}
            onAccepted={acceptThread}
            onSessionChanged={sessionHistory.refresh}
            onTitleMaySettle={sessionHistory.watchGeneratedTitle}
            researcherId={researcherId}
            selection={selection}
            sessionRefreshFailed={selectedSessionState.status === "ready" && selectedSessionState.refreshFailed}
            titleMaySettle={currentSession?.title === "Untitled"
              || (!accepted && thread.kind === "new")}
            threadId={thread.id}
            viewState={viewState}
          />
        )}
    </>
  );
}

function ChatNotFoundMain({ navigate }: { navigate: () => void }) {
  const { t } = useTranslation("chat");
  return (
    <ChatUiProvider><main className="quantgrove-chat grid h-full place-items-center" role="alert" aria-label={t("session")}>
      <Result status="404" title={<Typography.Title level={1}>{t("chatNotFound")}</Typography.Title>} subTitle={t("chatNotFoundDescription")}
        extra={<Button type="primary" href="/chat" onClick={event => handleWorkspaceNavigation(event as MouseEvent<HTMLAnchorElement>, navigate)}>{t("newChat")}</Button>} />
    </main></ChatUiProvider>
  );
}

function CatalogControls({
  contextThreadId,
  catalogState,
  onModelChange,
  onReasoningChange,
  onDefaultChange,
  reloadCatalog,
  selection,
  selectionRequired,
}: {
  contextThreadId: string | null;
  catalogState: AgentCatalogState;
  onModelChange: (modelKey: string) => void;
  onReasoningChange: (reasoningEffort: import("./modelCatalog").ReasoningEffort) => void;
  onDefaultChange: (followDefault: boolean) => void;
  reloadCatalog: () => void;
  selection: ReturnType<typeof resolveModelSelection> | null;
  selectionRequired: boolean;
}) {
  const { t } = useTranslation("chat");
  if (catalogState.status === "loading") {
    return <Typography.Text type="secondary" role="status">{t("loadingModels")}</Typography.Text>;
  }
  if (catalogState.status === "ready" && selectionRequired) {
    return (
      <div className="min-w-0">
        <p className="visually-hidden" role="alert">
          {t("modelUnavailable")}
        </p>
        <ModelPicker
          catalog={catalogState.catalog}
          onModelChange={onModelChange}
          onReasoningChange={onReasoningChange}
          onDefaultChange={onDefaultChange}
          selection={null}
        />
      </div>
    );
  }
  if (catalogState.status !== "ready" || selection === null) {
    const message = catalogState.status === "authentication-required"
      ? t("agentAuthentication")
      : catalogState.status === "invalid"
        ? t("invalidCatalog")
        : t("agentHostUnavailable");
    return (
      <Alert type="error" title={message} action={catalogState.status !== "authentication-required"
        ? <Button type="text" onClick={reloadCatalog}>{t("retry")}</Button> : undefined} />
    );
  }
  return (
    <Flex align="center" gap={0} style={{ minWidth: 0 }}>
      <ModelPicker
        catalog={catalogState.catalog}
        onModelChange={onModelChange}
        onReasoningChange={onReasoningChange}
        onDefaultChange={onDefaultChange}
        selection={selection}
      />
      <ContextWindowIndicator modelKey={selection.model.key} threadId={contextThreadId} />
    </Flex>
  );
}

function useAgentCatalog(): Readonly<{
  reload: () => void;
  state: AgentCatalogState;
}> {
  const query = useQuery({
    queryKey: ["chat-models"],
    queryFn: ({ signal }) => loadAgentModelCatalog(signal),
  });
  const state: AgentCatalogState = query.data !== undefined ? { status: "ready", catalog: query.data }
    : query.isPending ? { status: "loading" }
    : { status: query.error instanceof AgentCatalogAuthenticationRequiredError ? "authentication-required"
      : query.error instanceof AgentCatalogInvalidError ? "invalid" : "unavailable" };
  return { reload: () => { void query.refetch(); }, state };
}

function useAgentSessionPreference(
  thread: BrowserChatThread,
  researcherId: string,
): AgentSessionPreferenceState {
  const query = useQuery({
    queryKey: ["chat-preference", researcherId, thread.id],
    queryFn: ({ signal }) => loadAgentSessionPreference(thread.id!, signal),
    enabled: thread.kind === "session",
  });
  if (thread.kind !== "session") return { status: "not-required" };
  if (query.error instanceof AgentSessionPreferenceNotFoundError) return { status: "not-found" };
  if (query.error instanceof AgentSessionPreferenceInvalidError) return { status: "invalid" };
  if (query.data !== undefined) return { preference: query.data, status: "ready" };
  return { status: query.isPending ? "loading" : "unavailable" };
}
