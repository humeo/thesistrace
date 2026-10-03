import { Alert, Button, Result, Typography } from "antd";
import { ChatUiProvider } from "./ChatUiProvider";
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

export function ChatPage({ researcherId, thread: routedThread }: {
  researcherId: string;
  thread: BrowserChatThread;
}) {
  // The route is keyed by Chat identity. Accepting a new Chat updates its URL,
  // but must not reopen settings or unmount the active conversation.
  const [thread] = useState(routedThread);
  const { reload, state } = useAgentCatalog();
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
    <ResearchChatCopilotProvider>
      <ChatContent
        catalogState={state}
        navigateChat={navigate}
        preferenceState={preferenceState}
        researcherId={researcherId}
        reloadCatalog={reload}
        selectedSessionState={selectedSessionState}
        sessionHistory={sessionHistory}
        thread={thread}
      />
    </ResearchChatCopilotProvider>
  );
}

export function ChatContent({
  catalogState, navigateChat, preferenceState, researcherId,
  reloadCatalog, selectedSessionState, sessionHistory, thread,
}: {
  catalogState: AgentCatalogState;
  navigateChat: WorkspaceNavigate;
  preferenceState: AgentSessionPreferenceState;
  researcherId: string;
  reloadCatalog: () => void;
  selectedSessionState: SelectedSessionState;
  sessionHistory: SessionHistoryController;
  thread?: BrowserChatThread;
}) {
  const { t } = useTranslation("chat");
  const [requestedPreference, setRequestedPreference] = useState<AgentSessionPreference | null>(null);
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
    setRequestedPreference(null);
  }, [thread?.id, thread?.kind]);

  function acceptThread(): void {
    if (thread === undefined || thread.id === null || accepted) return;
    setAcceptedThreadId(thread.id);
    navigateChat(chatSessionHref(thread.id), { replace: true });
  }
  const openChat = (href: string) => navigateChat(href);

  const modelControls = (
    <CatalogControls
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
            sessionTitle={currentSession?.title && currentSession.title !== "Untitled" ? currentSession.title : t("session")}
          />
        ) : thread.kind === "session" && (
          preferenceState.status !== "ready"
          || selectedSessionState.status !== "ready"
        ) ? (
          <AuthoritativeStaticChatMain
            error={t("sessionLoadFailed")}
            modelControls={null}
            sessionTitle={currentSession?.title && currentSession.title !== "Untitled" ? currentSession.title : t("session")}
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
            titleMaySettle={currentSession?.title === "Untitled"
              || (!accepted && thread.kind === "new")}
            threadId={thread.id}
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
  catalogState,
  onModelChange,
  onReasoningChange,
  onDefaultChange,
  reloadCatalog,
  selection,
  selectionRequired,
}: {
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
    <ModelPicker
      catalog={catalogState.catalog}
      onModelChange={onModelChange}
      onReasoningChange={onReasoningChange}
      onDefaultChange={onDefaultChange}
      selection={selection}
    />
  );
}

function useAgentCatalog(): Readonly<{
  reload: () => void;
  state: AgentCatalogState;
}> {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<AgentCatalogState>({ status: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    void loadAgentModelCatalog(controller.signal)
      .then((catalog) => setState({ catalog, status: "ready" }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (error instanceof AgentCatalogAuthenticationRequiredError) {
          setState({ status: "authentication-required" });
        } else if (error instanceof AgentCatalogInvalidError) {
          setState({ status: "invalid" });
        } else {
          setState({ status: "unavailable" });
        }
      });
    return () => controller.abort();
  }, [attempt]);
  return { reload: () => setAttempt((current) => current + 1), state };
}

function useAgentSessionPreference(
  thread: BrowserChatThread,
  researcherId: string,
): AgentSessionPreferenceState {
  const preferenceKey = `${researcherId}:${thread.kind}:${thread.id ?? "invalid"}`;
  const [owned, setOwned] = useState<Readonly<{
    key: string;
    state: AgentSessionPreferenceState;
  }>>(() => ({
    key: preferenceKey,
    state: thread.kind === "session" ? { status: "loading" } : { status: "not-required" },
  }));
  useEffect(() => {
    if (thread.kind !== "session") {
      setOwned({ key: preferenceKey, state: { status: "not-required" } });
      return;
    }
    const controller = new AbortController();
    let current = true;
    setOwned({ key: preferenceKey, state: { status: "loading" } });
    void loadAgentSessionPreference(thread.id, controller.signal)
      .then((preference) => {
        if (!current) return;
        setOwned({
          key: preferenceKey,
          state: { preference, status: "ready" },
        });
      })
      .catch((error: unknown) => {
        if (!current || (error instanceof DOMException && error.name === "AbortError")) return;
        if (error instanceof AgentSessionPreferenceNotFoundError) {
          setOwned({ key: preferenceKey, state: { status: "not-found" } });
        } else if (error instanceof AgentSessionPreferenceInvalidError) {
          setOwned({ key: preferenceKey, state: { status: "invalid" } });
        } else {
          setOwned({ key: preferenceKey, state: { status: "unavailable" } });
        }
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [preferenceKey, thread.id, thread.kind]);
  return owned.key === preferenceKey
    ? owned.state
    : thread.kind === "session" ? { status: "loading" } : { status: "not-required" };
}
