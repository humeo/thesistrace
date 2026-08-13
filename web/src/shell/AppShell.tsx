import type { ReactNode } from "react";

const resourceRoutes = [
  { path: "/data", label: "Data" },
  { path: "/research", label: "Research" },
  { path: "/research-runs", label: "Research Runs" },
  { path: "/daily-tracks", label: "Daily Tracks" },
] as const;

type AppShellProps = {
  currentPath: string;
  children: ReactNode;
};

export function AppShell({ currentPath, children }: AppShellProps) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand" aria-label="ThesisTrace home">
          <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
          <span><strong>Thesis</strong><em>Trace</em></span>
        </div>
        <p className="sidebar-kicker">Research workspace</p>
        <nav aria-label="Product resources" className="resource-nav">
          {resourceRoutes.map((resource, index) => (
            <a
              aria-current={
                currentPath === resource.path || currentPath.startsWith(`${resource.path}/`)
                  ? "page"
                  : undefined
              }
              href={resource.path}
              key={resource.path}
            >
              <span className="nav-index">0{index + 1}</span>
              <span>{resource.label}</span>
              <span className="nav-arrow" aria-hidden="true">↗</span>
            </a>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className="health-dot" />
          <span>Local core online</span>
          <span className="sidebar-version">v0.1</span>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumb"><span>THESIS /</span> {labelForPath(currentPath)}</div>
          <div className="topbar-actions">
            <div className="topbar-meta"><span className="live-pulse" /> Canonical data · local</div>
            <a className="global-new-research" href="/research?new">New Research</a>
          </div>
        </header>
        <main className="main-content">{children}</main>
      </div>
    </div>
  );
}

function labelForPath(path: string) {
  if (path.startsWith("/research") && !path.startsWith("/research-runs")) return "RESEARCH";
  if (path.startsWith("/research-runs")) return "RESEARCH RUNS";
  if (path.startsWith("/daily-tracks")) return "DAILY TRACKS";
  return "DATA ROOM";
}
