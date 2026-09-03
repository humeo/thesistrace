import {
  ChartLineUp,
  ClockCounterClockwise,
  Database,
  Flask,
  List,
  NotePencil,
  SidebarSimple,
  X,
} from "@phosphor-icons/react";
import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import { AccountMenu } from "../auth/AccountMenu";
import { isUuid } from "../uuid";
import {
  AgentConversation as AuthoritativeAgentConversation,
  StaticChatMain as AuthoritativeStaticChatMain,
} from "./ChatConversation";
export { AssistantMarkdown } from "./ChatTimeline";
import { chatSessionHref, handleChatNavigation } from "./chatNavigation";
import {
  chatNavigationReducer,
  initialChatNavigationState,
  resolveModelSelection,
} from "./chatState";
import {
  AgentCatalogAuthenticationRequiredError,
  AgentCatalogInvalidError,
  loadAgentModelCatalog,
  reasoningEffortLabel,
  type AgentModelCatalog,
} from "./modelCatalog";
import { ModelPicker } from "./ModelPicker";
import { ResearchChatCopilotProvider } from "./ResearchChatCopilotProvider";
import { SessionHistoryList } from "./SessionHistoryList";
import {
  AgentSessionPreferenceInvalidError,
  AgentSessionPreferenceNotFoundError,
  loadAgentSessionPreference,
  type AgentSessionPreference,
} from "./sessionPreference";
import {
  useSelectedSession,
  useSessionHistory,
  type SelectedSessionState,
  type SessionHistoryController,
} from "./useSessionHistory";

const workspaceRoutes = [
  { path: "/data", label: "Data", icon: Database },
  { path: "/research", label: "Research", icon: Flask },
  { path: "/research-runs", label: "Research Runs", icon: ChartLineUp },
  { path: "/daily-tracks", label: "Daily Tracks", icon: ClockCounterClockwise },
] as const;

export type AgentCatalogState =
  | Readonly<{ status: "loading" }>
  | Readonly<{ catalog: AgentModelCatalog; status: "ready" }>
  | Readonly<{ status: "authentication-required" }>
  | Readonly<{ status: "invalid" }>
  | Readonly<{ status: "unavailable" }>;

export type BrowserChatThread =
  | Readonly<{ id: string; kind: "new" }>
  | Readonly<{ id: string; kind: "session" }>
  | Readonly<{ id: null; kind: "invalid" }>;

export type AgentSessionPreferenceState =
  | Readonly<{ status: "not-required" }>
  | Readonly<{ status: "loading" }>
  | Readonly<{ preference: AgentSessionPreference; status: "ready" }>
  | Readonly<{ status: "not-found" }>
  | Readonly<{ status: "invalid" }>
  | Readonly<{ status: "unavailable" }>;

export function ChatPage({ researcherId }: { researcherId: string }) {
  return <ResearcherChatPage key={researcherId} researcherId={researcherId} />;
}

function ResearcherChatPage({ researcherId }: { researcherId: string }) {
  const { reload, state } = useAgentCatalog();
  const [thread, setThread] = useState(() => readBrowserChatThread(window.location.search));
  const sessionHistory = useSessionHistory(researcherId);
  const listedSession = thread.id === null
    ? undefined
    : sessionHistory.sessions.find((session) => session.id === thread.id);
  const selectedSessionState = useSelectedSession(
    thread.kind === "session" ? thread.id : null,
    listedSession,
    researcherId,
    sessionHistory.status,
    sessionHistory.refreshVersion,
  );
  const preferenceState = useAgentSessionPreference(thread, researcherId);

  useEffect(() => {
    const synchronize = () => setThread(readBrowserChatThread(window.location.search));
    window.addEventListener("popstate", synchronize);
    return () => window.removeEventListener("popstate", synchronize);
  }, []);

  const navigateChat = useCallback((href: string) => {
    window.history.pushState(window.history.state, "", href);
    setThread(readBrowserChatThread(window.location.search));
  }, []);

  return (
    <ResearchChatCopilotProvider>
      <ChatShell
        catalogState={state}
        navigateChat={navigateChat}
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

export function ChatShell({
  catalogState,
  navigateChat,
  preferenceState,
  researcherId,
  reloadCatalog,
  selectedSessionState,
  sessionHistory,
  thread,
}: {
  catalogState: AgentCatalogState;
  navigateChat: (href: string) => void;
  preferenceState: AgentSessionPreferenceState;
  researcherId: string;
  reloadCatalog: () => void;
  selectedSessionState: SelectedSessionState;
  sessionHistory: SessionHistoryController;
  thread?: BrowserChatThread;
}) {
  const [navigation, dispatchNavigation] = useReducer(
    chatNavigationReducer,
    initialChatNavigationState,
  );
  const [requestedModelKey, setRequestedModelKey] = useState<string | null>(null);
  const [requestedReasoning, setRequestedReasoning] = useState<string | null>(null);
  const [acceptedThreadId, setAcceptedThreadId] = useState<string | null>(null);
  const accepted = thread?.kind === "session"
    || (thread?.kind === "new" && thread.id === acceptedThreadId);
  const mobileViewport = useMobileViewport();
  const mobileNavigationToggleRef = useRef<HTMLButtonElement>(null);
  const mobileNavigationCloseRef = useRef<HTMLButtonElement>(null);
  const newChatRef = useRef<HTMLAnchorElement>(null);
  const storedPreference = preferenceState.status === "ready"
    ? preferenceState.preference
    : null;
  const effectiveModelKey = requestedModelKey ?? storedPreference?.model_key ?? null;
  const effectiveReasoning = requestedModelKey === null
    ? requestedReasoning ?? storedPreference?.reasoning_effort ?? null
    : requestedReasoning;
  const preferenceReady = thread?.kind !== "session"
    || preferenceState.status === "ready";
  const currentSession = thread?.id === null || thread?.id === undefined
    ? undefined
    : sessionHistory.sessions.find((session) => session.id === thread.id)
      ?? (selectedSessionState.status === "ready" ? selectedSessionState.session : undefined);
  const selection = catalogState.status === "ready" && preferenceReady
    ? resolveModelSelection(
      catalogState.catalog,
      effectiveModelKey,
      effectiveReasoning,
    )
    : null;
  const contextTitle = chatContextTitle({
    accepted,
    currentSessionTitle: currentSession?.title,
    preferenceState,
    selectedSessionState,
    thread,
  });

  useEffect(() => {
    if (navigation.mobileNavigationOpen) {
      mobileNavigationCloseRef.current?.focus();
    }
  }, [navigation.mobileNavigationOpen]);

  useEffect(() => {
    setRequestedModelKey(null);
    setRequestedReasoning(null);
  }, [thread?.id, thread?.kind]);

  function closeMobileNavigation(): void {
    dispatchNavigation({ type: "close-mobile-navigation" });
    window.requestAnimationFrame(() => mobileNavigationToggleRef.current?.focus());
  }

  function handleMobileNavigationKeyDown(event: KeyboardEvent<HTMLElement>): void {
    if (!navigation.mobileNavigationOpen) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      closeMobileNavigation();
      return;
    }
    if (event.key !== "Tab") return;

    const focusable = [...event.currentTarget.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), summary, input:not([disabled]), select:not([disabled]), textarea:not([disabled])',
    )].filter((element) => element.getClientRects().length > 0);
    const first = focusable[0];
    const last = focusable.at(-1);
    if (first === undefined || last === undefined) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function acceptThread(): void {
    if (thread === undefined || thread.id === null || accepted) return;
    window.history.replaceState(window.history.state, "", chatSessionHref(thread.id));
    setAcceptedThreadId(thread.id);
  }

  function openChat(href: string): void {
    navigateChat(href);
    if (navigation.mobileNavigationOpen) closeMobileNavigation();
  }

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
    <div
      className={`chat-shell${navigation.sidebarCollapsed ? " chat-shell-collapsed" : ""}${navigation.mobileNavigationOpen ? " chat-shell-navigation-open" : ""}`}
    >
      <aside
        aria-hidden={mobileViewport && !navigation.mobileNavigationOpen ? true : undefined}
        className="chat-sidebar"
        id="chat-navigation"
        inert={mobileViewport && !navigation.mobileNavigationOpen ? true : undefined}
        onKeyDown={handleMobileNavigationKeyDown}
      >
        <div className="chat-brand-row">
          <a className="brand" aria-label="ThesisTrace home" href="/data">
            <span className="brand-mark" aria-hidden="true">T</span>
            <span className="chat-sidebar-label">ThesisTrace</span>
          </a>
          <button
            aria-label="Close navigation"
            className="chat-mobile-navigation-close"
            onClick={closeMobileNavigation}
            ref={mobileNavigationCloseRef}
            type="button"
          >
            <X aria-hidden="true" size={18} weight="regular" />
          </button>
        </div>

        <a
          aria-current={!accepted && thread?.kind !== "invalid" ? "page" : undefined}
          className="chat-new"
          href="/chat"
          onClick={(event) => handleChatNavigation(event, () => openChat("/chat"))}
          ref={newChatRef}
          title="New Chat"
        >
          <NotePencil aria-hidden="true" size={18} weight="regular" />
          <span className="chat-sidebar-label">New Chat</span>
        </a>

        <nav aria-label="Workspace" className="chat-workspace-navigation">
          {workspaceRoutes.map((route) => {
            const Icon = route.icon;
            return (
              <a href={route.path} key={route.path} title={route.label}>
                <Icon aria-hidden="true" size={18} weight="regular" />
                <span className="chat-sidebar-label">{route.label}</span>
              </a>
            );
          })}
        </nav>

        <section aria-labelledby="chat-session-heading" className="chat-session-region">
          <h2 data-collapsed-label="C" id="chat-session-heading">Chats</h2>
          <SessionHistoryList
            controller={sessionHistory}
            currentSessionId={accepted && thread?.id !== null ? thread?.id ?? null : null}
            navigate={openChat}
            navigationInteractive={!mobileViewport || navigation.mobileNavigationOpen}
            restoreFocus={(deletedCurrentSession) => {
              if (mobileViewport && (
                deletedCurrentSession || !navigation.mobileNavigationOpen
              )) {
                mobileNavigationToggleRef.current?.focus();
              } else {
                newChatRef.current?.focus();
              }
            }}
          />
        </section>

        <div className="chat-account-area">
          <AccountMenu />
        </div>
      </aside>

      <div className="chat-frame">
        <header className="chat-context-bar">
          <div className="chat-context-leading">
            <button
              aria-controls="chat-navigation"
              aria-expanded={navigation.mobileNavigationOpen}
              aria-label="Open navigation"
              className="chat-mobile-navigation-toggle"
              onClick={() => dispatchNavigation({ type: "open-mobile-navigation" })}
              ref={mobileNavigationToggleRef}
              type="button"
            >
              <List aria-hidden="true" size={19} weight="regular" />
            </button>
            <button
              aria-controls="chat-navigation"
              aria-expanded={!navigation.sidebarCollapsed}
              aria-label={navigation.sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              className="chat-sidebar-toggle"
              onClick={() => dispatchNavigation({ type: "toggle-sidebar" })}
              type="button"
            >
              <SidebarSimple aria-hidden="true" size={18} weight="regular" />
            </button>
            <div className="chat-session-title">
              <strong>{contextTitle}</strong>
              <span>Research Agent</span>
            </div>
          </div>
          <span className="chat-model-context">
            {selection === null
              ? catalogState.status === "ready" && preferenceState.status === "ready"
                ? "Model selection required"
                : "Model catalog"
              : `${selection.model.display_name} · ${reasoningEffortLabel(selection.reasoningEffort)}`}
          </span>
        </header>

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
      </div>

      <button
        aria-label="Close navigation"
        className="chat-navigation-backdrop"
        onClick={closeMobileNavigation}
        type="button"
      />
    </div>
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
          onClick={(event) => handleChatNavigation(event, navigate)}
        >
          Start a New Chat
        </a>
      </section>
    </main>
  );
}

function useMobileViewport(): boolean {
  const [mobile, setMobile] = useState(() => typeof window !== "undefined"
    && window.matchMedia("(max-width: 768px)").matches);
  useEffect(() => {
    const query = window.matchMedia("(max-width: 768px)");
    const update = () => setMobile(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return mobile;
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

export function readBrowserChatThread(
  search: string,
  createId: () => string = () => crypto.randomUUID(),
): BrowserChatThread {
  const parameters = new URLSearchParams(search);
  const keys = [...parameters.keys()];
  const sessions = parameters.getAll("session");
  if (keys.length === 0) {
    return { id: createId(), kind: "new" };
  }
  const session = sessions.length === 1 ? sessions[0] : undefined;
  if (
    keys.every((key) => key === "session")
    && keys.length === 1
    && session !== undefined
    && isUuid(session)
  ) {
    return { id: session.toLowerCase(), kind: "session" };
  }
  return { id: null, kind: "invalid" };
}
