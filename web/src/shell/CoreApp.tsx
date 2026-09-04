import { lazy, Suspense, useEffect, useMemo } from "react";

import type { BrowserLocation } from "../auth/routing";
import { readBrowserChatThread } from "../chat/chatNavigation";
import { useSessionHistory } from "../chat/useSessionHistory";
import type { WorkspaceNavigate } from "./navigation";

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

export function CoreApp({ location, navigate, isOperator, researcherId }: {
  location: BrowserLocation;
  navigate: WorkspaceNavigate;
  isOperator: boolean;
  researcherId: string;
}) {
  const currentPath = location.pathname;
  const sessionHistory = useSessionHistory(researcherId);
  const thread = useMemo(() => currentPath === "/chat"
    ? readBrowserChatThread(location.search) : null, [currentPath, location]);
  useEffect(() => { window.scrollTo(0, 0); }, [currentPath]);
  const researchRunMatch = currentPath.match(/^\/research-runs\/(run_[a-f0-9]+)$/);
  const dailyTrackMatch = currentPath.match(/^\/daily-tracks\/(track_[a-f0-9]+)$/);
  return (
    <AppShell
      currentPath={currentPath}
      currentSessionId={thread?.kind === "session" ? thread.id : null}
      isNewChat={thread?.kind === "new"}
      isOperator={isOperator}
      navigate={navigate}
      sessionHistory={sessionHistory}
    >
      <Suspense
        fallback={currentPath === "/chat"
          ? <main aria-busy="true" aria-label="Loading Chat" className="chat-main" />
          : <section className="state-section"><p>Loading workspace…</p></section>}
      >
        {thread === null ? null : <ChatPage key={thread.id ?? "invalid"} researcherId={researcherId} thread={thread} />}
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
        {currentPath !== "/chat" && currentPath !== "/data" &&
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
