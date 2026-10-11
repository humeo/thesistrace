import { CoreAuthenticationRequiredError, coreFetch } from "../auth/coreFetch";
import type { DailyTrackDetail, DailyTrackListItem } from "./DailyTracksPage";
import { dailyTrackCanRefresh } from "./progress";
import { readDailyTrackList } from "./queries";

export type BulkRefreshItem = {
  id: string;
  name: string | null;
  outcome: "queued" | "up_to_date" | "busy" | "blocked" | "stopped" | "changed" | "failed";
};

/** Submit existing Refresh commands; accepted work belongs to the Tracking Worker. */
export async function refreshAllDailyTracks(signal: AbortSignal): Promise<BulkRefreshItem[]> {
  const tracks = new Map<string, DailyTrackListItem>();
  let cursor: string | undefined;
  do {
    const page = await readDailyTrackList(signal, cursor);
    for (const track of page.items) tracks.set(track.id, track);
    cursor = page.next_cursor ?? undefined;
  } while (cursor);

  const results: BulkRefreshItem[] = [];
  for (const track of tracks.values()) {
    signal.throwIfAborted();
    const item = { id: track.id, name: track.seed_name };
    if (track.status !== "active") {
      results.push({ ...item, outcome: track.status === "stopping" ? "busy" : track.status });
      continue;
    }
    try {
      const response = await coreFetch(`/api/daily-tracks/${encodeURIComponent(track.id)}`, { signal });
      if (!response.ok) throw new Error("Track status unavailable");
      const detail = await response.json() as DailyTrackDetail;
      if (!dailyTrackCanRefresh(detail)) {
        const outcome = detail.status === "blocked" ? "blocked" : detail.status === "stopped" ? "stopped"
          : detail.status === "stopping" || detail.progress.phase !== "up_to_date" && detail.progress.phase !== "waiting"
            ? "busy" : "up_to_date";
        results.push({ ...item, outcome });
        continue;
      }
      const queued = await coreFetch(`/api/daily-tracks/${encodeURIComponent(track.id)}/refresh`, {
        method: "POST", signal, headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: `refresh_${crypto.randomUUID()}` }),
      });
      results.push({ ...item, outcome: queued.ok ? "queued" : queued.status === 409 ? "changed" : "failed" });
    } catch (error) {
      signal.throwIfAborted();
      if (error instanceof CoreAuthenticationRequiredError) throw error;
      results.push({ ...item, outcome: "failed" });
    }
  }
  return results;
}
