import { useEffect, useId, useState } from "react";
import { coreFetch } from "../auth/coreFetch";
import "./factor-evidence.css";

type Groups = Record<"q1" | "q2" | "q3" | "q4" | "q5", number | null>;
type Coverage = {
  alpha_candidate_count: number; alpha_sample_count: number; sample_count: number;
  alpha_exclusions: Record<string, number>; label_exclusions: Record<string, number>;
};
type Daily = Coverage & {
  session: string; label_entry_session: string | null; label_exit_session: string | null;
  label_status: string; ic: number | null; rank_ic: number | null;
  quantile_returns: Groups; quantile_counts: Groups; top_bottom_return: number | null;
  correlation_reason: string | null; quantile_reason: string | null;
};
type Period = {
  period: string;
  summary: { ic: { mean: number | null; icir: number | null };
    rank_ic: { mean: number | null; icir: number | null }; quantile_returns: Groups; top_bottom_return: number | null };
  coverage: Coverage & { signal_session_count: number; ic_valid_session_count: number;
    rank_ic_valid_session_count: number; first_signal_session: string; last_signal_session: string;
    first_evaluable_signal_session: string | null; last_evaluable_signal_session: string | null;
    label_evaluable_session_count: number; right_censored_session_count: number };
};
type Page = { section: "factor_observations"; items: Daily[]; next_cursor: string | null }
  | { section: "factor_periods"; items: Period[]; next_cursor: string | null };
type Filters = { horizon: string; view: "daily" | "month" | "year" | "all"; start: string; end: string };
const groups = ["q1", "q2", "q3", "q4", "q5"] as const;
const reasonLabels: Record<string, string> = {
  missing_expression: "Missing signal", missing_industry: "Missing industry",
  industry_group_too_small: "Industry group too small", sample_insufficient: "Fewer than 30 valid samples",
  constant_array: "Constant signal or returns", data_unavailable: "Data unavailable",
  confirmed_market_open_unavailable: "Open unavailable",
  right_censored_by_research_period_end: "Label extends beyond research end",
};
const number = (value: number | null) => value === null ? "—" : value.toFixed(3);
const percent = (value: number | null) => value === null ? "—" : `${(value * 100).toFixed(2)}%`;
function Exclusions({ values }: { values: Record<string, number> }) {
  return <>{Object.entries(values).map(([reason, count]) =>
    <span className="factor-exclusion" key={reason}>{reasonLabels[reason] ?? reason}: {count}</span>)}</>;
}
function SampleCoverage({ value }: { value: Coverage }) {
  return <><p>Candidates {value.alpha_candidate_count} · Final signals {value.alpha_sample_count} · Valid labels {value.sample_count}</p>
    <Exclusions values={value.alpha_exclusions} /><Exclusions values={value.label_exclusions} /></>;
}

export function FactorEvidence({ runId }: { runId: string }) {
  const [open, setOpen] = useState(false);
  const [filters, setFilters] = useState<Filters>({ horizon: "5", view: "month", start: "", end: "" });
  const id = useId();
  return <details className="factor-evidence" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Factor evidence</summary>
    {open && <div className="factor-evidence-content">
      <p>IC and Rank IC describe signal predictiveness. Group and Q5 − Q1 returns are forward Open labels before costs, not executable strategy returns. — means unavailable; zero is an observed value.</p>
      <div className="factor-evidence-controls">
        <label htmlFor={`${id}-horizon`}>Horizon<select id={`${id}-horizon`} value={filters.horizon}
          onChange={event => setFilters({ ...filters, horizon: event.target.value })}>
          {[1, 5, 20].map(h => <option value={h} key={h}>{h} sessions</option>)}
        </select></label>
        <label htmlFor={`${id}-view`}>View<select id={`${id}-view`} value={filters.view}
          onChange={event => setFilters({ ...filters, view: event.target.value as Filters["view"] })}>
          <option value="daily">Daily</option><option value="month">Monthly</option>
          <option value="year">Yearly</option><option value="all">Full period</option>
        </select></label>
        {filters.view === "daily" && <>
          <label htmlFor={`${id}-start`}>Signal from<input id={`${id}-start`} type="date" value={filters.start}
            onChange={event => setFilters({ ...filters, start: event.target.value })} /></label>
          <label htmlFor={`${id}-end`}>Signal through<input id={`${id}-end`} type="date" value={filters.end}
            onChange={event => setFilters({ ...filters, end: event.target.value })} /></label>
        </>}
      </div>
      {filters.view !== "daily" && <p>Grouped by signal date. Daily correlations have equal weight; labels crossing a month or year remain intact. ICIR uses the daily sample standard deviation.</p>}
      <EvidencePage key={`${runId}:${JSON.stringify(filters)}`} runId={runId} filters={filters} />
    </div>}
  </details>;
}

function EvidencePage({ runId, filters }: { runId: string; filters: Filters }) {
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const cursor = cursors[cursors.length - 1];
  const invalidRange = filters.view === "daily" && filters.start !== "" && filters.end !== "" && filters.start > filters.end;
  useEffect(() => {
    if (invalidRange) return;
    const controller = new AbortController();
    setPage(null); setError(null);
    const query = new URLSearchParams({ horizon: filters.horizon, limit: "20" });
    if (cursor) query.set("cursor", cursor);
    if (filters.view === "daily") {
      if (filters.start) query.set("start_session", filters.start);
      if (filters.end) query.set("end_session", filters.end);
    } else query.set("granularity", filters.view);
    const endpoint = filters.view === "daily" ? "factor-observations" : "factor-periods";
    void coreFetch(`/api/research-runs/${encodeURIComponent(runId)}/${endpoint}?${query}`, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error(response.status === 400 ? "The page cursor is no longer valid. Reload the first page." : "Factor evidence could not be loaded.");
        const result = await response.json() as Page;
        if (!controller.signal.aborted) setPage(result);
      }).catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Unable to load evidence.");
      });
    return () => controller.abort();
  }, [runId, filters, cursor, retry, invalidRange]);
  if (invalidRange) return <p role="alert">Signal through must be on or after Signal from.</p>;
  return <>
    {error ? <div role="alert"><p>{error}</p><button type="button" onClick={() => { setCursors([null]); setRetry(value => value + 1); }}>Reload first page</button></div>
      : page === null ? <p role="status">Loading Factor evidence…</p>
      : page.items.length === 0 ? <p>No observations in this selection.</p>
      : <div className="factor-evidence-table"><table>
        <caption>{page.section === "factor_observations" ? "Daily signal evidence" : "Signal-date period statistics"}</caption>
        <thead><tr><th>{page.section === "factor_observations" ? "Signal date" : "Period"}</th><th>IC</th><th>Rank IC</th>
          {page.section === "factor_periods" && <><th>ICIR</th><th>Rank ICIR</th></>}
          {groups.map(group => <th key={group}>{group.toUpperCase()}</th>)}<th>Q5 − Q1</th><th>Evidence</th></tr></thead>
        <tbody>{page.section === "factor_observations" ? page.items.map(row => <tr key={row.session}>
          <td>{row.session}</td><td>{number(row.ic)}</td><td>{number(row.rank_ic)}</td>
          {groups.map(group => <td key={group}>{percent(row.quantile_returns[group])}<small>n={row.quantile_counts[group]}</small></td>)}
          <td>{percent(row.top_bottom_return)}</td><td><details><summary>Coverage and label</summary>
            <SampleCoverage value={row} />
            <p>Open {row.label_entry_session ?? "—"} → {row.label_exit_session ?? "—"}</p>
            {row.label_status === "right_censored_by_research_period_end" && <p>Label extends beyond research end</p>}
            {row.correlation_reason && <p>{reasonLabels[row.correlation_reason] ?? row.correlation_reason}</p>}
          </details></td></tr>) : page.items.map(row => <tr key={row.period}>
          <td>{row.period}</td><td>{number(row.summary.ic.mean)}</td><td>{number(row.summary.rank_ic.mean)}</td>
          <td>{number(row.summary.ic.icir)}</td><td>{number(row.summary.rank_ic.icir)}</td>
          {groups.map(group => <td key={group}>{percent(row.summary.quantile_returns[group])}</td>)}
          <td>{percent(row.summary.top_bottom_return)}</td><td><details><summary>{row.coverage.label_evaluable_session_count} / {row.coverage.signal_session_count} sessions</summary>
            <p>Signals {row.coverage.first_signal_session} → {row.coverage.last_signal_session}</p>
            <p>Evaluable signals {row.coverage.first_evaluable_signal_session ?? "—"} → {row.coverage.last_evaluable_signal_session ?? "—"}</p>
            <p>Valid IC days {row.coverage.ic_valid_session_count} · Valid Rank IC days {row.coverage.rank_ic_valid_session_count} · Tail not evaluated {row.coverage.right_censored_session_count}</p>
            <SampleCoverage value={row.coverage} />
          </details></td></tr>)}</tbody>
      </table></div>}
    <nav aria-label="Factor evidence pages"><button type="button" disabled={cursors.length === 1 || page === null || error !== null}
      onClick={() => setCursors(values => values.slice(0, -1))}>Previous</button>
      <span>Page {cursors.length}</span><button type="button" disabled={!page?.next_cursor || error !== null}
        onClick={() => { if (page?.next_cursor) setCursors(values => [...values, page.next_cursor]); }}>Next</button></nav>
  </>;
}
