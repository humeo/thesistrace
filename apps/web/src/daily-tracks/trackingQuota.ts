import { coreFetch } from "../auth/coreFetch";
export type ChooseTracks = (
  limit: number,
  targetId: string | undefined,
) => Promise<string[] | null>;
export class TrackingSelectionCancelled extends Error {}
export class TrackingQuotaError extends Error {
  constructor(readonly selected: string[]) {
    super("TRACK_NOT_SELECTED");
  }
}
export async function submitTrackingAction(
  id: string,
  kind: "refresh" | "retry",
  signal: AbortSignal,
  choose: ChooseTracks,
  selected?: string[],
  bulk = false,
) {
  const request_id = `${kind}_${crypto.randomUUID()}`;
  const send = (selection?: string[]) =>
    coreFetch(`/api/daily-tracks/${encodeURIComponent(id)}/${kind}`, {
      method: "POST",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        request_id,
        ...(selection ? { selected_track_ids: selection } : {}),
      }),
    });
  let response = await send(selected);
  if (response.status !== 409) return response;
  const body = (await response
    .clone()
    .json()
    .catch(() => null)) as {
    detail?: { code?: string; limit?: number; selected_track_ids?: string[] };
  } | null;
  if (
    body?.detail?.code === "TRACK_SELECTION_REQUIRED" &&
    Number.isSafeInteger(body.detail.limit)
  ) {
    const selection = await choose(body.detail.limit!, bulk ? undefined : id);
    signal.throwIfAborted();
    if (selection === null) throw new TrackingSelectionCancelled();
    if (selection.includes(id)) response = await send(selection);
  } else if (body?.detail?.code?.startsWith("TRACK_") && !bulk)
    throw new TrackingQuotaError(body.detail.selected_track_ids ?? []);
  return response;
}
