import {
  ChartLineUp, ClockCounterClockwise, Database, Flask, List, NotePencil,
  ShieldCheck, SidebarSimple, X, type IconProps,
} from "@phosphor-icons/react";
import {
  createContext, useContext, useEffect, useRef, useState,
  type ComponentType, type CSSProperties, type KeyboardEvent, type ReactNode,
} from "react";

import { AccountMenu } from "../auth/AccountMenu";
import { Brand } from "../brand/Brand";
import { McpIcon } from "./McpIcon";
import { SessionHistoryList } from "../chat/SessionHistoryList";
import type { SessionHistoryController } from "../chat/useSessionHistory";
import { handleWorkspaceNavigation, type WorkspaceNavigate } from "./navigation";
import { useTranslation } from "../i18n";

const resourceRoutes = [

  { path: "/data", label: "data", icon: Database },
  { path: "/research", label: "research", icon: Flask },
  { path: "/research-runs", label: "researchRuns", icon: ChartLineUp },
  { path: "/daily-tracks", label: "dailyTracks", icon: ClockCounterClockwise },
  { path: "/connections/mcp", label: "mcp", icon: McpIcon },
] as const;
const operatorRoute = {
  activeRoot: "/operator", path: "/operator/researchers", label: "operator", icon: ShieldCheck,
} as const;

type WorkspaceContextValue = Readonly<{
  navigate: WorkspaceNavigate;
  sessionHistory: SessionHistoryController;
}>;
const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function useWorkspace(): WorkspaceContextValue {
  const workspace = useContext(WorkspaceContext);
  if (workspace === null) throw new Error("Workspace content requires AppShell");
  return workspace;
}

type AppShellProps = {
  currentPath: string;
  currentSessionId: string | null;
  isNewChat: boolean;
  children: ReactNode;
  isOperator: boolean;
  navigate: WorkspaceNavigate;
  sessionHistory: SessionHistoryController;
};

export function AppShell({
  currentPath, currentSessionId, isNewChat, children, isOperator, navigate, sessionHistory,
}: AppShellProps) {
  const { t } = useTranslation("navigation");
  const isChat = currentPath === "/chat";
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(224);
  const [isResizing, setIsResizing] = useState(false);
  const resizeSidebar = (width: number) => setSidebarWidth(Math.max(224, Math.min(400, width)));
  const [isNavigationOpen, setIsNavigationOpen] = useState(false);
  const mobileViewport = useMobileViewport();
  const mobileNavigationCloseRef = useRef<HTMLButtonElement>(null);
  const mobileNavigationToggleRef = useRef<HTMLButtonElement>(null);
  const newChatRef = useRef<HTMLAnchorElement>(null);

  useEffect(() => {
    if (!isNavigationOpen) return;
    mobileNavigationCloseRef.current?.focus({ preventScroll: true });
  }, [isNavigationOpen]);

  function closeNavigation(): void {
    setIsNavigationOpen(false);
    window.requestAnimationFrame(() => mobileNavigationToggleRef.current?.focus({ preventScroll: true }));
  }

  const openPage: WorkspaceNavigate = (href, options) => {
    navigate(href, options);
    if (isNavigationOpen) closeNavigation();
  };

  function handleNavigationKeyboard(event: KeyboardEvent<HTMLElement>): void {
    if (!isNavigationOpen || event.defaultPrevented) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      closeNavigation();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...event.currentTarget.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), summary, input:not([disabled]), select:not([disabled]), textarea:not([disabled])',
    )].filter((element) => {
      // Closed details can still report layout boxes for their hidden controls.
      const closedDetails = element.closest("details:not([open])");
      return element.getClientRects().length > 0 && (
        closedDetails === null || element === closedDetails.querySelector(":scope > summary")
      );
    });
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

  const mobileNavigationToggle = (
    <button aria-controls="primary-navigation" aria-expanded={isNavigationOpen}
      aria-label={t("open")}
      className="mobile-navigation-toggle"
      onClick={() => setIsNavigationOpen(true)} ref={mobileNavigationToggleRef} type="button">
      <List aria-hidden="true" size={19} weight="regular" />
    </button>
  );

  return (
    <WorkspaceContext value={{ navigate: openPage, sessionHistory }}>
      <div style={{ "--sidebar-expanded": `${sidebarWidth}px` } as CSSProperties}
        className={`app-shell${isChat ? " app-shell-chat" : ""}${currentPath === "/research" ? " app-shell-research" : ""}${isCollapsed ? " app-shell-collapsed" : ""}${isNavigationOpen ? " app-shell-navigation-open" : ""}${isResizing ? " app-shell-resizing" : ""}`}>
        <aside
          aria-hidden={mobileViewport && !isNavigationOpen ? true : undefined}
          aria-label={mobileViewport && isNavigationOpen ? t("navigation") : undefined}
          aria-modal={mobileViewport && isNavigationOpen ? true : undefined}
          className="application-sidebar"
          id="primary-navigation"
          inert={mobileViewport && !isNavigationOpen ? true : undefined}
          onKeyDown={handleNavigationKeyboard}
          role={mobileViewport && isNavigationOpen ? "dialog" : undefined}
        >
          <div className="sidebar-brand-row">
            <a className="brand" aria-label={t("home")} href="/">
              <Brand className="brand-mark" wordmarkClassName="sidebar-label" inverse />
            </a>
            <button aria-controls="primary-navigation" aria-expanded={!isCollapsed}
              aria-label={t(isCollapsed ? "expand" : "collapse")}
              className="sidebar-toggle" onClick={() => setIsCollapsed((collapsed) => !collapsed)}
              title={t(isCollapsed ? "expand" : "collapse")} type="button">
              <SidebarSimple aria-hidden="true" size={18} weight="regular" />
            </button>
            <button aria-label={t("close")} className="mobile-navigation-close"
              onClick={closeNavigation} ref={mobileNavigationCloseRef} type="button">
              <X aria-hidden="true" size={18} weight="regular" />
            </button>
          </div>
          <a aria-current={isNewChat ? "page" : undefined} className="sidebar-new-chat" href="/chat"
            onClick={(event) => handleWorkspaceNavigation(event, () => openPage("/chat"))}
            ref={newChatRef} title={t("newChat")}>
            <NotePencil aria-hidden="true" size={18} weight="regular" />
            <span className="sidebar-label">{t("newChat")}</span>
          </a>
          <nav aria-label={t("workspace")} className="resource-nav">
            {resourceRoutes.map((resource) => (
              <ResourceLink currentPath={currentPath} key={resource.path} navigate={openPage} resource={resource} />
            ))}
          </nav>
          <section aria-label={t("chats")} className="chat-session-region">
            <SessionHistoryList
              controller={sessionHistory}
              currentSessionId={currentSessionId}
              navigate={openPage}
              navigationInteractive={!mobileViewport || isNavigationOpen}
              restoreFocus={(deletedCurrentSession) => {
                if (mobileViewport && (deletedCurrentSession || !isNavigationOpen)) {
                  mobileNavigationToggleRef.current?.focus();
                } else newChatRef.current?.focus();
              }}
            />
          </section>
          {isOperator ? (
            <nav aria-label={t("operator")} className="resource-nav operator-nav">
              <ResourceLink currentPath={currentPath} navigate={openPage} resource={operatorRoute} />
            </nav>
          ) : null}
          <div className="sidebar-account-area"><AccountMenu /></div>
          {!mobileViewport && !isCollapsed ? (
            <div className="sidebar-resize-handle" role="separator" tabIndex={0}
              aria-label={t("resize")} aria-orientation="vertical" aria-controls="primary-navigation"
              aria-valuemin={224} aria-valuemax={400} aria-valuenow={sidebarWidth}
              onPointerDown={(event) => {
                if (event.button !== 0) return;
                event.preventDefault();
                event.currentTarget.focus();
                event.currentTarget.setPointerCapture(event.pointerId);
                setIsResizing(true);
              }}
              onPointerMove={(event) => {
                if (event.currentTarget.hasPointerCapture(event.pointerId)) resizeSidebar(event.clientX);
              }}
              onPointerUp={(event) => {
                if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
                setIsResizing(false);
              }}
              onLostPointerCapture={() => setIsResizing(false)}
              onKeyDown={(event) => {
                if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
                event.preventDefault();
                resizeSidebar(event.key === "Home" ? 224 : event.key === "End" ? 400 : sidebarWidth + (event.key === "ArrowRight" ? 16 : -16));
              }}
            />
          ) : null}
        </aside>
        <div className="application-frame">
          {mobileNavigationToggle}
          {isChat ? children : <main className="main-content">{children}</main>}
        </div>
        <button aria-label={t("close")} className="navigation-backdrop"
          onClick={closeNavigation} type="button" />
      </div>
    </WorkspaceContext>
  );
}

function ResourceLink({ currentPath, navigate, resource }: {
  currentPath: string;
  navigate: WorkspaceNavigate;
  resource: Readonly<{ icon: ComponentType<IconProps>; label: typeof resourceRoutes[number]["label"] | typeof operatorRoute.label; path: string; activeRoot?: string }>;
}) {
  const { t } = useTranslation("navigation");
  const Icon = resource.icon;
  const isCurrent = isResourceCurrent(currentPath, resource);
  return (
    <a aria-current={isCurrent ? "page" : undefined} href={resource.path}
      onClick={(event) => handleWorkspaceNavigation(event, () => navigate(resource.path))} title={t(resource.label)}>
      <Icon aria-hidden="true" size={18} weight={isCurrent ? "fill" : "regular"} />
      <span className="sidebar-label">{t(resource.label)}</span>
    </a>
  );
}

function isResourceCurrent(currentPath: string, resource: Readonly<{ activeRoot?: string; path: string }>): boolean {
  return currentPath === resource.path || currentPath.startsWith(`${resource.activeRoot ?? resource.path}/`);
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
