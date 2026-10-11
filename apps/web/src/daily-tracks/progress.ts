import type { DailyTrackDetail } from "./DailyTracksPage";

export function dailyTrackNeedsPolling(track: Pick<DailyTrackDetail, "status"> & {
  progress: Pick<DailyTrackDetail["progress"], "phase">;
}): boolean {
  return track.status === "stopping" || [
    "queued", "retry_wait", "starting", "calculating", "result_ready", "staging",
  ].includes(track.progress.phase);
}

export function dailyTrackCanRefresh(track: Pick<DailyTrackDetail, "status" | "lag_sessions" | "progress">): boolean {
  return track.status === "active" && track.lag_sessions > 0 && track.progress.phase === "waiting";
}
