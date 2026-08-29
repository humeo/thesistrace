import {
  ArrowUp,
  ChartLineUp,
  ChatCircle,
  ClockCounterClockwise,
  Database,
  Flask,
  List,
  NotePencil,
  SidebarSimple,
  X,
} from "@phosphor-icons/react";
import {
  useEffect,
  useReducer,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

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

export function ChatPage() {
  const { reload, state } = useAgentCatalog();
  return <ChatShell catalogState={state} reloadCatalog={reload} />;
}

export function ChatShell({
  catalogState,
  reloadCatalog,
}: {
  catalogState: AgentCatalogState;
  reloadCatalog: () => void;
}) {
  const [navigation, dispatchNavigation] = useReducer(
    chatNavigationReducer,
    initialChatNavigationState,
  );
  const [requestedModelKey, setRequestedModelKey] = useState<string | null>(null);
  const [requestedReasoning, setRequestedReasoning] = useState<string | null>(null);
  const mobileViewport = useMobileViewport();
  const mobileNavigationToggleRef = useRef<HTMLButtonElement>(null);
  const mobileNavigationCloseRef = useRef<HTMLButtonElement>(null);
  const selection = catalogState.status === "ready"
    ? resolveModelSelection(
      catalogState.catalog,
      requestedModelKey,
      requestedReasoning,
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

        <a aria-current="page" className="chat-new" href="/chat" title="New Chat">
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
          <div className="chat-session-empty">
            <ChatCircle aria-hidden="true" size={16} weight="regular" />
            <span>No conversations yet</span>
          </div>
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
              <strong>New chat</strong>
              <span>Research Agent</span>
            </div>
          </div>
          <span className="chat-model-context">
            {selection === null
              ? "Model catalog"
              : `${selection.model.display_name} · ${reasoningEffortLabel(selection.reasoningEffort)}`}
          </span>
        </header>

        <main className="chat-main">
          <section className="chat-empty-state">
            <span className="chat-empty-symbol" aria-hidden="true">α</span>
            <p className="eyebrow">Research Agent</p>
            <h1>Turn an investment idea into Alpha</h1>
            <p className="chat-empty-copy">
              Describe the signal you want to investigate. ThesisTrace will use the
              registered model and your research workspace when the conversation starts.
            </p>
            <CatalogControls
              catalogState={catalogState}
              onModelChange={(modelKey) => {
                setRequestedModelKey(modelKey);
                setRequestedReasoning(null);
              }}
              onReasoningChange={setRequestedReasoning}
              reloadCatalog={reloadCatalog}
              selection={selection}
            />
          </section>

          <div className="chat-composer-dock">
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
            <p>Registered models only · Session creation begins with the first message</p>
          </div>
        </main>
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
}: {
  catalogState: AgentCatalogState;
  onModelChange: (modelKey: string) => void;
  onReasoningChange: (reasoningEffort: string) => void;
  reloadCatalog: () => void;
  selection: ReturnType<typeof resolveModelSelection> | null;
}) {
  if (catalogState.status === "loading") {
    return <p className="chat-catalog-status" role="status">Loading registered models…</p>;
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
