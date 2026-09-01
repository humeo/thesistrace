import { lazy, Suspense } from "react";

import { AppShell } from "./AppShell";

const DataPage = lazy(() =>
  import("../data/DataPage").then(({ DataPage }) => ({ default: DataPage })),
);
const ChatPage = lazy(() =>
  import("../chat/ChatPage").then(({ ChatPage }) => ({ default: ChatPage })),
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
const OperatorResearchersPage = lazy(() =>
  import("../operator/OperatorResearchersPage").then(({ OperatorResearchersPage }) => ({
    default: OperatorResearchersPage,
  })),
);
const OperatorDataPage = lazy(() =>
  import("../operator/OperatorDataPage").then(({ OperatorDataPage }) => ({
    default: OperatorDataPage,
  })),
);

export function CoreApp({ currentPath, isOperator, researcherId }: {
  currentPath: string;
  isOperator: boolean;
  researcherId: string;
}) {
  if (currentPath === "/chat") {
    return (
      <Suspense
        fallback={<section className="state-section chat-route-loading"><p>Loading Chat…</p></section>}
      >
        <ChatPage researcherId={researcherId} />
      </Suspense>
    );
  }
  const researchRunMatch = currentPath.match(/^\/research-runs\/(run_[a-f0-9]+)$/);
  const dailyTrackMatch = currentPath.match(/^\/daily-tracks\/(track_[a-f0-9]+)$/);
  return (
    <AppShell currentPath={currentPath} isOperator={isOperator}>
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
        {currentPath === "/operator/researchers" && isOperator ? (
          <OperatorResearchersPage operatorResearcherId={researcherId} />
        ) : null}
        {currentPath === "/operator/data" && isOperator ? <OperatorDataPage /> : null}
        {(currentPath === "/operator/researchers" || currentPath === "/operator/data")
        && !isOperator ? (
          <section aria-label="Not found" className="page-section state-section">
            <h1>Not found</h1>
            <p>The requested resource is not available.</p>
          </section>
        ) : null}
        {currentPath !== "/data" &&
        currentPath !== "/research" &&
        currentPath !== "/operator/researchers" &&
        currentPath !== "/operator/data" &&
        !currentPath.startsWith("/research-runs") &&
        !currentPath.startsWith("/daily-tracks") ? (
          <div aria-label="Resource outlet" />
        ) : null}
      </Suspense>
    </AppShell>
  );
}
