import { DataPage } from "../data/DataPage";
import { DailyTracksPage } from "../daily-tracks/DailyTracksPage";
import { DefinitionsPage } from "../definitions/DefinitionsPage";
import { ResearchRunsPage } from "../research-runs/ResearchRunsPage";
import { AppShell } from "./AppShell";

export function CoreApp({ currentPath }: { currentPath: string }) {
  const definitionMatch = currentPath.match(/^\/definitions\/(def_[a-f0-9]+)$/);
  const researchRunMatch = currentPath.match(/^\/research-runs\/(run_[a-f0-9]+)$/);
  const dailyTrackMatch = currentPath.match(/^\/daily-tracks\/(track_[a-f0-9]+)$/);
  return (
    <AppShell currentPath={currentPath}>
      {currentPath === "/data" ? <DataPage /> : null}
      {currentPath === "/definitions" || definitionMatch ? (
        <DefinitionsPage definitionId={definitionMatch?.[1]} />
      ) : null}
      {currentPath === "/research-runs" || researchRunMatch ? (
        <ResearchRunsPage runId={researchRunMatch?.[1]} />
      ) : null}
      {currentPath === "/daily-tracks" || dailyTrackMatch ? (
        <DailyTracksPage trackId={dailyTrackMatch?.[1]} />
      ) : null}
      {currentPath !== "/data" &&
      !currentPath.startsWith("/definitions") &&
      !currentPath.startsWith("/research-runs") &&
      !currentPath.startsWith("/daily-tracks") ? (
        <div aria-label="Resource outlet" />
      ) : null}
    </AppShell>
  );
}
