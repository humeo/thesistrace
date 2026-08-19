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
  const isResearch = currentPath === "/research";

  return (
    <div className={`app-shell${isResearch ? " app-shell-research" : ""}`}>
      <header className="global-header">
        <a className="brand" aria-label="ThesisTrace home" href="/data">
          ThesisTrace
        </a>
        <nav aria-label="Product resources" className="resource-nav">
          {resourceRoutes.map((resource) => (
            <a
              aria-current={
                currentPath === resource.path || currentPath.startsWith(`${resource.path}/`)
                  ? "page"
                  : undefined
              }
              href={resource.path}
              key={resource.path}
            >
              {resource.label}
            </a>
          ))}
        </nav>
      </header>
      <main className="main-content">{children}</main>
    </div>
  );
}
