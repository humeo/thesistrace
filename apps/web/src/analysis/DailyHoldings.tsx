import { useTranslation } from "../i18n";
import { formatNumber, formatPercent, formatTimestamp } from "../i18n/format";
import { useEffect, useRef, useState } from "react";
import { CurrentDataRerun, type RerunSource } from "./CurrentDataRerun";
import { coreFetch } from "../auth/coreFetch";
import "./strategy-events.css";
import "./daily-holdings.css";

type Unit = { unit_id: string; source_kind: string; first_session: string; last_session: string; expires_at: string; status: "available" | "expired" };
type StatusPage = { status: "recorded" | "not_recorded"; units: Unit[]; next_cursor: string | null };
type Row = { session: string; instrument_id: string; execution_shares: number; adjusted_units: string; adjusted_mark: string; market_value_cny: string; weight: number };
type Details = { status: "available" | "expired" | "not_recorded"; unit: Unit | null; rows: Row[]; coverage: { session_count: number } | null; next_cursor: string | null };
type FieldError = "invalidRange" | "invalidValue" | "invalidDate" | "invalidInstrument";
type Filters = { start_session?: string; end_session?: string; instrument_id?: string };

export function DailyHoldings({ endpoint, rerun }: {
  endpoint: string;
  rerun?: { folderId: string; source: RerunSource };
}) {
  const { t } = useTranslation("analysis");
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<StatusPage | null>(null);
  const [unitId, setUnitId] = useState("");
  const [details, setDetails] = useState<Details | null>(null);
  const [draft, setDraft] = useState({ start_session: "", end_session: "", instrument_id: "" });
  const [fieldErrors, setFieldErrors] = useState<Record<string, FieldError>>({});
  const [filters, setFilters] = useState<Filters>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<"invalidQuery" | "cursorError" | "loadError" | null>(null);
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
        const problem = await response.json() as { detail?: { loc?: string[]; type?: string }[] };
        if (controller.signal.aborted) return;
        const errors: Record<string, FieldError> = {};
        if (Array.isArray(problem.detail)) for (const item of problem.detail) {
          const field = item.loc?.at(-1);
          if (field && ["start_session", "end_session", "instrument_id"].includes(field)) {
            errors[field] = field === "instrument_id" && item.type === "string_pattern_mismatch" ? "invalidInstrument"
              : ["start_session", "end_session"].includes(field) && item.type?.startsWith("date_") ? "invalidDate" : "invalidValue";
          }
        }
        if (Object.keys(errors).length) { setFieldErrors(errors); return; }
        setError("invalidQuery"); return;
      }
      if (!response.ok) { if (!controller.signal.aborted) setError(response.status === 400 ? "cursorError" : "loadError"); return; }
      const value: unknown = await response.json();
      if (!controller.signal.aborted) accept(value);
    } catch {
      if (!controller.signal.aborted) setError("loadError");
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
    <button type="button" className="strategy-events-toggle" aria-label={t("holdings.title")} aria-expanded={open} onClick={() => {
      setOpen(!open);
      if (!open && !status) loadPeriods();
    }}><span>{t("holdings.title")}</span></button>
    {open && <div className="daily-holdings-content">
      <p>{t("holdings.explanation")}</p>
      <button type="button" disabled={busy} onClick={() => loadPeriods()}>{t("holdings.check")}</button>
      {status?.status === "not_recorded" && <p>{t("holdings.notRecordedResult")}</p>}
      {status && status.units.length > 0 && <>
        <label>{t("holdings.period")}<select value={unitId} disabled={busy} onChange={event => {
          setUnitId(event.target.value); setDetails(null);
        }}>{status.units.map(unit => <option key={unit.unit_id} value={unit.unit_id}>
          {unit.first_session} – {unit.last_session} · {unit.source_kind === "research_run" ? t("holdings.backtest") : t("holdings.tracking")}{unit.status === "expired" ? ` · ${t("holdings.expired")}` : ""}
        </option>)}</select></label>
        {status.next_cursor && <button type="button" disabled={busy} onClick={() => loadPeriods(status.next_cursor)}>{t("holdings.more")}</button>}
        {selectedUnit && <p>{selectedUnit.status === "expired" ? t("holdings.expired") : t("holdings.until")}: <time>{formatTimestamp(selectedUnit.expires_at, { year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" })}</time></p>}
        <form className="strategy-event-filters" onSubmit={event => {
          event.preventDefault();
          if (draft.start_session && draft.end_session && draft.start_session > draft.end_session) {
            setFieldErrors({ end_session: "invalidRange" });
            return;
          }
          const next = Object.fromEntries(Object.entries(draft).filter(([, value]) => value !== "")) as Filters;
          setFilters(next); loadDetails(null, next);
        }}>
          <label>{t("holdings.from")}<input type="date" value={draft.start_session} onChange={event => setDraft({ ...draft, start_session: event.target.value })} aria-invalid={!!fieldErrors.start_session} />{fieldErrors.start_session && <span className="daily-holdings-validation" role="alert">{t(`holdings.${fieldErrors.start_session}`)}</span>}</label>
          <label>{t("holdings.through")}<input type="date" value={draft.end_session} onChange={event => setDraft({ ...draft, end_session: event.target.value })} aria-invalid={!!fieldErrors.end_session} />{fieldErrors.end_session && <span className="daily-holdings-validation" role="alert">{t(`holdings.${fieldErrors.end_session}`)}</span>}</label>
          <label>{t("holdings.instrument")}<input value={draft.instrument_id} placeholder="equity:600001.SH" onChange={event => setDraft({ ...draft, instrument_id: event.target.value })} aria-invalid={!!fieldErrors.instrument_id} />{fieldErrors.instrument_id && <span className="daily-holdings-validation" role="alert">{t(`holdings.${fieldErrors.instrument_id}`)}</span>}</label>
          <button type="submit" disabled={busy || !unitId}>{t("holdings.load")}</button>
        </form>
      </>}
      {busy && <p role="status">{t("loading")}</p>}
      {error && <p role="alert">{t(`holdings.${error}`)}</p>}
      {details?.status === "expired" && <p>{t("holdings.expiredDetails")}</p>}
      {rerun && selectedUnit?.status === "expired" && <CurrentDataRerun
        key={`${unitId}:${JSON.stringify(rerun.source)}`} folderId={rerun.folderId}
        source={rerun.source.kind === "daily_track"
          ? { ...rerun.source, through_session: selectedUnit.last_session } : rerun.source} />}
      {details?.status === "not_recorded" && <p>{t("holdings.notRecordedPeriod")}</p>}
      {details?.status === "available" && <>
        <p>{t("holdings.coverage", { count: details.coverage?.session_count ?? 0 })}</p>
        {details.rows.length === 0 ? <p>{details.next_cursor ? t("holdings.emptyMore") : t("holdings.empty")}</p> : <div className="daily-holdings-table" role="region" aria-label={t("holdings.rows")} tabIndex={0}>
          <table><thead><tr><th>{t("holdings.session")}</th><th>{t("holdings.instrument")}</th><th>{t("holdings.shares")}</th><th>{t("holdings.units")}</th><th>{t("holdings.mark")}</th><th>{t("holdings.value")}</th><th>{t("holdings.weight")}</th></tr></thead>
            <tbody>{details.rows.map(row => <tr key={`${row.session}:${row.instrument_id}`}><td>{row.session}</td><td>{row.instrument_id}</td><td>{formatNumber(row.execution_shares)}</td><td>{row.adjusted_units}</td><td>{row.adjusted_mark}</td><td>{row.market_value_cny}</td><td>{formatPercent(row.weight)}</td></tr>)}</tbody>
          </table>
        </div>}
        {details.next_cursor && <button type="button" disabled={busy} onClick={() => loadDetails(details.next_cursor, filters)}>{t("holdings.next")}</button>}
      </>}
    </div>}
  </section>;
}
