import { DataPage } from "../data/DataPage";
import { AppShell, type ResourceRoute } from "./AppShell";

const routes = new Set<ResourceRoute>([
  "/data",
  "/definitions",
  "/research-runs",
  "/daily-tracks",
]);

export function isCoreRoute(pathname: string): pathname is ResourceRoute {
  return routes.has(pathname as ResourceRoute);
}

export function CoreApp({ currentPath }: { currentPath: ResourceRoute }) {
  return (
    <AppShell currentPath={currentPath}>
      {currentPath === "/data" ? <DataPage /> : <div aria-label="Resource outlet" />}
    </AppShell>
  );
}
