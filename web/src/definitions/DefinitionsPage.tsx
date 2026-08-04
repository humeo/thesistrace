import { useCallback, useEffect, useState } from "react";

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
  const [items, setItems] = useState<DefinitionSummary[] | null>(null);
  const [definition, setDefinition] = useState<DefinitionDetail | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [hypothesis, setHypothesis] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    if (definitionId) {
      const response = await fetch(`/api/definitions/${definitionId}`);
      if (!response.ok) throw new Error("Research Definition unavailable");
      const loaded = (await response.json()) as DefinitionDetail;
      setDefinition(loaded);
      setName(loaded.name);
      setHypothesis(loaded.hypothesis ?? "");
      setCreating(false);
      return;
    }
    const response = await fetch("/api/definitions");
    if (!response.ok) throw new Error("Research Definitions unavailable");
    setItems(((await response.json()) as DefinitionList).items);
  }, [definitionId]);

  useEffect(() => {
    void load().catch((reason: Error) => setError(reason.message));
  }, [load]);

  function startNew() {
    setCreating(true);
    setDefinition(null);
    setName("");
    setHypothesis("");
    setStatus(null);
    setError(null);
  }

  async function save() {
    setError(null);
    setStatus("Saving…");
    const body: Record<string, unknown> = {};
    if (name.trim()) body.name = name;
    if (hypothesis.trim()) body.hypothesis = hypothesis;
    if (definition) body.expected_revision = definition.revision;
    const response = await fetch(
      definition ? `/api/definitions/${definition.id}` : "/api/definitions",
      {
        method: definition ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
    if (!response.ok) {
      setStatus(null);
      setError("Research Definition was not saved");
      return;
    }
    const saved = (await response.json()) as DefinitionDetail;
    setDefinition(saved);
    setCreating(false);
    setName(saved.name);
    setHypothesis(saved.hypothesis ?? "");
    setStatus(`Saved revision ${saved.revision}.`);
    window.history.replaceState({}, "", `/definitions/${saved.id}`);
  }

  if (error) {
    return (
      <section aria-label="Definitions">
        <p role="alert">{error}</p>
        <button onClick={() => void load()}>Retry</button>
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
          <button onClick={startNew}>New Definition</button>
          <button onClick={() => void load()}>Refresh</button>
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
          <button type="submit">Save</button>
          <button type="button" onClick={() => void load()}>Refresh</button>
          {status && <p role="status">{status}</p>}
        </form>
      )}
    </section>
  );
}
