import { lazy, Suspense } from "react";

import { AppShell } from "./AppShell";

const DataPage = lazy(() =>
  import("../data/DataPage").then(({ DataPage }) => ({ default: DataPage })),
);
const DailyTracksPage = lazy(() =>
  import("../daily-tracks/DailyTracksPage").then(({ DailyTracksPage }) => ({
    default: DailyTracksPage,
  })),
);
const ResearchWorkspacePage = lazy(() =>
  import("../research/ResearchWorkspacePage").then(({ ResearchWorkspacePage }) => ({
    default: ResearchWorkspacePage,
  })),
);
const ResearchRunsPage = lazy(() =>
  import("../research-runs/ResearchRunsPage").then(({ ResearchRunsPage }) => ({
    default: ResearchRunsPage,
  })),
);

export function CoreApp({ currentPath, researcherId }: {
  currentPath: string;
  researcherId: string;
}) {
  const researchRunMatch = currentPath.match(/^\/research-runs\/(run_[a-f0-9]+)$/);
  const dailyTrackMatch = currentPath.match(/^\/daily-tracks\/(track_[a-f0-9]+)$/);
  return (
    <AppShell currentPath={currentPath}>
      <Suspense
        fallback={<section className="state-section"><p>Loading workspace…</p></section>}
      >
        {currentPath === "/data" ? <DataPage /> : null}
        {currentPath === "/research" ? (
          <ResearchWorkspacePage researcherId={researcherId} />
        ) : null}
        {currentPath === "/research-runs" || researchRunMatch ? (
          <ResearchRunsPage researcherId={researcherId} runId={researchRunMatch?.[1]} />
        ) : null}
        {currentPath === "/daily-tracks" || dailyTrackMatch ? (
          <DailyTracksPage trackId={dailyTrackMatch?.[1]} />
        ) : null}
        {currentPath !== "/data" &&
        currentPath !== "/research" &&
        !currentPath.startsWith("/research-runs") &&
        !currentPath.startsWith("/daily-tracks") ? (
          <div aria-label="Resource outlet" />
        ) : null}
      </Suspense>
    </AppShell>
  );
}
