import { useEffect, useState } from "react";
import { coreFetch } from "../auth/coreFetch";
import "./strategy-events.css";

type Section = "strategy_targets" | "strategy_orders" | "strategy_child_orders" | "strategy_fills" | "strategy_adjustments";
type EventValue = string | number | null | string[] | Record<string, string | number>;
type EventRow = Record<string, EventValue>;
type Page = { section: Section; status: "recorded" | "not_recorded"; rows: EventRow[]; next_cursor: string | null };
type Filter = { start_session?: string; end_session?: string; instrument_id?: string; target_id?: string; order_id?: string; child_order_id?: string };
const sections: Record<Section, string> = {
  strategy_targets: "Targets", strategy_orders: "Simulated orders", strategy_child_orders: "Child orders",
  strategy_fills: "Simulated fills", strategy_adjustments: "Valuation adjustments",
};
const idFields: Record<Section, string> = {
  strategy_targets: "target_id", strategy_orders: "order_id", strategy_child_orders: "child_order_id",
  strategy_fills: "fill_id", strategy_adjustments: "adjustment_id",
};
const fieldLabels: Record<string, string> = {
  raw_open: "Raw Open (CNY)", adjusted_open: "Adjusted Open (CNY)", raw_notional: "Raw notional (CNY)",
  research_settlement: "Research Settlement (CNY)", cost: "Fees (CNY)", net_cash_delta: "Net cash change (CNY)",
  gross_cash_delta: "Gross cash change (CNY)", cash_rounding_delta: "Cash rounding (CNY)",
  adjusted_units_delta: "Adjusted holding units change", execution_shares_delta: "Execution shares change",
};
function label(key: string) { return fieldLabels[key] ?? key.replaceAll("_", " ").replace(/^./, value => value.toUpperCase()); }
function display(value: EventValue | undefined): string {
  if (value == null) return "—";
  if (Array.isArray(value)) return value.join(", ") || "None";
  if (typeof value === "object") return Object.entries(value).map(([key, item]) => `${key}: ${item}`).join("; ") || "None";
  return String(value);
}

export function StrategyEvents({ endpoint }: { endpoint: string }) {
  const [open, setOpen] = useState(false);
  const [section, setSection] = useState<Section>("strategy_targets");
  const [filters, setFilters] = useState<Filter>({});
  const [draft, setDraft] = useState({ start_session: "", end_session: "", instrument_id: "" });
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const cursor = cursors[cursors.length - 1];
  function navigate(next: Section, relation: Filter = {}) {
    setPage(null); setSection(next); setFilters(relation); setCursors([null]);
    setDraft({ start_session: "", end_session: "", instrument_id: "" });
  }
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setPage(null); setError(null);
    void coreFetch(endpoint, {
      method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
      body: JSON.stringify({ section, ...filters, cursor, limit: 20 }),
    }).then(async response => {
      if (!response.ok) throw new Error(response.status === 400
        ? "This page cannot be continued. Reload the first page."
        : "Trading events could not be loaded.");
      const result = await response.json() as Page;
      if (!controller.signal.aborted) setPage(result);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Unable to load events.");
    });
    return () => controller.abort();
  }, [open, endpoint, section, filters, cursor, revision]);
  return <details className="strategy-events" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Trading events</summary>
    {open && <div className="strategy-events-content">
      <p>Follow a target through simulated orders and fills. Research Settlement and cash changes reconcile the research account; raw notional is the execution-price amount. Valuation adjustments are listed separately.</p>
      <form className="strategy-event-filters" onSubmit={event => {
        event.preventDefault(); setPage(null); setCursors([null]);
        setFilters({ ...filters, start_session: draft.start_session || undefined, end_session: draft.end_session || undefined, instrument_id: draft.instrument_id.trim() || undefined });
      }}>
        <label>Event type<select value={section} onChange={event => navigate(event.target.value as Section)}>
          {Object.entries(sections).map(([value, title]) => <option key={value} value={value}>{title}</option>)}
        </select></label>
        <label>From<input type="date" value={draft.start_session} max={draft.end_session || undefined} onChange={event => setDraft({ ...draft, start_session: event.target.value })} /></label>
        <label>Through<input type="date" value={draft.end_session} min={draft.start_session || undefined} onChange={event => setDraft({ ...draft, end_session: event.target.value })} /></label>
        <label>Instrument ID<input value={draft.instrument_id} onChange={event => setDraft({ ...draft, instrument_id: event.target.value })} /></label>
        <button type="submit">Apply filters</button>
        <button type="button" onClick={() => navigate(section)}>Clear filters</button>
      </form>
      <p>Dates refer to the decision for targets and the execution or adjustment for other events.</p>
      {(filters.target_id || filters.order_id || filters.child_order_id) && <p className="strategy-event-relation">Related to {filters.child_order_id ? "child order" : filters.order_id ? "order" : "target"}: <code>{filters.child_order_id ?? filters.order_id ?? filters.target_id}</code></p>}
      {error ? <p role="alert">{error}</p> : page === null ? <p role="status">Loading trading events…</p>
        : page.status === "not_recorded" ? <p>Trading events were not recorded for this result.</p>
        : page.rows.length === 0 ? <p>No {sections[section].toLowerCase()} match these filters.</p>
        : <ol className="strategy-event-list">{page.rows.map(row => <li key={String(row[idFields[section]])}>
          <details>
            <summary><time>{display(row.session ?? row.decision_session)}</time><span>{display(row.instrument_id ?? row.mode ?? row.type)}</span><span>{display(row.side ?? row.reason)}</span><span>{row.exposure === undefined ? display(row.quantity ?? row.legal_quantity) : `${Number(row.exposure) * 100}% exposure`}</span></summary>
            <dl>{Object.entries(row).map(([key, value]) => <div key={key}><dt>{label(key)}</dt><dd>{display(value)}</dd></div>)}</dl>
          </details>
          <div className="strategy-event-links">
            {section === "strategy_targets" && <button type="button" onClick={() => navigate("strategy_orders", { target_id: String(row.target_id) })}>View orders</button>}
            {section === "strategy_orders" && <button type="button" onClick={() => navigate("strategy_child_orders", { order_id: String(row.order_id) })}>View child orders</button>}
            {(section === "strategy_targets" || section === "strategy_orders" || section === "strategy_child_orders") && <button type="button" onClick={() => navigate("strategy_fills", section === "strategy_child_orders" ? { child_order_id: String(row.child_order_id) } : section === "strategy_orders" ? { order_id: String(row.order_id) } : { target_id: String(row.target_id) })}>View fills</button>}
          </div>
        </li>)}</ol>}
      <nav aria-label="Trading event pages">
        <button type="button" onClick={() => { setCursors([null]); setRevision(value => value + 1); }}>Reload first page</button>
        <button type="button" disabled={cursors.length === 1 || !page} onClick={() => { setPage(null); setCursors(values => values.slice(0, -1)); }}>Previous</button>
        <span>Page {cursors.length}</span>
        <button type="button" disabled={!page?.next_cursor} onClick={() => { if (page?.next_cursor) { setCursors(values => [...values, page.next_cursor]); setPage(null); } }}>Next</button>
      </nav>
    </div>}
  </details>;
}
