import { i18n, useTranslation } from "../i18n";
import { formatDecimal, formatNumber, formatPercent } from "../i18n/format";
import { useEffect, useId, useState } from "react";
import { coreFetch } from "../auth/coreFetch";
import { Button } from "../components/ui/button";
import { Field, FieldGroup, FieldLabel } from "../components/ui/field";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../components/ui/collapsible";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { CalendarDateField } from "../components/layout/CalendarDateField";
import { isIsoCalendarDate } from "../components/layout/calendarDate";

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
function reasonLabel(reason: string) {
  const labels = i18n.t("analysis:factor.reasons", { returnObjects: true });
  return labels[reason as keyof typeof labels] ?? i18n.t("analysis:unknownReason");
}
const number = (value: number | null) => formatDecimal(value, 3, "dash");
const percent = (value: number | null) => formatPercent(value, { missing: "dash" });
function Exclusions({ values }: { values: Record<string, number> }) {
  useTranslation("analysis");
  return <>{Object.entries(values).map(([reason, count]) =>
    <span className="mt-1 block text-muted-foreground" key={reason}>{reasonLabel(reason)}: {formatNumber(count)}</span>)}</>;
}
function SampleCoverage({ value }: { value: Coverage }) {
  const { t } = useTranslation("analysis");
  return <><p>{t("factor.samples", { candidates: formatNumber(value.alpha_candidate_count), signals: formatNumber(value.alpha_sample_count), labels: formatNumber(value.sample_count) })}</p>
    <Exclusions values={value.alpha_exclusions} /><Exclusions values={value.label_exclusions} /></>;
}

export function FactorEvidence({ runId, embedded = false }: { runId: string; embedded?: boolean }) {
  const { t } = useTranslation("analysis");
  const [open, setOpen] = useState(false);
  const [filters, setFilters] = useState<Filters>({ horizon: "5", view: "month", start: "", end: "" });
  const id = useId();
  const invalidStart = filters.view === "daily" && filters.start !== "" && !isIsoCalendarDate(filters.start);
  const invalidEnd = filters.view === "daily" && filters.end !== "" && !isIsoCalendarDate(filters.end);
  const invalidRange = filters.view === "daily" && !invalidStart && !invalidEnd && filters.start !== "" && filters.end !== "" && filters.start > filters.end;
  const content = <div className="[&>p]:max-w-[90ch] [&>p]:text-sm [&>p]:text-muted-foreground">
      <p>{t("factor.explanation")}</p>
      <FieldGroup className="my-5 grid grid-cols-[repeat(auto-fit,minmax(min(100%,180px),1fr))] gap-4">
        <Field><FieldLabel htmlFor={`${id}-horizon`}>{t("factor.horizon")}</FieldLabel>
          <Select value={filters.horizon} onValueChange={value => setFilters({ ...filters, horizon: value ?? "5" })}>
            <SelectTrigger id={`${id}-horizon`} aria-label={t("factor.horizon")}><SelectValue>{t("factor.sessions", { count: Number(filters.horizon) })}</SelectValue></SelectTrigger>
            <SelectContent><SelectGroup>{[1, 5, 20].map(h => <SelectItem value={String(h)} key={h}>{t("factor.sessions", { count: h })}</SelectItem>)}</SelectGroup></SelectContent>
          </Select>
        </Field>
        <Field><FieldLabel htmlFor={`${id}-view`}>{t("factor.view")}</FieldLabel>
          <Select value={filters.view} onValueChange={value => setFilters({ ...filters, view: (value ?? "month") as Filters["view"] })}>
            <SelectTrigger id={`${id}-view`} aria-label={t("factor.view")}><SelectValue>{t(filters.view === "daily" ? "factor.daily" : filters.view === "month" ? "factor.month" : filters.view === "year" ? "factor.year" : "factor.all")}</SelectValue></SelectTrigger>
            <SelectContent><SelectGroup>
              <SelectItem value="daily">{t("factor.daily")}</SelectItem><SelectItem value="month">{t("factor.month")}</SelectItem>
              <SelectItem value="year">{t("factor.year")}</SelectItem><SelectItem value="all">{t("factor.all")}</SelectItem>
            </SelectGroup></SelectContent>
          </Select>
        </Field>
        {filters.view === "daily" && <>
          <CalendarDateField id={`${id}-start`} label={t("factor.from")} openLabel={t("factor.openFromCalendar")} value={filters.start}
            minimum={null} maximum={filters.end || null} error={invalidStart ? t("factor.invalidDate") : undefined} errorId={`${id}-start-error`}
            onChange={value => setFilters({ ...filters, start: value })} />
          <CalendarDateField id={`${id}-end`} label={t("factor.through")} openLabel={t("factor.openThroughCalendar")} value={filters.end}
            minimum={filters.start || null} maximum={null} error={invalidEnd ? t("factor.invalidDate") : invalidRange ? t("factor.invalidRange") : undefined} errorId={`${id}-end-error`}
            onChange={value => setFilters({ ...filters, end: value })} />
        </>}
      </FieldGroup>
      {filters.view !== "daily" && <p>{t("factor.grouping")}</p>}
      <EvidencePage key={`${runId}:${JSON.stringify(filters)}`} runId={runId} filters={filters} />
    </div>;
  return embedded ? <section aria-label={t("factor.title")} className="min-w-0 data-[slot=collapsible]:border-t data-[slot=collapsible]:border-border">{content}</section>
    : <Collapsible open={open} onOpenChange={setOpen} className="min-w-0 data-[slot=collapsible]:border-t data-[slot=collapsible]:border-border">
      <CollapsibleTrigger render={<Button variant="ghost" className="min-h-11" />}>{t("factor.title")}</CollapsibleTrigger>
      <CollapsibleContent>{open ? content : null}</CollapsibleContent>
    </Collapsible>;
}

function EvidencePage({ runId, filters }: { runId: string; filters: Filters }) {
  const { t } = useTranslation("analysis");
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<"cursor" | "load" | null>(null);
  const [retry, setRetry] = useState(0);
  const cursor = cursors[cursors.length - 1];
  const invalidRange = filters.view === "daily" && filters.start !== "" && filters.end !== "" && filters.start > filters.end;
  const invalidDate = filters.view === "daily" && [filters.start, filters.end].some(value => value !== "" && !isIsoCalendarDate(value));
  useEffect(() => {
    if (invalidRange || invalidDate) return;
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
        if (!response.ok) { if (!controller.signal.aborted) setError(response.status === 400 ? "cursor" : "load"); return; }
        const result = await response.json() as Page;
        if (!controller.signal.aborted) setPage(result);
      }).catch(() => {
        if (!controller.signal.aborted) setError("load");
      });
    return () => controller.abort();
  }, [runId, filters, cursor, retry, invalidRange, invalidDate]);
  if (invalidDate || invalidRange) return null;
  return <>
    {error ? <div role="alert"><p>{t(error === "cursor" ? "factor.cursorError" : "factor.loadError")}</p><Button variant="outline" onClick={() => { setCursors([null]); setRetry(value => value + 1); }}>{t("reloadFirst")}</Button></div>
      : page === null ? <p role="status">{t("factor.loading")}</p>
      : page.items.length === 0 ? <p>{t("factor.empty")}</p>
      : <div className="max-w-full [&_[data-slot=table]]:tabular-nums [&_[data-slot=table-head]]:p-3 [&_[data-slot=table-cell]]:p-3 [&_[data-slot=table-head]]:text-right [&_[data-slot=table-cell]]:text-right [&_[data-slot=table-head]:first-child]:text-left [&_[data-slot=table-cell]:first-child]:text-left [&_[data-slot=table-head]:last-child]:text-left [&_[data-slot=table-cell]:last-child]:min-w-[220px] [&_[data-slot=table-cell]:last-child]:max-w-[320px] [&_[data-slot=table-cell]:last-child]:whitespace-normal [&_[data-slot=table-cell]:last-child]:text-left [&_small]:mt-1 [&_small]:block [&_small]:text-muted-foreground [&_[data-slot=collapsible-content]_p]:my-2"><Table scrollLabel={page.section === "factor_observations" ? t("factor.dailyCaption") : t("factor.periodCaption")}>
        <TableCaption>{page.section === "factor_observations" ? t("factor.dailyCaption") : t("factor.periodCaption")}</TableCaption>
        <TableHeader><TableRow><TableHead>{page.section === "factor_observations" ? t("factor.signalDate") : t("factor.period")}</TableHead><TableHead>IC</TableHead><TableHead>Rank IC</TableHead>
          {page.section === "factor_periods" && <><TableHead>ICIR</TableHead><TableHead>Rank ICIR</TableHead></>}
          {groups.map(group => <TableHead key={group}>{group.toUpperCase()}</TableHead>)}<TableHead>Q5 − Q1</TableHead><TableHead>{t("factor.evidence")}</TableHead></TableRow></TableHeader>
        <TableBody>{page.section === "factor_observations" ? page.items.map(row => <TableRow key={row.session}>
          <TableCell>{row.session}</TableCell><TableCell>{number(row.ic)}</TableCell><TableCell>{number(row.rank_ic)}</TableCell>
          {groups.map(group => <TableCell key={group}>{percent(row.quantile_returns[group])}<small>n={row.quantile_counts[group] === null ? "—" : formatNumber(row.quantile_counts[group])}</small></TableCell>)}
          <TableCell>{percent(row.top_bottom_return)}</TableCell><TableCell><Collapsible><CollapsibleTrigger render={<Button variant="ghost" size="sm" />}>{t("factor.coverage")}</CollapsibleTrigger><CollapsibleContent>
            <SampleCoverage value={row} />
            <p>{t("factor.open", { start: row.label_entry_session ?? "—", end: row.label_exit_session ?? "—" })}</p>
            {row.label_status === "right_censored_by_research_period_end" && <p>{t("factor.reasons.right_censored_by_research_period_end")}</p>}
            {row.correlation_reason && <p>{reasonLabel(row.correlation_reason)}</p>}
          </CollapsibleContent></Collapsible></TableCell></TableRow>) : page.items.map(row => <TableRow key={row.period}>
          <TableCell>{row.period}</TableCell><TableCell>{number(row.summary.ic.mean)}</TableCell><TableCell>{number(row.summary.rank_ic.mean)}</TableCell>
          <TableCell>{number(row.summary.ic.icir)}</TableCell><TableCell>{number(row.summary.rank_ic.icir)}</TableCell>
          {groups.map(group => <TableCell key={group}>{percent(row.summary.quantile_returns[group])}</TableCell>)}
          <TableCell>{percent(row.summary.top_bottom_return)}</TableCell><TableCell><Collapsible><CollapsibleTrigger render={<Button variant="ghost" size="sm" />}>{t("factor.coverageCount", { valid: formatNumber(row.coverage.label_evaluable_session_count), total: formatNumber(row.coverage.signal_session_count) })}</CollapsibleTrigger><CollapsibleContent>
            <p>{t("factor.signals", { start: row.coverage.first_signal_session, end: row.coverage.last_signal_session })}</p>
            <p>{t("factor.evaluable", { start: row.coverage.first_evaluable_signal_session ?? "—", end: row.coverage.last_evaluable_signal_session ?? "—" })}</p>
            <p>{t("factor.validDays", { ic: formatNumber(row.coverage.ic_valid_session_count), rankIc: formatNumber(row.coverage.rank_ic_valid_session_count), tail: formatNumber(row.coverage.right_censored_session_count) })}</p>
            <SampleCoverage value={row.coverage} />
          </CollapsibleContent></Collapsible></TableCell></TableRow>)}</TableBody>
      </Table></div>}
    <nav aria-label={t("factor.pages")} className="flex flex-wrap items-center justify-end gap-3 py-4 text-xs text-muted-foreground"><Button variant="outline" disabled={cursors.length === 1 || page === null || error !== null}
      onClick={() => setCursors(values => values.slice(0, -1))}>{t("previous")}</Button>
      <span>{t("page", { page: formatNumber(cursors.length) })}</span><Button variant="outline" disabled={!page?.next_cursor || error !== null}
        onClick={() => { if (page?.next_cursor) setCursors(values => [...values, page.next_cursor]); }}>{t("next")}</Button></nav>
  </>;
}
