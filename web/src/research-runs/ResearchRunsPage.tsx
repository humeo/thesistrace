import { useEffect, useState } from "react";

type ResearchRun = {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  definition_id: string;
  definition_revision: number;
  dataset_release_id: string;
};

type ResearchRunList = { items: ResearchRun[]; next_cursor: string | null };

export function ResearchRunsPage({ runId }: { runId?: string }) {
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [items, setItems] = useState<ResearchRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    const path = runId ? `/api/research-runs/${runId}` : "/api/research-runs";
    void fetch(path, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("ResearchRun unavailable");
        if (runId) setRun(await response.json() as ResearchRun);
        else setItems((await response.json() as ResearchRunList).items);
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError("ResearchRun unavailable");
      });
    return () => controller.abort();
  }, [runId]);

  if (error) return <section aria-label="Research Runs"><p role="alert">{error}</p></section>;
  if (runId && run === null) {
    return <section aria-label="Research Runs"><p>Loading ResearchRun…</p></section>;
  }
  if (!runId && items === null) {
    return <section aria-label="Research Runs"><p>Loading Research Runs…</p></section>;
  }
  if (run) {
    return (
      <section aria-label="Research Runs">
        <h1>ResearchRun</h1>
        <p><strong>Status</strong> {run.status}</p>
        <p>
          <strong>Definition</strong>{" "}
          <a href={`/definitions/${run.definition_id}`}>
            Revision {run.definition_revision}
          </a>
        </p>
        <p><strong>Dataset Release</strong> {run.dataset_release_id}</p>
      </section>
    );
  }
  return (
    <section aria-label="Research Runs">
      <h1>Research Runs</h1>
      {items?.length === 0 ? <p>No Research Runs yet.</p> : null}
      <ol aria-label="Research Runs">
        {items?.map((item) => (
          <li key={item.id}>
            <a href={`/research-runs/${item.id}`}>{item.id}</a>
            <span> · {item.status}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
