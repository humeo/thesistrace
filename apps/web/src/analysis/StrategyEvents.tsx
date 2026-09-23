import { useTranslation } from "../i18n";
import { formatNumber } from "../i18n/format";
import { useEffect, useRef, useState } from "react";
import { coreFetch } from "../auth/coreFetch";
import { StrategyEventTable, eventSections as sections, instrumentLabel, eventSectionLabel, eventScopeLabel, type EventScope, type EventRow, type EventSection as Section } from "./StrategyEventDetails";
import "./strategy-events.css";

type Page = { section: Section; status: "recorded" | "not_recorded" | "expired" | "partially_expired"; expires_at: string | null; rows: EventRow[]; next_cursor: string | null };
type Filter = { start_session?: string; end_session?: string; instrument_id?: string; target_id?: string; order_id?: string; child_order_id?: string };
type View = { section: Section; filters: Filter; cursors: (string | null)[]; scope: EventScope | null };
function stockFilter(value: string) {
  const trimmed = value.trim();
  return /^\d{6}\.(SH|SZ)$/i.test(trimmed) ? "equity:" + trimmed.toUpperCase() : trimmed || undefined;
}

export function StrategyEvents({ endpoint }: { endpoint: string }) {
  const { t } = useTranslation("analysis");
  const [open, setOpen] = useState(false);
  const [section, setSection] = useState<Section>("strategy_orders");
  const [filters, setFilters] = useState<Filter>({});
  const [draft, setDraft] = useState({ start_session: "", end_session: "", instrument_id: "" });
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [scope, setScope] = useState<EventScope | null>(null);
  const [history, setHistory] = useState<View[]>([]);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<"cursorError" | "invalidQuery" | "loadError" | null>(null);
  const [revision, setRevision] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const focusAfterNavigation = useRef(false);
  const cursor = cursors[cursors.length - 1];
  const filtered = Object.values(filters).some(value => !!value);
  function navigate(next: Section, relation: Filter = {}, context: EventScope | null = null) {
    setHistory(context ? [...history, { section, filters, cursors, scope }] : []);
    setScope(context);
    setPage(null); setSection(next); setFilters(relation); setCursors([null]);
    setDraft({ start_session: "", end_session: "", instrument_id: "" });
    focusAfterNavigation.current = true;
  }
  function goBack() {
    const previous = history.at(-1);
    if (!previous) return;
    setHistory(history.slice(0, -1));
    setSection(previous.section); setFilters(previous.filters); setCursors(previous.cursors); setScope(previous.scope);
    setDraft({ start_session: previous.filters.start_session ?? "", end_session: previous.filters.end_session ?? "", instrument_id: previous.filters.instrument_id ?? "" });
    setPage(null); focusAfterNavigation.current = true;
  }
  useEffect(() => {
    if (!open) return;
    if (focusAfterNavigation.current) {
      heading.current?.focus({ preventScroll: true });
      heading.current?.scrollIntoView({ block: "nearest" });
      focusAfterNavigation.current = false;
    }
    const controller = new AbortController();
    setPage(null); setError(null);
    void coreFetch(endpoint, {
      method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
      body: JSON.stringify({ section, ...filters, cursor, limit: 20 }),
    }).then(async response => {
      if (!response.ok) { if (!controller.signal.aborted) setError(response.status === 400 ? "cursorError" : response.status === 422 ? "invalidQuery" : "loadError"); return; }
      const result = await response.json() as Page;
      if (!controller.signal.aborted) setPage(result);
    }).catch(() => {
      if (!controller.signal.aborted) setError("loadError");
    });
    return () => controller.abort();
  }, [open, endpoint, section, filters, cursor, revision]);
  return <details className="strategy-events" onToggle={event => {
    if (event.target === event.currentTarget) setOpen(event.currentTarget.open);
  }}>
    <summary><span>{t("events.title")}</span></summary>
    {open && <div className="strategy-events-content">
      <header className="strategy-events-heading">
        <h3 ref={heading} tabIndex={-1}>{eventSectionLabel(section)}</h3>
        <p>{t(`events.descriptions.${section}`)}</p>
        <p>{t("events.retention")}</p>
      </header>
      <form className="strategy-event-filters" onSubmit={event => {
        event.preventDefault(); setPage(null); setCursors([null]);
        setFilters({ ...filters, start_session: draft.start_session || undefined, end_session: draft.end_session || undefined, instrument_id: stockFilter(draft.instrument_id) });
        focusAfterNavigation.current = true;
      }}>
        <label>{t("events.type")}<select value={section} onChange={event => navigate(event.target.value as Section)}>
          {sections.map(value => <option key={value} value={value}>{eventSectionLabel(value)}</option>)}
        </select></label>
        <label>{t("events.from")}<input type="date" value={draft.start_session} max={draft.end_session || undefined} onChange={event => setDraft({ ...draft, start_session: event.target.value })} /></label>
        <label>{t("events.through")}<input type="date" value={draft.end_session} min={draft.start_session || undefined} onChange={event => setDraft({ ...draft, end_session: event.target.value })} /></label>
        <label>{t("events.instrument")}<input value={draft.instrument_id} placeholder="600000.SH" onChange={event => setDraft({ ...draft, instrument_id: event.target.value })} /></label>
        <button type="submit">{t("events.query")}</button>
        <button type="button" disabled={!filtered && !draft.start_session && !draft.end_session && !draft.instrument_id} onClick={() => navigate(section)}>{t("events.reset")}</button>
      </form>
      {scope && <div className="strategy-event-scope" role="region" aria-label={t("events.scope")}>
        <span>{t("events.relatedOnly", { relatedContext: eventScopeLabel(scope) })}</span>
        <div className="strategy-event-links">
          {history.length > 0 && <button type="button" onClick={goBack}>{t("events.back", { section: eventSectionLabel(history.at(-1)!.section) })}</button>}
          <button type="button" onClick={() => navigate(section)}>{t("events.viewAll", { section: eventSectionLabel(section) })}</button>
        </div>
      </div>}
      <div className="strategy-events-status">
        <span>{filters.start_session || filters.end_session ? t("events.dateRange", { start: filters.start_session ?? t("events.earliest"), end: filters.end_session ?? t("events.latest") }) : t("events.allDates")} · {filters.instrument_id ? instrumentLabel(filters.instrument_id) : t("events.allStocks")}</span>
        <span>{section === "strategy_targets" ? t("events.decisionDate") : section === "strategy_adjustments" ? t("events.adjustmentDate") : t("events.executionDate")} · {t("events.pageSize")}</span>
      </div>
      {page?.status === "partially_expired" && <p role="status">{t("events.partialExpiry")}</p>}
      {error ? <p role="alert">{t(`events.${error}`)}</p> : page === null ? <p role="status">{t("events.loading")}</p>
        : page.status === "expired" ? <p role="status">{t("events.expired")}</p>
        : page.status === "not_recorded" ? <p>{section === "strategy_execution_constraints"
          ? t("events.constraintsNotRecorded")
          : t("events.notRecorded")}</p>
        : page.rows.length === 0 ? <p>{t("events.empty", { section: eventSectionLabel(section) })}</p>
        : <StrategyEventTable key={section + ":" + JSON.stringify(filters) + ":" + cursor}
            section={section} rows={page.rows} navigate={navigate} />}
      <nav aria-label={t("events.pages")}>
        <span className="strategy-event-page-count" role="status">{(page?.status === "recorded" || page?.status === "partially_expired") && !error && <>{t("events.count", { count: page.rows.length })}{!page.next_cursor && <span>{filtered ? t("events.filterEnd") : t("events.end")}</span>}</>}</span>
        <button type="button" onClick={() => { setPage(null); setCursors([null]); setRevision(value => value + 1); focusAfterNavigation.current = true; }}>{t("reloadFirst")}</button>
        <button type="button" disabled={cursors.length === 1 || !page} onClick={() => { setPage(null); setCursors(values => values.slice(0, -1)); focusAfterNavigation.current = true; }}>{t("previous")}</button>
        <span>{t("page", { page: formatNumber(cursors.length) })}</span>
        <button type="button" disabled={!page?.next_cursor} onClick={() => { if (page?.next_cursor) { setCursors(values => [...values, page.next_cursor]); setPage(null); focusAfterNavigation.current = true; } }}>{t("next")}</button>
      </nav>
    </div>}
  </details>;
}
