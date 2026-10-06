import { queryOptions } from "@tanstack/react-query";
import { coreFetch } from "../auth/coreFetch";
import type { DailyTrackDetail, DailyTrackList } from "./DailyTracksPage";

export const dailyTrackKeys = {
  all: ["workspace", "daily-tracks"] as const,
  list: ["workspace", "daily-tracks", "list"] as const,
  detail: (id: string | undefined) => ["workspace", "daily-tracks", "detail", id] as const,
  comparison: (ids: readonly string[]) => ["workspace", "daily-tracks", "comparison", ids] as const,
};

export class DailyTrackReadError extends Error {
  constructor(readonly status: number) { super("DailyTrack unavailable"); }
}

export async function readDailyTrackList(signal: AbortSignal): Promise<DailyTrackList> {
  const response = await coreFetch("/api/daily-tracks", { signal });
  if (!response.ok) throw new DailyTrackReadError(response.status);
  return await response.json() as DailyTrackList;
}

export function dailyTrackDetailOptions(id: string | undefined) {
  return queryOptions({
    queryKey: dailyTrackKeys.detail(id),
    queryFn: async ({ signal }): Promise<DailyTrackDetail> => {
      const response = await coreFetch(`/api/daily-tracks/${encodeURIComponent(id!)}`, { signal });
      if (!response.ok) throw new DailyTrackReadError(response.status);
      return await response.json() as DailyTrackDetail;
    },
    enabled: !!id,
    staleTime: 0,
  });
}
