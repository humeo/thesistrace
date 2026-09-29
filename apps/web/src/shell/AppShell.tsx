import {
  ChartLineUp, ClockCounterClockwise, Database, Flask, NotePencil,
  ShieldCheck, X, type IconProps,
} from "@phosphor-icons/react";
import {
  createContext, useContext, useEffect, useRef, useState,
  type ComponentType, type CSSProperties, type ReactNode,
} from "react";

import { AccountMenu } from "../auth/AccountMenu";
import { Brand } from "../brand/Brand";
import { SessionDecisionDialog, SessionHistoryList, type SessionDialog } from "../chat/SessionHistoryList";
import type { SessionHistoryController } from "../chat/useSessionHistory";
import { Button } from "../components/ui/button";
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarHeader, SidebarMenu,
  SidebarMenuButton, SidebarMenuItem, SidebarProvider, SidebarTrigger, useSidebar,
} from "../components/ui/sidebar";
import { useTranslation } from "../i18n";
import { McpIcon } from "./McpIcon";
import { handleWorkspaceNavigation, type WorkspaceNavigate } from "./navigation";

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

export function AppShell(props: AppShellProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(240);
  const [isResizing, setIsResizing] = useState(false);
  const resizeSidebar = (width: number) => setSidebarWidth(Math.max(240, Math.min(400, width)));
  const isChat = props.currentPath === "/chat";
  return (
    <SidebarProvider
      className={`app-shell${isChat ? " app-shell-chat" : ""}${props.currentPath === "/research" ? " app-shell-research" : ""}${isCollapsed ? " app-shell-collapsed" : ""}${isResizing ? " app-shell-resizing" : ""}`}
      open={!isCollapsed}
      onOpenChange={(expanded) => setIsCollapsed(!expanded)}
      style={{ "--sidebar-width": `${sidebarWidth}px`, "--sidebar-expanded": `${sidebarWidth}px`, "--sidebar-width-icon": "56px" } as CSSProperties}
    >
      <WorkspaceShellContent {...props} sidebarWidth={sidebarWidth} resizeSidebar={resizeSidebar} setIsResizing={setIsResizing} />
    </SidebarProvider>
  );
}

function WorkspaceShellContent({
  currentPath, currentSessionId, isNewChat, children, isOperator, navigate, sessionHistory,
  sidebarWidth, resizeSidebar, setIsResizing,
}: AppShellProps & {
  sidebarWidth: number;
  resizeSidebar: (width: number) => void;
  setIsResizing: (value: boolean) => void;
}) {
  const { t } = useTranslation("navigation");
  const { isMobile, open, openMobile, setOpenMobile } = useSidebar();
  const newChatRef = useRef<HTMLAnchorElement>(null);
  const mobileNavigationToggleRef = useRef<HTMLButtonElement>(null);
  const [sessionDialog, setSessionDialog] = useState<SessionDialog | null>(null);
  const wasMobileOpen = useRef(openMobile);
  useEffect(() => {
    if (isMobile && wasMobileOpen.current && !openMobile) {
      window.requestAnimationFrame(() => mobileNavigationToggleRef.current?.focus({ preventScroll: true }));
    }
    wasMobileOpen.current = openMobile;
  }, [isMobile, openMobile]);
  const openPage: WorkspaceNavigate = (href, options) => {
    navigate(href, options);
    if (openMobile) setOpenMobile(false);
  };
  const restoreHistoryFocus = (deletedCurrentSession: boolean) => {
    if (isMobile && (deletedCurrentSession || !openMobile)) {
      if (deletedCurrentSession) setOpenMobile(false);
      window.requestAnimationFrame(() => mobileNavigationToggleRef.current?.focus());
    } else newChatRef.current?.focus();
  };

  return (
    <WorkspaceContext value={{ navigate: openPage, sessionHistory }}>
      <Sidebar id="primary-navigation" className="application-sidebar" collapsible="icon" mobileTitle={t("navigation")}>
        <SidebarHeader className="sidebar-primary-header p-0">
          <div className="sidebar-brand-row">
            <a className="brand" aria-label={t("home")} href="/">
              <Brand className="brand-mark" wordmarkClassName="sidebar-label" inverse />
            </a>
            {!isMobile ? (
              <SidebarTrigger
                aria-controls="primary-navigation"
                aria-expanded={open}
                aria-label={t(open ? "collapse" : "expand")}
                className="sidebar-toggle"
                title={t(open ? "collapse" : "expand")}
              />
            ) : (
              <Button aria-label={t("close")} autoFocus className="mobile-navigation-close" onClick={() => setOpenMobile(false)} size="icon" variant="ghost" type="button">
                <X aria-hidden="true" size={18} weight="regular" />
              </Button>
            )}
          </div>
          <SidebarMenu className="sidebar-new-chat-menu">
            <SidebarMenuItem>
              <SidebarMenuButton
                render={<a href="/chat" onClick={(event) => handleWorkspaceNavigation(event, () => openPage("/chat"))} ref={newChatRef} />}
                isActive={isNewChat}
                aria-current={isNewChat ? "page" : undefined}
                className="sidebar-new-chat"
                tooltip={t("newChat")}
              >
                <NotePencil aria-hidden="true" size={18} weight="regular" />
                <span className="sidebar-label">{t("newChat")}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
          <nav aria-label={t("workspace")} className="resource-nav">
            <SidebarMenu>
              {resourceRoutes.map((resource) => (
                <ResourceLink currentPath={currentPath} key={resource.path} navigate={openPage} resource={resource} />
              ))}
            </SidebarMenu>
          </nav>
        </SidebarHeader>
        <SidebarContent className="overflow-hidden">
          <section aria-label={t("chats")} className="chat-session-region">
            <SessionHistoryList
              controller={sessionHistory}
              currentSessionId={currentSessionId}
              navigate={openPage}
              navigationInteractive={!isMobile || openMobile}
              restoreFocus={restoreHistoryFocus}
              onDecision={setSessionDialog}
            />
          </section>
        </SidebarContent>
        <SidebarFooter className="gap-0 p-0">
          {isOperator ? (
            <nav aria-label={t("operator")} className="resource-nav operator-nav">
              <SidebarMenu><ResourceLink currentPath={currentPath} navigate={openPage} resource={operatorRoute} /></SidebarMenu>
            </nav>
          ) : null}
          <div className="sidebar-account-area"><AccountMenu /></div>
        </SidebarFooter>
        {!isMobile && open ? (
          <div className="sidebar-resize-handle" role="separator" tabIndex={0}
            aria-label={t("resize")} aria-orientation="vertical" aria-controls="primary-navigation"
            aria-valuemin={240} aria-valuemax={400} aria-valuenow={sidebarWidth}
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
              resizeSidebar(event.key === "Home" ? 240 : event.key === "End" ? 400 : sidebarWidth + (event.key === "ArrowRight" ? 16 : -16));
            }}
          />
        ) : null}
      </Sidebar>
      <div className="application-frame">
        <SidebarTrigger className="mobile-navigation-toggle" aria-controls="primary-navigation" aria-expanded={openMobile} aria-label={t("open")} ref={mobileNavigationToggleRef} />
        {currentPath === "/chat" ? children : <main className="main-content">{children}</main>}
      </div>
      {sessionDialog === null ? null : (
        <SessionDecisionDialog
          key={`${sessionDialog.kind}:${sessionDialog.session.id}`}
          controller={sessionHistory}
          dialog={sessionDialog}
          onClose={() => setSessionDialog(null)}
          onDeleted={(sessionId) => {
            setSessionDialog(null);
            if (sessionId === currentSessionId) openPage("/chat");
            restoreHistoryFocus(sessionId === currentSessionId);
          }}
        />
      )}
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
  const isCurrent = currentPath === resource.path || currentPath.startsWith(`${resource.activeRoot ?? resource.path}/`);
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        render={<a href={resource.path} onClick={(event) => handleWorkspaceNavigation(event, () => navigate(resource.path))} />}
        isActive={isCurrent}
        aria-current={isCurrent ? "page" : undefined}
        tooltip={t(resource.label)}
      >
        <Icon aria-hidden="true" size={18} weight={isCurrent ? "fill" : "regular"} />
        <span className="sidebar-label">{t(resource.label)}</span>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}
