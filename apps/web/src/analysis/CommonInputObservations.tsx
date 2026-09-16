import { useEffect, useState } from "react";
import { coreFetch } from "../auth/coreFetch";
import "./strategy-events.css";
import "./common-input-observations.css";

type Observation = {
  session: string;
  identifier: string;
  industry_code: string | null;
  value: number | null;
  member_count: number;
  valid_count: number;
  exclusions: Record<string, number>;
};
type Page = { items: Observation[]; next_cursor: string | null };
const reasons: Record<string, string> = {
  insufficient_history: "No previous observation",
  invalid_current_close: "Invalid current Close",
  invalid_previous_close: "Invalid previous Close",
  non_finite_return: "Non-finite return",
};

export function CommonInputObservations({ endpoint }: { endpoint: string }) {
  const [open, setOpen] = useState(false);
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const cursor = cursors[cursors.length - 1];
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setPage(null);
    setError(null);
    const query = new URLSearchParams({ limit: "20" });
    if (cursor) query.set("cursor", cursor);
    void coreFetch(`${endpoint}?${query}`, { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error(response.status === 400
        ? "This result changed. Restart from the first page."
        : "Common market inputs could not be loaded.");
      const result = await response.json() as Page;
      if (!controller.signal.aborted) setPage(result);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Unable to load inputs.");
    });
    return () => controller.abort();
  }, [open, endpoint, cursor, retry]);
  return <details className="common-input-observations" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Common market inputs</summary>
    {open && <div className="common-input-content">
      <p>Historical members of this research Universe. Industry values describe its SW2021 L1 subset, not an official industry index. Selecting an industry here does not change the stock Universe.</p>
      <p>Returns use adjusted Close. Advancing fraction includes zero-return members in its denominator; missing values mean no valid sample.</p>
      {error ? <div role="alert"><p>{error}</p><button type="button" onClick={() => {
        setCursors([null]); setRetry(value => value + 1);
      }}>Reload first page</button></div> : page === null ? <p role="status">Loading common inputs…</p>
        : page.items.length === 0 ? <p>This research does not use common market inputs.</p>
        : <div className="common-input-table"><table>
          <thead><tr><th>Date</th><th>Metric</th><th>Scope</th><th>Value</th><th>Valid / members</th><th>Excluded</th></tr></thead>
          <tbody>{page.items.map(item => <tr key={`${item.session}:${item.identifier}:${item.industry_code ?? ""}`}>
            <td>{item.session}</td><td>{item.identifier.endsWith("advancing_fraction") ? "Advancing fraction" : "Equal-weight return"}</td>
            <td>{item.industry_code ? `Universe · SW2021 L1 ${item.industry_code}` : "Research Universe"}</td>
            <td>{item.value === null ? "—" : `${(item.value * 100).toFixed(2)}%`}</td>
            <td>{item.valid_count} / {item.member_count}</td>
            <td>{Object.entries(item.exclusions).map(([reason, count]) => `${reasons[reason] ?? reason}: ${count}`).join("; ") || "None"}</td>
          </tr>)}</tbody>
        </table></div>}
      <nav aria-label="Common input pages">
        <button type="button" disabled={cursors.length === 1 || page === null} onClick={() => setCursors(values => values.slice(0, -1))}>Previous</button>
        <span>Page {cursors.length}</span>
        <button type="button" disabled={!page?.next_cursor} onClick={() => {
          if (page?.next_cursor) setCursors(values => [...values, page.next_cursor]);
        }}>Next</button>
      </nav>
    </div>}
  </details>;
}
