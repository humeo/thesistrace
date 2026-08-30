import type { AbstractAgent, AgentSubscriber } from "@ag-ui/client";
import type { Message } from "@ag-ui/core";
import { UseAgentUpdate, useAgent } from "@copilotkit/react-core/v2/headless";
import {
  ArrowUp,
  ChartLineUp,
  ChatCircle,
  CheckCircle,
  CircleNotch,
  ClockCounterClockwise,
  Database,
  Flask,
  List,
  NotePencil,
  SidebarSimple,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { AccountMenu } from "../auth/AccountMenu";
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
import { ResearchChatCopilotProvider } from "./ResearchChatCopilotProvider";
import {
  AgentSessionPreferenceInvalidError,
  AgentSessionPreferenceNotFoundError,
  loadAgentSessionPreference,
  type AgentSessionPreference,
} from "./sessionPreference";
import {
  parseResearchRunHref,
  parseSafeToolResult,
  researchRunHref,
  type SafeResearchRunResource,
  type SafeToolResult,
} from "./toolResult";

const MAX_CHAT_MESSAGE_BYTES = 16 * 1024;
const RESEARCH_AGENT_ID = "research";
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
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

export type BrowserChatThread = Readonly<{
  id: string;
  persisted: boolean;
}>;

export type AgentSessionPreferenceState =
  | Readonly<{ status: "not-required" }>
  | Readonly<{ status: "loading" }>
  | Readonly<{ preference: AgentSessionPreference; status: "ready" }>
  | Readonly<{ status: "not-found" }>
  | Readonly<{ status: "invalid" }>
  | Readonly<{ status: "unavailable" }>;

type ConversationStatus =
  | "idle"
  | "loading-history"
  | "starting"
  | "running"
  | "complete"
  | "failed"
  | "disconnected";

type ConversationSubscriberOptions = Readonly<{
  failRunningTools: () => void;
  finishTool: (id: string, result: SafeToolResult | null) => void;
  onRunFailed: () => void;
  onRunFinished: () => void;
  onRunInitialized?: () => void;
  onRunError: () => void;
  onRunStarted: () => void;
  startTool: (id: string, name: string) => void;
}>;

export type ChatToolActivity = Readonly<{
  durationMs?: number;
  id: string;
  name: string;
  resource?: SafeResearchRunResource;
  startedAtMs?: number;
  status: "running" | "completed" | "failed";
}>;

type ChatTimelineItem =
  | Readonly<{
      content: string;
      id: string;
      kind: "message";
      role: "assistant" | "user";
    }>
  | Readonly<{
      activity: ChatToolActivity;
      id: string;
      kind: "tool";
    }>;

export function ChatPage() {
  const { reload, state } = useAgentCatalog();
  const [thread] = useState(() => readBrowserChatThread(window.location.search));
  const preferenceState = useAgentSessionPreference(thread);
  return (
    <ResearchChatCopilotProvider>
      <ChatShell
        catalogState={state}
        preferenceState={preferenceState}
        reloadCatalog={reload}
        thread={thread}
      />
    </ResearchChatCopilotProvider>
  );
}

export function ChatShell({
  catalogState,
  preferenceState,
  reloadCatalog,
  thread,
}: {
  catalogState: AgentCatalogState;
  preferenceState: AgentSessionPreferenceState;
  reloadCatalog: () => void;
  thread?: BrowserChatThread;
}) {
  const [navigation, dispatchNavigation] = useReducer(
    chatNavigationReducer,
    initialChatNavigationState,
  );
  const [requestedModelKey, setRequestedModelKey] = useState<string | null>(null);
  const [requestedReasoning, setRequestedReasoning] = useState<string | null>(null);
  const [accepted, setAccepted] = useState(thread?.persisted ?? false);
  const mobileViewport = useMobileViewport();
  const mobileNavigationToggleRef = useRef<HTMLButtonElement>(null);
  const mobileNavigationCloseRef = useRef<HTMLButtonElement>(null);
  const storedPreference = preferenceState.status === "ready"
    ? preferenceState.preference
    : null;
  const effectiveModelKey = requestedModelKey ?? storedPreference?.model_key ?? null;
  const effectiveReasoning = requestedModelKey === null
    ? requestedReasoning ?? storedPreference?.reasoning_effort ?? null
    : requestedReasoning;
  const preferenceReady = thread?.persisted !== true
    || preferenceState.status === "ready";
  const selection = catalogState.status === "ready" && preferenceReady
    ? resolveModelSelection(
      catalogState.catalog,
      effectiveModelKey,
      effectiveReasoning,
    )
    : null;

  useEffect(() => {
    if (navigation.mobileNavigationOpen) {
      mobileNavigationCloseRef.current?.focus();
    }
  }, [navigation.mobileNavigationOpen]);

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
    if (thread === undefined || accepted) return;
    window.history.replaceState(window.history.state, "", chatSessionHref(thread.id));
    setAccepted(true);
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

        <a aria-current={!accepted ? "page" : undefined} className="chat-new" href="/chat" title="New Chat">
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
          <h2 id="chat-session-heading">Chats</h2>
          {accepted ? (
            <a aria-current="page" className="chat-session-current" href={chatSessionHref(thread?.id ?? "")}>
              <ChatCircle aria-hidden="true" size={16} weight="regular" />
              <span>Current research chat</span>
            </a>
          ) : (
            <div className="chat-session-empty">
              <ChatCircle aria-hidden="true" size={16} weight="regular" />
              <span>No conversations yet</span>
            </div>
          )}
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
              <strong>{accepted ? "Research chat" : "New chat"}</strong>
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
          <StaticChatMain modelControls={modelControls} status="idle" />
        ) : thread.persisted && preferenceState.status === "loading" ? (
          <StaticChatMain
            modelControls={<p className="chat-catalog-status" role="status">Loading Session settings…</p>}
            status="loading-history"
          />
        ) : thread.persisted && preferenceState.status !== "ready" ? (
          <StaticChatMain
            error={preferenceState.status === "not-found"
              ? "The Research Agent session could not be loaded."
              : "The Research Agent Session settings could not be loaded."}
            modelControls={null}
            status="disconnected"
          />
        ) : (
          <AgentConversation
            existingSession={thread.persisted}
            modelControls={modelControls}
            onAccepted={acceptThread}
            selection={selection}
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

function AgentConversation({
  existingSession,
  modelControls,
  onAccepted,
  selection,
  threadId,
}: {
  existingSession: boolean;
  modelControls: React.ReactNode;
  onAccepted: () => void;
  selection: ReturnType<typeof resolveModelSelection> | null;
  threadId: string;
}) {
  const { agent, isReady } = useAgent({
    agentId: `research-chat-${threadId}`,
    runtimeAgentId: RESEARCH_AGENT_ID,
    threadId,
    throttleMs: 16,
    updates: [
      UseAgentUpdate.OnMessagesChanged,
      UseAgentUpdate.OnRunStatusChanged,
    ],
  });
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<ConversationStatus>(
    existingSession ? "loading-history" : "idle",
  );
  const [toolActivities, setToolActivities] = useState<ReadonlyMap<string, ChatToolActivity>>(
    () => new Map(),
  );
  const connectedAgent = useRef<AbstractAgent | null>(null);
  const messageBytes = chatMessageBytes(draft);
  const messageTooLarge = messageBytes > MAX_CHAT_MESSAGE_BYTES;
  const timeline = chatTimelineItems(agent.messages, [...toolActivities.values()]);
  const busy = agent.isRunning
    || status === "loading-history"
    || status === "starting"
    || status === "running"
    || status === "disconnected";
  const canSubmit = isReady
    && selection !== null
    && !busy
    && draft.trim().length > 0
    && !messageTooLarge;

  const startTool = useCallback((id: string, name: string) => {
    const startedAtMs = monotonicNow();
    setToolActivities((current) => {
      const next = new Map(current);
      next.set(id, { id, name, startedAtMs, status: "running" });
      return next;
    });
  }, []);
  const finishTool = useCallback((id: string, result: SafeToolResult | null) => {
    const finishedAtMs = monotonicNow();
    setToolActivities((current) => {
      const existing = current.get(id);
      if (existing === undefined) return current;
      const next = new Map(current);
      next.set(id, {
        ...existing,
        durationMs: existing.startedAtMs === undefined
          ? undefined
          : Math.max(0, finishedAtMs - existing.startedAtMs),
        ...(result?.resource === undefined ? {} : { resource: result.resource }),
        status: result?.outcome ?? "failed",
      });
      return next;
    });
  }, []);
  const failRunningTools = useCallback(() => {
    const finishedAtMs = monotonicNow();
    setToolActivities((current) => {
      let changed = false;
      const next = new Map(current);
      for (const [id, activity] of current) {
        if (activity.status !== "running") continue;
        changed = true;
        next.set(id, {
          ...activity,
          durationMs: activity.startedAtMs === undefined
            ? undefined
            : Math.max(0, finishedAtMs - activity.startedAtMs),
          status: "failed",
        });
      }
      return changed ? next : current;
    });
  }, []);

  useEffect(() => {
    if (!existingSession || !isReady || connectedAgent.current === agent) return;
    connectedAgent.current = agent;
    let disposed = false;
    let failed = false;
    const subscriber = createConversationSubscriber({
      failRunningTools,
      onRunStarted: () => {
        if (!disposed) setStatus("running");
      },
      onRunFinished: () => {
        if (!disposed) setStatus("complete");
      },
      onRunError: () => {
        failed = true;
        if (!disposed) {
          setError("The previous Research Agent run did not complete.");
          setStatus("failed");
        }
      },
      onRunFailed: () => {
        failed = true;
        if (!disposed) {
          setError("The Research Agent session could not be loaded.");
          setStatus("disconnected");
        }
      },
      startTool: (id, name) => {
        if (!disposed) startTool(id, name);
      },
      finishTool: (id, result) => {
        if (!disposed) finishTool(id, result);
      },
    });
    setStatus("loading-history");
    void agent.connectAgent(undefined, subscriber)
      .then(() => {
        if (!disposed && !failed) setStatus("idle");
      })
      .catch(() => {
        if (!disposed) {
          setError("The Research Agent session could not be loaded.");
          setStatus("disconnected");
        }
      });
    return () => {
      disposed = true;
    };
  }, [agent, existingSession, failRunningTools, finishTool, isReady, startTool]);

  async function submit(event?: FormEvent): Promise<void> {
    event?.preventDefault();
    if (!canSubmit || selection === null) return;

    const content = draft;
    const messageId = crypto.randomUUID();
    let accepted = false;
    let terminal: "none" | "complete" | "failed" = "none";
    const subscriber = createConversationSubscriber({
      failRunningTools,
      finishTool,
      onRunInitialized: () => {
        setError(null);
        setStatus("starting");
      },
      onRunStarted: () => {
        accepted = true;
        onAccepted();
        setStatus("running");
      },
      onRunFinished: () => {
        terminal = "complete";
        setStatus("complete");
      },
      onRunError: () => {
        terminal = "failed";
        setError("The Research Agent could not complete this run.");
        setStatus("failed");
      },
      onRunFailed: () => {
        terminal = "failed";
        setError("The Research Agent connection was interrupted.");
        setStatus("disconnected");
      },
      startTool,
    });

    agent.addMessage({ content, id: messageId, role: "user" });
    setDraft("");
    setError(null);
    setStatus("starting");
    try {
      await agent.runAgent({
        forwardedProps: {
          thesistrace: {
            modelKey: selection.model.key,
            reasoningEffort: selection.reasoningEffort,
          },
        },
      }, subscriber);
      if (terminal === "none") setStatus("complete");
    } catch {
      terminal = "failed";
      setError("The Research Agent connection was interrupted.");
      setStatus("disconnected");
    }

    if (!accepted && terminal === "failed") {
      agent.setMessages(agent.messages.filter((message) => message.id !== messageId));
      setDraft(content);
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    void submit();
  }

  return (
    <main className="chat-main">
      {timeline.length === 0 ? (
        <ChatEmptyState status={status} />
      ) : (
        <section aria-label="Conversation" className="chat-conversation" aria-live="polite">
          {timeline.map((item) => item.kind === "tool" ? (
            <ToolActivityRow activity={item.activity} key={item.id} />
          ) : (
            <article
              className={`chat-message chat-message-${item.role}`}
              key={item.id}
            >
              <p className="chat-message-author">
                {item.role === "assistant" ? "ThesisTrace" : "You"}
              </p>
              <div className="chat-message-content">
                {item.content.length === 0
                  ? "Responding…"
                  : item.role === "assistant"
                    ? <AssistantMarkdown content={item.content} />
                    : item.content}
              </div>
            </article>
          ))}
        </section>
      )}

      <form className="chat-composer-dock" onSubmit={(event) => void submit(event)}>
        {modelControls}
        <div className="chat-composer-status-row">
          <span role="status">{conversationStatusLabel(status, isReady)}</span>
          <span className={messageBytes > MAX_CHAT_MESSAGE_BYTES ? "chat-byte-count-invalid" : undefined}>
            {messageBytes.toLocaleString()} / {MAX_CHAT_MESSAGE_BYTES.toLocaleString()} bytes
          </span>
        </div>
        {messageTooLarge ? (
          <p className="chat-run-error" id="chat-composer-validation" role="alert">
            Message exceeds the 16 KiB limit.
          </p>
        ) : null}
        {error !== null ? <p className="chat-run-error" role="alert">{error}</p> : null}
        <div className="chat-composer-preview">
          <textarea
            aria-describedby={messageTooLarge
              ? "chat-composer-limit chat-composer-validation"
              : "chat-composer-limit"}
            aria-invalid={messageTooLarge || undefined}
            aria-label="Message"
            disabled={!isReady || selection === null || busy}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleComposerKeyDown}
            placeholder="Ask ThesisTrace about an investment idea…"
            rows={2}
            value={draft}
          />
          <button aria-label="Send message" disabled={!canSubmit} type="submit">
            <ArrowUp aria-hidden="true" size={18} weight="bold" />
          </button>
        </div>
        <p id="chat-composer-limit">Text only · Registered models · 16 KiB maximum</p>
      </form>
    </main>
  );
}

function createConversationSubscriber(
  options: ConversationSubscriberOptions,
): AgentSubscriber {
  return {
    onRunFailed: () => {
      options.failRunningTools();
      options.onRunFailed();
    },
    onRunFinishedEvent: () => {
      options.failRunningTools();
      options.onRunFinished();
    },
    onRunInitialized: options.onRunInitialized,
    onRunErrorEvent: () => {
      options.failRunningTools();
      options.onRunError();
    },
    onRunStartedEvent: options.onRunStarted,
    onToolCallResultEvent: ({ event }) => {
      options.finishTool(event.toolCallId, parseSafeToolResult(event.content));
    },
    onToolCallStartEvent: ({ event }) => {
      options.startTool(event.toolCallId, event.toolCallName);
    },
  };
}

function StaticChatMain({
  error,
  modelControls,
  status,
}: {
  error?: string;
  modelControls: React.ReactNode;
  status: ConversationStatus;
}) {
  return (
    <main className="chat-main">
      <ChatEmptyState status={status} />
      <div className="chat-composer-dock">
        {modelControls}
        <div className="chat-composer-status-row">
          <span role="status">{conversationStatusLabel(status, true)}</span>
        </div>
        {error === undefined ? null : (
          <p className="chat-run-error" role="alert">{error}</p>
        )}
        <div className="chat-composer-preview">
          <textarea
            aria-label="Message"
            disabled
            placeholder="Ask ThesisTrace about an investment idea…"
            rows={2}
          />
          <button aria-label="Send message" disabled type="button">
            <ArrowUp aria-hidden="true" size={18} weight="bold" />
          </button>
        </div>
        <p>Text only · Registered models · 16 KiB maximum</p>
      </div>
    </main>
  );
}

function ChatEmptyState({ status }: { status: ConversationStatus }) {
  return (
    <section className="chat-empty-state">
      <span className="chat-empty-symbol" aria-hidden="true">α</span>
      <p className="eyebrow">Research Agent</p>
      <h1>Turn an investment idea into Alpha</h1>
      <p className="chat-empty-copy">
        Describe the signal you want to investigate. ThesisTrace will use the
        selected registered model and only this Chat thread's memory.
      </p>
      {status === "loading-history" ? (
        <p className="chat-history-status" role="status">Loading conversation…</p>
      ) : null}
    </section>
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
      <div>
        <p className="chat-catalog-error" role="alert">
          The previous model selection is no longer available. Choose a registered model.
        </p>
        <div className="chat-model-controls" aria-label="Agent model settings">
          <div className="chat-model-field">
            <label htmlFor="chat-model">Model</label>
            <select
              id="chat-model"
              onChange={(event) => onModelChange(event.target.value)}
              value=""
            >
              <option disabled value="">Select a model</option>
              {catalogState.catalog.models.map((model) => (
                <option key={model.key} value={model.key}>{model.display_name}</option>
              ))}
            </select>
          </div>
          <div className="chat-model-field">
            <label htmlFor="chat-reasoning">Reasoning</label>
            <select disabled id="chat-reasoning" value="">
              <option value="">Select a model first</option>
            </select>
          </div>
        </div>
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
    <div className="chat-model-controls" aria-label="Agent model settings">
      <div className="chat-model-field">
        <label htmlFor="chat-model">Model</label>
        <select
          id="chat-model"
          onChange={(event) => onModelChange(event.target.value)}
          value={selection.model.key}
        >
          {catalogState.catalog.models.map((model) => (
            <option key={model.key} value={model.key}>{model.display_name}</option>
          ))}
        </select>
      </div>
      <div className="chat-model-field">
        <label htmlFor="chat-reasoning">Reasoning</label>
        <select
          id="chat-reasoning"
          onChange={(event) => onReasoningChange(event.target.value)}
          value={selection.reasoningEffort}
        >
          {selection.model.reasoning_efforts.map((effort) => (
            <option key={effort} value={effort}>{reasoningEffortLabel(effort)}</option>
          ))}
        </select>
      </div>
    </div>
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
): AgentSessionPreferenceState {
  const [state, setState] = useState<AgentSessionPreferenceState>(
    thread.persisted ? { status: "loading" } : { status: "not-required" },
  );
  useEffect(() => {
    if (!thread.persisted) {
      setState({ status: "not-required" });
      return;
    }
    const controller = new AbortController();
    setState({ status: "loading" });
    void loadAgentSessionPreference(thread.id, controller.signal)
      .then((preference) => setState({ preference, status: "ready" }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (error instanceof AgentSessionPreferenceNotFoundError) {
          setState({ status: "not-found" });
        } else if (error instanceof AgentSessionPreferenceInvalidError) {
          setState({ status: "invalid" });
        } else {
          setState({ status: "unavailable" });
        }
      });
    return () => controller.abort();
  }, [thread.id, thread.persisted]);
  return state;
}

export function readBrowserChatThread(
  search: string,
  createId: () => string = () => crypto.randomUUID(),
): BrowserChatThread {
  const parameters = new URLSearchParams(search);
  const sessions = parameters.getAll("session");
  const session = sessions.length === 1 ? sessions[0] : undefined;
  if (session !== undefined && uuidPattern.test(session)) {
    return { id: session.toLowerCase(), persisted: true };
  }
  return { id: createId(), persisted: false };
}

export function chatSessionHref(threadId: string): string {
  const parameters = new URLSearchParams({ session: threadId });
  return `/chat?${parameters.toString()}`;
}

export function chatMessageBytes(message: string): number {
  return new TextEncoder().encode(message).byteLength;
}

export function chatTimelineItems(
  messages: readonly Message[],
  liveActivities: readonly ChatToolActivity[] = [],
): readonly ChatTimelineItem[] {
  const liveById = new Map(liveActivities.map((activity) => [activity.id, activity]));
  const resultByToolCall = new Map<string, SafeToolResult | null>();
  for (const message of messages) {
    if (message.role !== "tool") continue;
    resultByToolCall.set(message.toolCallId, parseSafeToolResult(message.content));
  }

  const representedToolCalls = new Set<string>();
  const items: ChatTimelineItem[] = [];
  for (const message of messages) {
    if (message.role === "user" && typeof message.content === "string") {
      items.push({
        content: message.content,
        id: `message:${message.id}`,
        kind: "message",
        role: "user",
      });
      continue;
    }
    if (message.role !== "assistant") continue;
    const content = typeof message.content === "string" ? message.content : "";
    const toolCalls = message.toolCalls ?? [];
    for (const toolCall of toolCalls) {
      representedToolCalls.add(toolCall.id);
      const live = liveById.get(toolCall.id);
      const persistedResult = resultByToolCall.get(toolCall.id);
      items.push({
        activity: {
          ...(live?.durationMs === undefined ? {} : { durationMs: live.durationMs }),
          id: toolCall.id,
          name: toolCall.function.name,
          ...(persistedResult?.resource === undefined && live?.resource === undefined
            ? {}
            : { resource: persistedResult?.resource ?? live?.resource }),
          ...(live?.startedAtMs === undefined ? {} : { startedAtMs: live.startedAtMs }),
          status: resultByToolCall.has(toolCall.id)
            ? persistedResult?.outcome ?? "failed"
            : live?.status ?? "running",
        },
        id: `tool:${toolCall.id}`,
        kind: "tool",
      });
    }
    if (content.length > 0 || toolCalls.length === 0) {
      items.push({
        content,
        id: `message:${message.id}`,
        kind: "message",
        role: "assistant",
      });
    }
  }
  for (const activity of liveActivities) {
    if (representedToolCalls.has(activity.id)) continue;
    items.push({ activity, id: `tool:${activity.id}`, kind: "tool" });
  }
  return items;
}

export function ToolActivityRow({ activity }: { activity: ChatToolActivity }) {
  const statusLabel = activity.status === "running"
    ? "Running"
    : activity.status === "completed"
      ? "Completed"
      : "Failed";
  const Icon = activity.status === "running"
    ? CircleNotch
    : activity.status === "completed"
      ? CheckCircle
      : WarningCircle;
  return (
    <article
      aria-label={`Tool ${activity.name}: ${statusLabel}`}
      className={`chat-tool-activity chat-tool-activity-${activity.status}`}
    >
      <Icon aria-hidden="true" size={15} weight="regular" />
      <span className="chat-tool-kind">MCP Tool</span>
      <code>{activity.name}</code>
      <span className="chat-tool-status">{statusLabel}</span>
      <span className="chat-tool-duration">
        {activity.durationMs === undefined
          ? activity.status === "running" ? "In progress" : "Duration unavailable"
          : formatToolDuration(activity.durationMs)}
      </span>
      {activity.resource === undefined ? null : (
        <a
          className="chat-tool-resource"
          href={researchRunHref(activity.resource)}
        >
          <span>ResearchRun</span>
          <code>{activity.resource.id}</code>
          <span>{activity.resource.status}</span>
        </a>
      )}
    </article>
  );
}

const RESEARCH_MARKDOWN_REMARK_PLUGINS = [remarkGfm];

export function AssistantMarkdown({
  content,
  streaming = true,
}: {
  content: string;
  streaming?: boolean;
}) {
  return (
    <div
      className={`chat-assistant-markdown chat-assistant-markdown-${streaming ? "streaming" : "static"}`}
    >
      <ReactMarkdown
        components={{
          a: SafeMarkdownLink,
          code: SafeMarkdownCode,
          img: HiddenMarkdownImage,
          pre: SafeMarkdownPre,
        }}
        remarkPlugins={RESEARCH_MARKDOWN_REMARK_PLUGINS}
        skipHtml
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function SafeMarkdownLink({
  children,
  href,
}: React.AnchorHTMLAttributes<HTMLAnchorElement> & { node?: unknown }) {
  const safeHref = parseResearchRunHref(href);
  return safeHref === null
    ? <span className="chat-markdown-link-disabled">{children}</span>
    : <a className="chat-markdown-run-link" href={safeHref}>{children}</a>;
}

function SafeMarkdownCode({
  children,
  className,
}: React.HTMLAttributes<HTMLElement> & { node?: unknown }) {
  return <code className={className}>{children}</code>;
}

function SafeMarkdownPre({
  children,
}: React.HTMLAttributes<HTMLPreElement> & { node?: unknown }) {
  return <pre>{children}</pre>;
}

function HiddenMarkdownImage(
  _props: React.ImgHTMLAttributes<HTMLImageElement> & { node?: unknown },
) {
  return null;
}

function conversationStatusLabel(status: ConversationStatus, ready: boolean): string {
  if (!ready) return "Connecting to Research Agent…";
  switch (status) {
    case "idle": return "Ready";
    case "loading-history": return "Loading conversation…";
    case "starting": return "Starting run…";
    case "running": return "Research Agent is responding…";
    case "complete": return "Run complete";
    case "failed": return "Run failed";
    case "disconnected": return "Agent disconnected";
  }
}

function formatToolDuration(durationMs: number): string {
  if (durationMs < 1_000) return `${Math.max(1, Math.round(durationMs))} ms`;
  return `${(durationMs / 1_000).toFixed(durationMs < 10_000 ? 2 : 1)} s`;
}

function monotonicNow(): number {
  return typeof performance === "undefined" ? Date.now() : performance.now();
}
