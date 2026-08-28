import {
  ChartLineUp,
  ClockCounterClockwise,
  Database,
  Flask,
  List,
  SidebarSimple,
  X,
} from "@phosphor-icons/react";
import { useState, type ReactNode } from "react";

import { AccountMenu } from "../auth/AccountMenu";

const resourceRoutes = [
  { path: "/data", label: "Data", icon: Database },
  { path: "/research", label: "Research", icon: Flask },
  { path: "/research-runs", label: "Research Runs", icon: ChartLineUp },
  { path: "/daily-tracks", label: "Daily Tracks", icon: ClockCounterClockwise },
] as const;

type AppShellProps = {
  currentPath: string;
  children: ReactNode;
};

export function AppShell({ currentPath, children }: AppShellProps) {
  const isResearch = currentPath === "/research";
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isNavigationOpen, setIsNavigationOpen] = useState(false);
  const currentResource = resourceRoutes.find(
    (resource) => currentPath === resource.path || currentPath.startsWith(`${resource.path}/`),
  );

  return (
    <div
      className={`app-shell${isResearch ? " app-shell-research" : ""}${isCollapsed ? " app-shell-collapsed" : ""}${isNavigationOpen ? " app-shell-navigation-open" : ""}`}
    >
      <aside className="application-sidebar" id="primary-navigation">
        <div className="sidebar-brand-row">
          <a className="brand" aria-label="ThesisTrace home" href="/data">
            <span className="brand-mark" aria-hidden="true">T</span>
            <span className="brand-name">ThesisTrace</span>
          </a>
          <button
            aria-label="Close navigation"
            className="mobile-navigation-close"
            onClick={() => setIsNavigationOpen(false)}
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
        <div className="sidebar-footer">
          <span className="sidebar-footer-label">Research workspace</span>
          <span className="sidebar-footer-short" aria-hidden="true">TT</span>
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
        onClick={() => setIsNavigationOpen(false)}
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
  resource: (typeof resourceRoutes)[number];
}) {
  const Icon = resource.icon;
  const isCurrent = currentPath === resource.path || currentPath.startsWith(`${resource.path}/`);
  return (
    <a aria-current={isCurrent ? "page" : undefined} href={resource.path} title={resource.label}>
      <Icon aria-hidden="true" size={18} weight={isCurrent ? "fill" : "regular"} />
      <span>{resource.label}</span>
    </a>
  );
}
