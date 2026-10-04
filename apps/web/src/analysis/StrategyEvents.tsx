import { i18n, useTranslation } from "../i18n";
import { formatNumber } from "../i18n/format";
import { useEffect, useId, useRef, useState } from "react";
import { coreFetch } from "../auth/coreFetch";
import { StrategyEventTable, eventSections as sections, instrumentLabel, eventSectionLabel, eventScopeLabel, type EventScope, type EventRow, type EventSection as Section } from "./StrategyEventDetails";
import { Button } from "../components/ui/button";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../components/ui/collapsible";
import { Empty, EmptyDescription } from "../components/ui/empty";
import { Field, FieldGroup, FieldLabel } from "../components/ui/field";
import { Input } from "../components/ui/input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { CalendarDateField } from "../components/layout/CalendarDateField";
import { InfoHelp } from "../components/product/InfoHelp";
import { retrievalCalendarBounds, validateRetrievalDates, type RetrievalDateError, type RetrievalDateRange } from "./retrievalDates";

type Page = { section: Section; status: "recorded" | "not_recorded" | "expired" | "partially_expired"; expires_at: string | null; rows: EventRow[]; next_cursor: string | null };
type Filter = { start_session?: string; end_session?: string; instrument_id?: string; target_id?: string; order_id?: string; child_order_id?: string };
type View = { section: Section; filters: Filter; cursors: (string | null)[]; scope: EventScope | null };
function stockFilter(value: string) {
  const trimmed = value.trim();
  return /^\d{6}\.(SH|SZ)$/i.test(trimmed) ? "equity:" + trimmed.toUpperCase() : trimmed || undefined;
}

export function StrategyEvents({ endpoint, embedded = false, dateRange, initialQuery }: { endpoint: string; embedded?: boolean; dateRange?: RetrievalDateRange; initialQuery?: { section: Section; filters?: Filter; scope?: EventScope } }) {
  const { t } = useTranslation("analysis");
  const [open, setOpen] = useState(embedded);
  const id = useId();
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<"start_session" | "end_session", RetrievalDateError>>>({});
  const [section, setSection] = useState<Section>(initialQuery?.section ?? "strategy_orders");
  const [filters, setFilters] = useState<Filter>(initialQuery?.filters ?? {});
  const [draft, setDraft] = useState({ start_session: "", end_session: "", instrument_id: "" });
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [scope, setScope] = useState<EventScope | null>(initialQuery?.scope ?? null);
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
    setFieldErrors({});
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
  const content = <div className="flex min-w-0 flex-col gap-4">
      <header className="flex items-center justify-between gap-4">
        <h3 className="m-0 text-base font-semibold outline-none" ref={heading} tabIndex={-1}>{eventSectionLabel(section)}</h3>
        <InfoHelp label={eventSectionLabel(section)} buttonLabel={t("help.about", { label: eventSectionLabel(section) })} closeLabel={t("help.close")}>
          <div className="flex flex-col gap-2 [&_p]:m-0">
            <p>{t(`events.descriptions.${section}`)}</p>
            <p>{t("events.retention")}</p>
          </div>
        </InfoHelp>
      </header>
      <form onSubmit={event => {
        event.preventDefault();
        const invalid = validateRetrievalDates(draft, dateRange);
        setFieldErrors(invalid);
        if (Object.keys(invalid).length) return;
        setPage(null); setCursors([null]);
        setFilters({ ...filters, start_session: draft.start_session || undefined, end_session: draft.end_session || undefined, instrument_id: stockFilter(draft.instrument_id) });
        focusAfterNavigation.current = true;
      }}>
        <FieldGroup className="grid items-end gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Field>
            <FieldLabel htmlFor={`${id}-section`}>{t("events.type")}</FieldLabel>
            <Select value={section} onValueChange={value => { if (value) navigate(value); }} items={sections.map(value => ({ value, label: eventSectionLabel(value) }))}>
              <SelectTrigger id={`${id}-section`} className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent><SelectGroup>{sections.map(value => <SelectItem key={value} value={value}>{eventSectionLabel(value)}</SelectItem>)}</SelectGroup></SelectContent>
            </Select>
          </Field>
          {(["start_session", "end_session"] as const).map(key => <CalendarDateField key={key}
            id={`${id}-${key}`} label={t(key === "start_session" ? "events.from" : "events.through")}
            openLabel={i18n.t(key === "start_session" ? "research:openStartCalendar" : "research:openEndCalendar")}
            value={draft[key]} onChange={value => setDraft({ ...draft, [key]: value })}
            {...retrievalCalendarBounds(key, draft, dateRange)}
            error={fieldErrors[key] ? t(`holdings.${fieldErrors[key]}`, dateRange) : undefined} errorId={`${id}-${key}-error`} />)}
          <Field><FieldLabel htmlFor={`${id}-instrument`}>{t("events.instrument")}</FieldLabel><Input id={`${id}-instrument`} disabled={section === "strategy_history_reads"} value={draft.instrument_id} placeholder="600000.SH" onChange={event => setDraft({ ...draft, instrument_id: event.target.value })} /></Field>
        </FieldGroup>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button type="submit">{t("events.query")}</Button>
          <Button variant="outline" type="button" disabled={!filtered && !draft.start_session && !draft.end_session && !draft.instrument_id} onClick={() => navigate(section)}>{t("events.reset")}</Button>
        </div>
      </form>
      {scope && <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-muted p-4" role="region" aria-label={t("events.scope")}>
        <span>{t("events.relatedOnly", { relatedContext: eventScopeLabel(scope) })}</span>
        <div className="flex flex-wrap gap-4">
          {history.length > 0 && <Button variant="link" size="sm" className="px-0" type="button" onClick={goBack}>{t("events.back", { section: eventSectionLabel(history.at(-1)!.section) })}</Button>}
          <Button variant="link" size="sm" className="px-0" type="button" onClick={() => navigate(section)}>{t("events.viewAll", { section: eventSectionLabel(section) })}</Button>
        </div>
      </div>}
      <div className="flex flex-wrap justify-between gap-2 text-muted-foreground">
        <span>{filters.start_session || filters.end_session ? t("events.dateRange", { start: filters.start_session ?? t("events.earliest"), end: filters.end_session ?? t("events.latest") }) : t("events.allDates")} · {filters.instrument_id ? instrumentLabel(filters.instrument_id) : t("events.allStocks")}</span>
        <span>{section === "strategy_targets" || section === "strategy_framework" || section === "strategy_history_reads" ? t("events.decisionDate") : section === "strategy_adjustments" ? t("events.adjustmentDate") : t("events.executionDate")} · {t("events.pageSize")}</span>
      </div>
      {page?.status === "partially_expired" && <p role="status">{t("events.partialExpiry")}</p>}
      {error ? <Alert variant="destructive"><AlertDescription>{t(`events.${error}`)}</AlertDescription></Alert> : page === null ? <p role="status">{t("events.loading")}</p>
        : page.status === "expired" ? <p role="status">{t("events.expired")}</p>
        : page.status === "not_recorded" ? <p>{section === "strategy_execution_constraints"
          ? t("events.constraintsNotRecorded")
          : t("events.notRecorded")}</p>
        : page.rows.length === 0 ? <Empty><EmptyDescription>{t("events.empty", { section: eventSectionLabel(section) })}</EmptyDescription></Empty>
        : <StrategyEventTable key={section + ":" + JSON.stringify(filters) + ":" + cursor}
            section={section} rows={page.rows} navigate={navigate} />}
      <nav className="flex flex-wrap items-center gap-3" aria-label={t("events.pages")}>
        <span className="flex flex-wrap gap-2" role="status">{(page?.status === "recorded" || page?.status === "partially_expired") && !error && <>{t("events.count", { count: page.rows.length })}{!page.next_cursor && <span>{filtered ? t("events.filterEnd") : t("events.end")}</span>}</>}</span>
        <Button variant="outline" type="button" onClick={() => { setPage(null); setCursors([null]); setRevision(value => value + 1); focusAfterNavigation.current = true; }}>{t("reloadFirst")}</Button>
        <Button variant="outline" type="button" disabled={cursors.length === 1 || !page} onClick={() => { setPage(null); setCursors(values => values.slice(0, -1)); focusAfterNavigation.current = true; }}>{t("previous")}</Button>
        <span>{t("page", { page: formatNumber(cursors.length) })}</span>
        <Button variant="outline" type="button" disabled={!page?.next_cursor} onClick={() => { if (page?.next_cursor) { setCursors(values => [...values, page.next_cursor]); setPage(null); focusAfterNavigation.current = true; } }}>{t("next")}</Button>
      </nav>
    </div>;
  if (embedded) return <section aria-label={t("events.title")} className="min-w-0">{content}</section>;
  return <Collapsible open={open} onOpenChange={setOpen} className="min-w-0">
    <CollapsibleTrigger render={<Button variant="outline" />}>{t("events.title")}</CollapsibleTrigger>
    <CollapsibleContent keepMounted className="pt-4">{content}</CollapsibleContent>
  </Collapsible>;
}
