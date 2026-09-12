import { useEffect, useRef, useState } from "react";
import { CurrentDataRerun, type RerunSource } from "./CurrentDataRerun";
import { coreFetch } from "../auth/coreFetch";
import "./strategy-events.css";
import "./daily-holdings.css";

type Unit = { unit_id: string; source_kind: string; first_session: string; last_session: string; expires_at: string; status: "available" | "expired" };
type StatusPage = { status: "recorded" | "not_recorded"; units: Unit[]; next_cursor: string | null };
type Row = { session: string; instrument_id: string; execution_shares: number; adjusted_units: string; adjusted_mark: string; market_value_cny: string; weight: number };
type Details = { status: "available" | "expired" | "not_recorded"; unit: Unit | null; rows: Row[]; coverage: { session_count: number } | null; next_cursor: string | null };
type Filters = { start_session?: string; end_session?: string; instrument_id?: string };

export function DailyHoldings({ endpoint, rerun }: {
  endpoint: string;
  rerun?: { folderId: string; source: RerunSource };
}) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<StatusPage | null>(null);
  const [unitId, setUnitId] = useState("");
  const [details, setDetails] = useState<Details | null>(null);
  const [draft, setDraft] = useState({ start_session: "", end_session: "", instrument_id: "" });
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [filters, setFilters] = useState<Filters>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  async function load(body: object, accept: (value: unknown) => void) {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError(null); setFieldErrors({});
    try {
      const response = await coreFetch(endpoint, {
        method: "POST", headers: { "Content-Type": "application/json" },
        signal: controller.signal, body: JSON.stringify(body),
      });
      if (response.status === 422) {
        const problem = await response.json() as { detail?: { loc?: string[]; msg?: string }[] };
        if (controller.signal.aborted) return;
        const errors: Record<string, string> = {};
        if (Array.isArray(problem.detail)) for (const item of problem.detail) {
          const field = item.loc?.at(-1);
          if (field && ["start_session", "end_session", "instrument_id"].includes(field)) {
            errors[field] = item.msg ?? "Invalid value.";
          }
        }
        if (Object.keys(errors).length) { setFieldErrors(errors); return; }
        throw new Error("The query is invalid. Check the date range and instrument.");
      }
      if (!response.ok) throw new Error(response.status === 400
        ? "This page cannot be continued. Load the first page again."
        : "Daily holdings could not be loaded.");
      const value: unknown = await response.json();
      if (!controller.signal.aborted) accept(value);
    } catch (cause) {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Request failed.");
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  function loadPeriods(cursor: string | null = null) {
    void load({ section: "daily_holdings_status", limit: 20, cursor }, value => {
      const page = value as StatusPage;
      setStatus(page); setUnitId(page.units[0]?.unit_id ?? ""); setDetails(null);
    });
  }
  function loadDetails(cursor: string | null, selectedFilters: Filters) {
    if (!unitId) return;
    void load({ section: "daily_holdings", unit_id: unitId, ...selectedFilters, limit: 20, cursor }, value => {
      setDetails(value as Details);
    });
  }
  const selectedUnit = details?.unit ?? status?.units.find(unit => unit.unit_id === unitId);
  return <section className="strategy-events daily-holdings">
    <button type="button" className="strategy-events-toggle" aria-expanded={open} onClick={() => {
      setOpen(!open);
      if (!open && !status) loadPeriods();
    }}>Daily holdings <span aria-hidden="true">{open ? "−" : "+"}</span></button>
    {open && <div className="daily-holdings-content">
      <p>Actual holdings after Open execution and fees. Successful detail reads retain that period for another 7 days. Checking availability does not extend retention.</p>
      <button type="button" disabled={busy} onClick={() => loadPeriods()}>Check availability</button>
      {status?.status === "not_recorded" && <p>Daily holdings were not recorded for this result.</p>}
      {status && status.units.length > 0 && <>
        <label>Recorded period<select value={unitId} disabled={busy} onChange={event => {
          setUnitId(event.target.value); setDetails(null);
        }}>{status.units.map(unit => <option key={unit.unit_id} value={unit.unit_id}>
          {unit.first_session} – {unit.last_session} · {unit.source_kind === "research_run" ? "Backtest" : "Tracking"}{unit.status === "expired" ? " · Expired" : ""}
        </option>)}</select></label>
        {status.next_cursor && <button type="button" disabled={busy} onClick={() => loadPeriods(status.next_cursor)}>More periods</button>}
        {selectedUnit && <p>{selectedUnit.status === "expired" ? "Expired" : "Available until"}: <time>{new Date(selectedUnit.expires_at).toLocaleString()}</time></p>}
        <form className="strategy-event-filters" onSubmit={event => {
          event.preventDefault();
          if (draft.start_session && draft.end_session && draft.start_session > draft.end_session) {
            setFieldErrors({ end_session: "Through must be on or after From." });
            return;
          }
          const next = Object.fromEntries(Object.entries(draft).filter(([, value]) => value !== "")) as Filters;
          setFilters(next); loadDetails(null, next);
        }}>
          <label>From<input type="date" value={draft.start_session} onChange={event => setDraft({ ...draft, start_session: event.target.value })} aria-invalid={!!fieldErrors.start_session} />{fieldErrors.start_session && <span className="daily-holdings-validation" role="alert">{fieldErrors.start_session}</span>}</label>
          <label>Through<input type="date" value={draft.end_session} onChange={event => setDraft({ ...draft, end_session: event.target.value })} aria-invalid={!!fieldErrors.end_session} />{fieldErrors.end_session && <span className="daily-holdings-validation" role="alert">{fieldErrors.end_session}</span>}</label>
          <label>Instrument<input value={draft.instrument_id} placeholder="equity:600001.SH" onChange={event => setDraft({ ...draft, instrument_id: event.target.value })} aria-invalid={!!fieldErrors.instrument_id} />{fieldErrors.instrument_id && <span className="daily-holdings-validation" role="alert">{fieldErrors.instrument_id}</span>}</label>
          <button type="submit" disabled={busy || !unitId}>Load holdings</button>
        </form>
      </>}
      {busy && <p role="status">Loading…</p>}
      {error && <p role="alert">{error}</p>}
      {details?.status === "expired" && <p>These holdings have expired. Permanent results and trading events remain available.</p>}
      {rerun && selectedUnit?.status === "expired" && <CurrentDataRerun
        key={`${unitId}:${JSON.stringify(rerun.source)}`} folderId={rerun.folderId}
        source={rerun.source.kind === "daily_track"
          ? { ...rerun.source, through_session: selectedUnit.last_session } : rerun.source} />}
      {details?.status === "not_recorded" && <p>Daily holdings were not recorded for this period.</p>}
      {details?.status === "available" && <>
        <p>{details.coverage?.session_count ?? 0} Research Sessions covered.</p>
        {details.rows.length === 0 ? <p>{details.next_cursor ? "No matching holdings on this page. Continue to check the remaining dates." : "No holdings on this page."}</p> : <div className="daily-holdings-table" role="region" aria-label="Daily holdings rows" tabIndex={0}>
          <table><thead><tr><th>Session</th><th>Instrument</th><th>Shares</th><th>Adjusted units</th><th>Adjusted mark</th><th>Value (CNY)</th><th>Weight</th></tr></thead>
            <tbody>{details.rows.map(row => <tr key={`${row.session}:${row.instrument_id}`}><td>{row.session}</td><td>{row.instrument_id}</td><td>{row.execution_shares}</td><td>{row.adjusted_units}</td><td>{row.adjusted_mark}</td><td>{row.market_value_cny}</td><td>{(row.weight * 100).toFixed(2)}%</td></tr>)}</tbody>
          </table>
        </div>}
        {details.next_cursor && <button type="button" disabled={busy} onClick={() => loadDetails(details.next_cursor, filters)}>Next holdings page</button>}
      </>}
    </div>}
  </section>;
}
