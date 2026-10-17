import {submitTrackingAction,TrackingSelectionCancelled,type ChooseTracks} from "./trackingQuota";
import { CoreAuthenticationRequiredError, coreFetch } from "../auth/coreFetch";
import type { DailyTrackDetail, DailyTrackListItem } from "./DailyTracksPage";
import { dailyTrackCanRefresh } from "./progress";
import { readDailyTrackList } from "./queries";

export type BulkRefreshItem = {
  id: string;
  name: string | null;
  outcome: "queued" | "up_to_date" | "busy" | "blocked" | "stopped" | "changed" | "quota_limited" | "failed";
};

/** Submit existing Refresh commands; accepted work belongs to the Tracking Worker. */
export async function refreshAllDailyTracks(signal: AbortSignal, chooseTracks:ChooseTracks): Promise<BulkRefreshItem[]> {
  const tracks = new Map<string, DailyTrackListItem>();
  let cursor: string | undefined;
  do {
    const page = await readDailyTrackList(signal, cursor);
    for (const track of page.items) tracks.set(track.id, track);
    cursor = page.next_cursor ?? undefined;
  } while (cursor);

  const results: BulkRefreshItem[] = [];
  let selection:string[]|undefined;
  for (const track of tracks.values()) {
    signal.throwIfAborted();
    const item = { id: track.id, name: track.seed_name };
    if(selection&&!selection.includes(track.id)){results.push({...item,outcome:"quota_limited"});continue;}
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
      const queued=await submitTrackingAction(track.id,"refresh",signal,async(limit,target)=>{const chosen=await chooseTracks(limit,target);selection=chosen??undefined;return chosen;},selection,true);

      const reason=queued.status===409?await queued.clone().json().catch(()=>null):null;
      results.push({ ...item, outcome: queued.ok ? "queued" : reason?.detail?.code?.startsWith("TRACK_")?"quota_limited":queued.status === 409 ? "changed" : "failed" });
    } catch (error) {
      signal.throwIfAborted();
      if (error instanceof CoreAuthenticationRequiredError || error instanceof TrackingSelectionCancelled) throw error;
      results.push({ ...item, outcome: "failed" });
    }
  }
  return results;
}
