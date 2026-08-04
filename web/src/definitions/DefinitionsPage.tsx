import { useCallback, useEffect, useRef, useState } from "react";

type DefinitionSummary = { id: string; name: string; revision: number };
type DefinitionList = { items: DefinitionSummary[]; next_cursor: string | null };
type DefinitionDetail = DefinitionSummary & {
  hypothesis: string | null;
  alpha: Record<string, unknown> | null;
  universe: "top300" | "top1000" | "top2000" | "top3000" | null;
  neutralization: "none" | "industry" | null;
  holdings_count: number | null;
  rebalance_every_sessions: number | null;
};

export function DefinitionsPage({ definitionId }: { definitionId?: string }) {
  const [activeDefinitionId, setActiveDefinitionId] = useState(definitionId);
  const [items, setItems] = useState<DefinitionSummary[] | null>(null);
  const [definition, setDefinition] = useState<DefinitionDetail | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [hypothesis, setHypothesis] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"loading" | "refreshing" | "saving" | null>(
    "loading",
  );
  const busyRef = useRef(false);
  const loadController = useRef<AbortController | null>(null);
  const loadGeneration = useRef(0);
  const skipNextRouteLoad = useRef(false);

  const load = useCallback(async (
    kind: "loading" | "refreshing" = "loading",
    supersede = false,
  ) => {
    if (busyRef.current && !supersede) return;
    loadController.current?.abort();
    const controller = new AbortController();
    loadController.current = controller;
    const generation = ++loadGeneration.current;
    busyRef.current = true;
    setBusy(kind);
    setError(null);
    setStatus(null);
    try {
      if (activeDefinitionId) {
        const response = await fetch(`/api/definitions/${activeDefinitionId}`, {
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("Research Definition unavailable");
        const loaded = (await response.json()) as DefinitionDetail;
        if (generation !== loadGeneration.current) return;
        setDefinition(loaded);
        setName(loaded.name);
        setHypothesis(loaded.hypothesis ?? "");
        setCreating(false);
      } else {
        const response = await fetch("/api/definitions", { signal: controller.signal });
        if (!response.ok) throw new Error("Research Definitions unavailable");
        const loaded = (await response.json()) as DefinitionList;
        if (generation !== loadGeneration.current) return;
        setItems(loaded.items);
      }
      if (kind === "refreshing") setStatus("Refreshed.");
    } catch (reason: unknown) {
      if (
        generation !== loadGeneration.current ||
        (reason instanceof DOMException && reason.name === "AbortError")
      ) return;
      setStatus(null);
      setError(
        activeDefinitionId
          ? "Research Definition unavailable"
          : "Research Definitions unavailable",
      );
    } finally {
      if (generation === loadGeneration.current) {
        busyRef.current = false;
        setBusy(null);
      }
    }
  }, [activeDefinitionId]);

  useEffect(() => {
    if (skipNextRouteLoad.current) {
      skipNextRouteLoad.current = false;
    } else {
      void load("loading", true);
    }
    return () => {
      loadGeneration.current += 1;
      loadController.current?.abort();
    };
  }, [load]);

  function startNew() {
    setCreating(true);
    setDefinition(null);
    setActiveDefinitionId(undefined);
    setName("");
    setHypothesis("");
    setStatus(null);
    setError(null);
  }

  async function save() {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy("saving");
    setError(null);
    setStatus("Saving…");
    const body: Record<string, unknown> = {};
    if (name.trim()) body.name = name;
    if (definition) body.hypothesis = hypothesis.trim() ? hypothesis : null;
    else if (hypothesis.trim()) body.hypothesis = hypothesis;
    if (definition) body.expected_revision = definition.revision;
    try {
      const response = await fetch(
        definition ? `/api/definitions/${definition.id}` : "/api/definitions",
        {
          method: definition ? "PUT" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      );
      if (!response.ok) throw new Error("Research Definition was not saved");
      const saved = (await response.json()) as DefinitionDetail;
      setDefinition(saved);
      setCreating(false);
      setName(saved.name);
      setHypothesis(saved.hypothesis ?? "");
      setStatus(`Saved revision ${saved.revision}.`);
      skipNextRouteLoad.current = true;
      setActiveDefinitionId(saved.id);
      window.history.replaceState({}, "", `/definitions/${saved.id}`);
    } catch (reason: unknown) {
      setStatus(null);
      setError(
        reason instanceof Error ? reason.message : "Research Definition was not saved",
      );
    } finally {
      busyRef.current = false;
      setBusy(null);
    }
  }

  if (error && !creating && definition === null && items === null) {
    return (
      <section aria-label="Definitions">
        <p role="alert">{error}</p>
        <button disabled={busy !== null} onClick={() => void load()}>Retry</button>
      </section>
    );
  }

  const editing = creating || definition !== null;
  if (!editing && items === null) {
    return <section aria-label="Definitions"><p>Loading Definitions…</p></section>;
  }

  return (
    <section aria-label="Definitions">
      <h1>Definitions</h1>
      {!editing ? (
        <>
          <button disabled={busy !== null} onClick={startNew}>New Definition</button>
          <button disabled={busy !== null} onClick={() => void load("refreshing")}>Refresh</button>
          {busy === "refreshing" && <p role="status">Refreshing…</p>}
          {status && busy === null && <p role="status">{status}</p>}
          {error && <><p role="alert">{error}</p><button disabled={busy !== null} onClick={() => void load()}>Retry</button></>}
          {items?.length === 0 && <p>No Research Definitions yet.</p>}
          <ol aria-label="Research Definitions">
            {items?.map((item) => (
              <li key={item.id}>
                <a href={`/definitions/${item.id}`}>{item.name}</a>
                <span> · Revision {item.revision}</span>
              </li>
            ))}
          </ol>
        </>
      ) : (
        <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
          <label>
            Definition name
            <input
              aria-label="Definition name"
              onChange={(event) => setName(event.target.value)}
              value={name}
            />
          </label>
          <label>
            Hypothesis (optional)
            <textarea
              aria-label="Hypothesis (optional)"
              onChange={(event) => setHypothesis(event.target.value)}
              value={hypothesis}
            />
          </label>
          {definition && <p>Revision {definition.revision}</p>}
          <button disabled={busy !== null} type="submit">Save</button>
          <button
            disabled={busy !== null}
            type="button"
            onClick={() => void load("refreshing")}
          >
            Refresh
          </button>
          {busy === "refreshing" && <p role="status">Refreshing…</p>}
          {error && <><p role="alert">{error}</p><button disabled={busy !== null} type="button" onClick={() => void load()}>Retry</button></>}
          {status && busy !== "refreshing" && <p role="status">{status}</p>}
        </form>
      )}
    </section>
  );
}
