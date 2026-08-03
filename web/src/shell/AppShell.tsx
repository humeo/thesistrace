import type { ReactNode } from "react";

const resourceRoutes = [
  { path: "/data", label: "Data" },
  { path: "/definitions", label: "Definitions" },
  { path: "/research-runs", label: "Research Runs" },
  { path: "/daily-tracks", label: "Daily Tracks" },
] as const;

export type ResourceRoute = (typeof resourceRoutes)[number]["path"];

type AppShellProps = {
  currentPath: ResourceRoute;
  children: ReactNode;
};

export function AppShell({ currentPath, children }: AppShellProps) {
  return (
    <div>
      <nav aria-label="Product resources">
        {resourceRoutes.map((resource) => (
          <a
            aria-current={currentPath === resource.path ? "page" : undefined}
            href={resource.path}
            key={resource.path}
          >
            {resource.label}
          </a>
        ))}
      </nav>
      <main>{children}</main>
    </div>
  );
}
