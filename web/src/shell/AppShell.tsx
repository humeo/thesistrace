import {
  ChartLineUp,
  ClockCounterClockwise,
  ChatCircle,
  Database,
  Flask,
  List,
  ShieldCheck,
  SidebarSimple,
  X,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { AccountMenu } from "../auth/AccountMenu";

const resourceRoutes = [
  { path: "/chat", label: "Chat", icon: ChatCircle },
  { path: "/data", label: "Data", icon: Database },
  { path: "/research", label: "Research", icon: Flask },
  { path: "/research-runs", label: "Research Runs", icon: ChartLineUp },
  { path: "/daily-tracks", label: "Daily Tracks", icon: ClockCounterClockwise },
] as const;

const operatorRoute = {
  activeRoot: "/operator",
  path: "/operator/researchers",
  label: "Operator",
  icon: ShieldCheck,
} as const;

type AppShellProps = {
  currentPath: string;
  children: ReactNode;
  isOperator: boolean;
};

export function AppShell({ currentPath, children, isOperator }: AppShellProps) {
  const isResearch = currentPath === "/research";
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isNavigationOpen, setIsNavigationOpen] = useState(false);
  const mobileNavigationRef = useRef<HTMLElement>(null);
  const mobileNavigationCloseRef = useRef<HTMLButtonElement>(null);
  const mobileNavigationToggleRef = useRef<HTMLButtonElement>(null);
  const currentResource = [...resourceRoutes, ...(isOperator ? [operatorRoute] : [])]
    .find((resource) => isResourceCurrent(currentPath, resource));

  useEffect(() => {
    if (!isNavigationOpen) return;
    mobileNavigationCloseRef.current?.focus();
    const handleNavigationKeyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setIsNavigationOpen(false);
        requestAnimationFrame(() => mobileNavigationToggleRef.current?.focus());
        return;
      }
      if (event.key !== "Tab") return;
      const navigation = mobileNavigationRef.current;
      if (navigation === null) return;
      const focusable = [...navigation.querySelectorAll<HTMLElement>(
        "a[href], button:not([disabled]), [tabindex]:not([tabindex='-1'])",
      )].filter((element) => element.getAttribute("aria-hidden") !== "true");
      const first = focusable.at(0);
      const last = focusable.at(-1);
      if (first === undefined || last === undefined) return;
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !navigation.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !navigation.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleNavigationKeyboard);
    return () => document.removeEventListener("keydown", handleNavigationKeyboard);
  }, [isNavigationOpen]);

  const closeNavigation = () => {
    setIsNavigationOpen(false);
    requestAnimationFrame(() => mobileNavigationToggleRef.current?.focus());
  };

  return (
    <div
      className={`app-shell${isResearch ? " app-shell-research" : ""}${isCollapsed ? " app-shell-collapsed" : ""}${isNavigationOpen ? " app-shell-navigation-open" : ""}`}
    >
      <aside
        aria-label={isNavigationOpen ? "Navigation" : undefined}
        aria-modal={isNavigationOpen ? true : undefined}
        className="application-sidebar"
        id="primary-navigation"
        ref={mobileNavigationRef}
        role={isNavigationOpen ? "dialog" : undefined}
      >
        <div className="sidebar-brand-row">
          <a className="brand" aria-label="ThesisTrace home" href="/data">
            <span className="brand-mark" aria-hidden="true">T</span>
            <span className="brand-name">ThesisTrace</span>
          </a>
          <button
            aria-label="Close navigation"
            className="mobile-navigation-close"
            onClick={closeNavigation}
            ref={mobileNavigationCloseRef}
            type="button"
          >
            <X aria-hidden="true" size={18} weight="regular" />
          </button>
        </div>
        <nav aria-label="Product resources" className="resource-nav">
          {resourceRoutes.map((resource) => (
            <ResourceLink
              currentPath={currentPath}
              key={resource.path}
              resource={resource}
            />
          ))}
        </nav>
        <div className="sidebar-bottom">
          {isOperator ? (
            <nav aria-label="Operator" className="resource-nav operator-nav">
              <ResourceLink currentPath={currentPath} resource={operatorRoute} />
            </nav>
          ) : null}
          <div className="sidebar-footer">
            <span className="sidebar-footer-label">Research workspace</span>
            <span className="sidebar-footer-short" aria-hidden="true">TT</span>
          </div>
        </div>
      </aside>
      <div className="application-frame">
        <header className="context-bar">
          <div className="context-bar-leading">
            <button
              aria-controls="primary-navigation"
              aria-expanded={isNavigationOpen}
              aria-label="Open navigation"
              className="mobile-navigation-toggle"
              onClick={() => setIsNavigationOpen(true)}
              ref={mobileNavigationToggleRef}
              type="button"
            >
              <List aria-hidden="true" size={19} weight="regular" />
            </button>
            <button
              aria-controls="primary-navigation"
              aria-expanded={!isCollapsed}
              aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              className="sidebar-toggle"
              onClick={() => setIsCollapsed((collapsed) => !collapsed)}
              type="button"
            >
              <SidebarSimple aria-hidden="true" size={18} weight="regular" />
            </button>
            <div className="context-breadcrumb" aria-label="Current resource">
              <span>Workspace</span>
              <span aria-hidden="true">/</span>
              <strong>{currentResource?.label ?? "Resource"}</strong>
            </div>
          </div>
          <AccountMenu />
        </header>
        <main className="main-content">{children}</main>
      </div>
      <button
        aria-label="Close navigation"
        className="navigation-backdrop"
        onClick={closeNavigation}
        type="button"
      />
    </div>
  );
}

function ResourceLink({
  currentPath,
  resource,
}: {
  currentPath: string;
  resource: Readonly<{
    icon: typeof Database;
    label: string;
    path: string;
    activeRoot?: string;
  }>;
}) {
  const Icon = resource.icon;
  const isCurrent = isResourceCurrent(currentPath, resource);
  return (
    <a aria-current={isCurrent ? "page" : undefined} href={resource.path} title={resource.label}>
      <Icon aria-hidden="true" size={18} weight={isCurrent ? "fill" : "regular"} />
      <span>{resource.label}</span>
    </a>
  );
}

function isResourceCurrent(
  currentPath: string,
  resource: Readonly<{ activeRoot?: string; path: string }>,
): boolean {
  const activeRoot = resource.activeRoot ?? resource.path;
  return currentPath === resource.path || currentPath.startsWith(`${activeRoot}/`);
}
