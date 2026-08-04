import { useEffect, useRef, useState } from "react";

type DailyTrack = {
  id: string;
  status: "active";
  seed_run_id: string;
  seed_release_id: string;
  current_release_id: string;
  definition_id: string;
  definition_revision: number;
  result_checksum_sha256: string;
  strategy_session: string;
};

type DailyTrackList = { items: DailyTrack[]; next_cursor: string | null };

export function DailyTracksPage({ trackId }: { trackId?: string }) {
  const [track, setTrack] = useState<DailyTrack | null>(null);
  const [items, setItems] = useState<DailyTrack[] | null>(null);
  const [error, setError] = useState(false);
  const [refreshGeneration, setRefreshGeneration] = useState(0);
  const loadGeneration = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    const generation = ++loadGeneration.current;
    setError(false);
    const path = trackId ? `/api/daily-tracks/${trackId}` : "/api/daily-tracks";

    async function load() {
      try {
        const response = await fetch(path, { signal: controller.signal });
        if (!response.ok) throw new Error("DailyTrack unavailable");
        if (trackId) {
          const nextTrack = (await response.json()) as DailyTrack;
          if (generation !== loadGeneration.current) return;
          setTrack(nextTrack);
        } else {
          const nextItems = ((await response.json()) as DailyTrackList).items;
          if (generation !== loadGeneration.current) return;
          setItems(nextItems);
        }
      } catch (reason: unknown) {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        if (generation === loadGeneration.current) setError(true);
      }
    }

    void load();
    return () => {
      if (generation === loadGeneration.current) loadGeneration.current += 1;
      controller.abort();
    };
  }, [refreshGeneration, trackId]);

  if (error) {
    return (
      <section aria-label="Daily Tracks">
        <h1>DailyTrack</h1>
        <p role="alert">DailyTrack unavailable</p>
        <button onClick={() => setRefreshGeneration((value) => value + 1)}>Retry</button>
      </section>
    );
  }
  if (trackId && track === null) {
    return <section aria-label="Daily Tracks"><p>Loading DailyTrack…</p></section>;
  }
  if (!trackId && items === null) {
    return <section aria-label="Daily Tracks"><p>Loading DailyTracks…</p></section>;
  }
  if (track) {
    return (
      <section aria-label="Daily Tracks">
        <h1>DailyTrack</h1>
        <div className="research-run-facts">
          <p><strong>Status</strong> {track.status}</p>
          <p>
            <strong>Seed ResearchRun</strong>{" "}
            <a href={`/research-runs/${track.seed_run_id}`}>{track.seed_run_id}</a>
          </p>
          <p><strong>Seed Dataset Release</strong> {track.seed_release_id}</p>
          <p><strong>Current Dataset Release</strong> {track.current_release_id}</p>
          <p>
            <strong>Definition</strong>{" "}
            <a href={`/definitions/${track.definition_id}`}>
              Revision {track.definition_revision}
            </a>
          </p>
          <p><strong>Strategy session</strong> {track.strategy_session}</p>
          <p><strong>Result checksum</strong> {track.result_checksum_sha256}</p>
        </div>
      </section>
    );
  }
  return (
    <section aria-label="Daily Tracks">
      <h1>Daily Tracks</h1>
      {items?.length === 0 ? <p>No DailyTracks yet.</p> : null}
      <ol aria-label="Daily Tracks">
        {items?.map((item) => (
          <li key={item.id}>
            <a href={`/daily-tracks/${item.id}`}>{item.id}</a>
            <span> · {item.status}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
