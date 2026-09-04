import { useEffect, useState } from "react";

import { AppHeader, useWorkspace } from "../shell/AppShell";
import { handleWorkspaceNavigation, type WorkspaceNavigate } from "../shell/navigation";
import {
  AgentConversation as AuthoritativeAgentConversation,
  StaticChatMain as AuthoritativeStaticChatMain,
} from "./ChatConversation";
export { AssistantMarkdown } from "./ChatTimeline";
import { chatSessionHref, type BrowserChatThread } from "./chatNavigation";
import { resolveModelSelection } from "./chatState";
import {
  AgentCatalogAuthenticationRequiredError, AgentCatalogInvalidError, loadAgentModelCatalog,
  reasoningEffortLabel, type AgentModelCatalog,
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
  const [requestedModelKey, setRequestedModelKey] = useState<string | null>(null);
  const [requestedReasoning, setRequestedReasoning] = useState<string | null>(null);
  const [acceptedThreadId, setAcceptedThreadId] = useState<string | null>(null);
  const accepted = thread?.kind === "session"
    || (thread?.kind === "new" && thread.id === acceptedThreadId);
  const storedPreference = preferenceState.status === "ready" ? preferenceState.preference : null;
  const effectiveModelKey = requestedModelKey ?? storedPreference?.model_key ?? null;
  const effectiveReasoning = requestedModelKey === null
    ? requestedReasoning ?? storedPreference?.reasoning_effort ?? null : requestedReasoning;
  const preferenceReady = thread?.kind !== "session" || preferenceState.status === "ready";
  const currentSession = thread?.id === null || thread?.id === undefined
    ? undefined
    : sessionHistory.sessions.find((session) => session.id === thread.id)
      ?? (selectedSessionState.status === "ready" ? selectedSessionState.session : undefined);
  const selection = catalogState.status === "ready" && preferenceReady
    ? resolveModelSelection(catalogState.catalog, effectiveModelKey, effectiveReasoning) : null;
  const contextTitle = chatContextTitle({
    accepted, currentSessionTitle: currentSession?.title, preferenceState, selectedSessionState, thread,
  });

  useEffect(() => {
    setRequestedModelKey(null);
    setRequestedReasoning(null);
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
        setRequestedModelKey(modelKey);
        setRequestedReasoning(null);
      }}
      onReasoningChange={setRequestedReasoning}
      reloadCatalog={reloadCatalog}
      selection={selection}
      selectionRequired={catalogState.status === "ready"
        && preferenceState.status === "ready"
        && selection === null}
    />
  );

  return (
    <>
      <AppHeader
        title={<div className="chat-session-title"><strong>{contextTitle}</strong><span>Research Agent</span></div>}
        trailing={
          <span className="chat-model-context">
            {selection === null
              ? catalogState.status === "ready" && preferenceState.status === "ready"
                ? "Model selection required" : "Model catalog"
              : `${selection.model.display_name} · ${reasoningEffortLabel(selection.reasoningEffort)}`}
          </span>
        }
      />
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
            modelControls={<p className="chat-catalog-status" role="status">Loading Session settings…</p>}
            opening
          />
        ) : thread.kind === "session" && (
          preferenceState.status !== "ready"
          || selectedSessionState.status !== "ready"
        ) ? (
          <AuthoritativeStaticChatMain
            error="The Research Agent Session could not be loaded."
            modelControls={null}
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
  return (
    <main className="chat-main chat-not-found-main">
      <section className="chat-not-found" role="alert">
        <p className="eyebrow">Chat Session</p>
        <h1>Chat not found</h1>
        <p>
          This Chat does not exist or is not available to the current Researcher.
        </p>
        <a
          className="button button-primary"
          href="/chat"
          onClick={(event) => handleWorkspaceNavigation(event, navigate)}
        >
          Start a New Chat
        </a>
      </section>
    </main>
  );
}

function CatalogControls({
  catalogState,
  onModelChange,
  onReasoningChange,
  reloadCatalog,
  selection,
  selectionRequired,
}: {
  catalogState: AgentCatalogState;
  onModelChange: (modelKey: string) => void;
  onReasoningChange: (reasoningEffort: string) => void;
  reloadCatalog: () => void;
  selection: ReturnType<typeof resolveModelSelection> | null;
  selectionRequired: boolean;
}) {
  if (catalogState.status === "loading") {
    return <p className="chat-catalog-status" role="status">Loading registered models…</p>;
  }
  if (catalogState.status === "ready" && selectionRequired) {
    return (
      <div className="chat-model-picker-with-error">
        <p className="visually-hidden" role="alert">
          The previous model selection is no longer available. Choose a registered model.
        </p>
        <ModelPicker
          catalog={catalogState.catalog}
          onModelChange={onModelChange}
          onReasoningChange={onReasoningChange}
          selection={null}
        />
      </div>
    );
  }
  if (catalogState.status !== "ready" || selection === null) {
    const message = catalogState.status === "authentication-required"
      ? "Your Agent Session could not be verified. Log in again to continue."
      : catalogState.status === "invalid"
        ? "The registered model Catalog is invalid."
        : "The Agent Host is unavailable.";
    return (
      <div className="chat-catalog-error" role="alert">
        <span>{message}</span>
        {catalogState.status !== "authentication-required" ? (
          <button className="button-quiet" onClick={reloadCatalog} type="button">
            Retry
          </button>
        ) : null}
      </div>
    );
  }
  return (
    <ModelPicker
      catalog={catalogState.catalog}
      onModelChange={onModelChange}
      onReasoningChange={onReasoningChange}
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

function chatContextTitle(options: Readonly<{
  accepted: boolean;
  currentSessionTitle: string | undefined;
  preferenceState: AgentSessionPreferenceState;
  selectedSessionState: SelectedSessionState;
  thread: BrowserChatThread | undefined;
}>): string {
  if (
    options.thread?.kind === "invalid"
    || options.preferenceState.status === "not-found"
    || options.selectedSessionState.status === "not-found"
  ) {
    return "Chat not found";
  }
  if (options.thread?.kind === "session") {
    if (
      options.preferenceState.status === "loading"
      || options.selectedSessionState.status === "loading"
    ) {
      return "Loading Chat";
    }
    if (
      options.preferenceState.status !== "ready"
      || options.selectedSessionState.status !== "ready"
    ) {
      return "Chat unavailable";
    }
    return options.selectedSessionState.session.title;
  }
  if (options.accepted) return options.currentSessionTitle ?? "Untitled";
  return "New chat";
}
