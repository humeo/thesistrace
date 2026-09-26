import { i18n, useTranslation } from "../i18n";
import { formatNumber, formatPercent, formatTimestamp } from "../i18n/format";
import { useEffect, useId, useRef, useState } from "react";
import { CurrentDataRerun, type RerunSource } from "./CurrentDataRerun";
import { coreFetch } from "../auth/coreFetch";
import { Button } from "../components/ui/button";
import { Alert, AlertDescription } from "../components/ui/alert";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../components/ui/collapsible";
import { Empty, EmptyDescription } from "../components/ui/empty";
import { Field, FieldError, FieldGroup, FieldLabel } from "../components/ui/field";
import { Input } from "../components/ui/input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { ResearchDateInput } from "../research/ResearchDateInput";
import { isResearchIsoDate } from "../research/dateRange";

type Unit = { unit_id: string; source_kind: string; first_session: string; last_session: string; expires_at: string; status: "available" | "expired" };
type StatusPage = { status: "recorded" | "not_recorded"; units: Unit[]; next_cursor: string | null };
type Row = { session: string; instrument_id: string; execution_shares: number; adjusted_units: string; adjusted_mark: string; market_value_cny: string; weight: number };
type Details = { status: "available" | "expired" | "not_recorded"; unit: Unit | null; rows: Row[]; coverage: { session_count: number } | null; next_cursor: string | null };
type FieldError = "invalidRange" | "invalidValue" | "invalidDate" | "invalidInstrument";
type Filters = { start_session?: string; end_session?: string; instrument_id?: string };

export function DailyHoldings({ endpoint, rerun, embedded = false }: {
  endpoint: string;
  embedded?: boolean;
  rerun?: { folderId: string; source: RerunSource };
}) {
  const { t } = useTranslation("analysis");
  const [open, setOpen] = useState(embedded);
  const id = useId();
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
  useEffect(() => { if (embedded) loadPeriods(); }, [embedded, endpoint]);
  const selectedUnit = details?.unit ?? status?.units.find(unit => unit.unit_id === unitId);
  const content = <div className="flex min-w-0 flex-col gap-4">
    <p className="m-0 text-muted-foreground">{t("holdings.explanation")}</p>
    <Button variant="outline" className="self-start" disabled={busy} onClick={() => loadPeriods()}>{t("holdings.check")}</Button>
    {status?.status === "not_recorded" && <Empty><EmptyDescription>{t("holdings.notRecordedResult")}</EmptyDescription></Empty>}
    {status && status.units.length > 0 && <>
      <Field className="max-w-xl">
        <FieldLabel htmlFor={`${id}-period`}>{t("holdings.period")}</FieldLabel>
        <Select value={unitId} disabled={busy} onValueChange={value => {
          if (value === null) return;
          setUnitId(value); setDetails(null);
        }} items={status.units.map(unit => ({ value: unit.unit_id, label: `${unit.first_session} – ${unit.last_session} · ${unit.source_kind === "research_run" ? t("holdings.backtest") : t("holdings.tracking")}${unit.status === "expired" ? ` · ${t("holdings.expired")}` : ""}` }))}>
          <SelectTrigger id={`${id}-period`} className="w-full"><SelectValue /></SelectTrigger>
          <SelectContent><SelectGroup>{status.units.map(unit => <SelectItem key={unit.unit_id} value={unit.unit_id}>
            {unit.first_session} – {unit.last_session} · {unit.source_kind === "research_run" ? t("holdings.backtest") : t("holdings.tracking")}{unit.status === "expired" ? ` · ${t("holdings.expired")}` : ""}
          </SelectItem>)}</SelectGroup></SelectContent>
        </Select>
      </Field>
      {status.next_cursor && <Button variant="outline" className="self-start" disabled={busy} onClick={() => loadPeriods(status.next_cursor)}>{t("holdings.more")}</Button>}
      {selectedUnit && <p className="m-0 text-muted-foreground">{selectedUnit.status === "expired" ? t("holdings.expired") : t("holdings.until")}: <time>{formatTimestamp(selectedUnit.expires_at, { year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" })}</time></p>}
      <form onSubmit={event => {
        event.preventDefault();
        const errors: Record<string, FieldError> = {};
        for (const key of ["start_session", "end_session"] as const) {
          if (draft[key] && !isResearchIsoDate(draft[key])) errors[key] = "invalidDate";
        }
        if (!Object.keys(errors).length && draft.start_session && draft.end_session && draft.start_session > draft.end_session) errors.end_session = "invalidRange";
        setFieldErrors(errors);
        if (Object.keys(errors).length) return;
        const next = Object.fromEntries(Object.entries(draft).filter(([, value]) => value !== "")) as Filters;
        setFilters(next); loadDetails(null, next);
      }}>
        <FieldGroup className="grid items-end gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {(["start_session", "end_session"] as const).map(key => <ResearchDateInput key={key}
            id={`${id}-${key}`} label={t(key === "start_session" ? "holdings.from" : "holdings.through")}
            openLabel={i18n.t(key === "start_session" ? "research:openStartCalendar" : "research:openEndCalendar")}
            value={draft[key]} onChange={value => setDraft({ ...draft, [key]: value })}
            minimum={key === "end_session" ? draft.start_session || null : null}
            maximum={key === "start_session" ? draft.end_session || null : null}
            error={fieldErrors[key] ? t(`holdings.${fieldErrors[key]}`) : undefined} errorId={`${id}-${key}-error`} />)}
          <Field data-invalid={!!fieldErrors.instrument_id}>
            <FieldLabel htmlFor={`${id}-instrument`}>{t("holdings.instrument")}</FieldLabel>
            <Input id={`${id}-instrument`} value={draft.instrument_id} placeholder="equity:600001.SH" onChange={event => setDraft({ ...draft, instrument_id: event.target.value })} aria-invalid={!!fieldErrors.instrument_id} aria-describedby={fieldErrors.instrument_id ? `${id}-instrument-error` : undefined} />
            {fieldErrors.instrument_id && <FieldError id={`${id}-instrument-error`}>{t(`holdings.${fieldErrors.instrument_id}`)}</FieldError>}
          </Field>
          <Button type="submit" disabled={busy || !unitId}>{t("holdings.load")}</Button>
        </FieldGroup>
      </form>
    </>}
    {busy && <p role="status">{t("loading")}</p>}
    {error && <Alert variant="destructive"><AlertDescription>{t(`holdings.${error}`)}</AlertDescription></Alert>}
    {details?.status === "expired" && <Alert role="status"><AlertDescription>{t("holdings.expiredDetails")}</AlertDescription></Alert>}
    {rerun && selectedUnit?.status === "expired" && <CurrentDataRerun
      key={`${unitId}:${JSON.stringify(rerun.source)}`} folderId={rerun.folderId}
      source={rerun.source.kind === "daily_track" ? { ...rerun.source, through_session: selectedUnit.last_session } : rerun.source} />}
    {details?.status === "not_recorded" && <Empty><EmptyDescription>{t("holdings.notRecordedPeriod")}</EmptyDescription></Empty>}
    {details?.status === "available" && <>
      <p>{t("holdings.coverage", { count: details.coverage?.session_count ?? 0 })}</p>
      {details.rows.length === 0 ? <Empty><EmptyDescription>{details.next_cursor ? t("holdings.emptyMore") : t("holdings.empty")}</EmptyDescription></Empty> : <div className="min-w-0">
        <Table scrollLabel={t("holdings.rows")} className="tabular-nums [&_th:nth-child(n+3)]:text-right [&_td:nth-child(n+3)]:text-right"><TableHeader><TableRow>
          {(["session", "instrument", "shares", "units", "mark", "value", "weight"] as const).map(key => <TableHead key={key}>{t(`holdings.${key}`)}</TableHead>)}
        </TableRow></TableHeader><TableBody>{details.rows.map(row => <TableRow key={`${row.session}:${row.instrument_id}`}>
          <TableCell>{row.session}</TableCell><TableCell>{row.instrument_id}</TableCell><TableCell>{formatNumber(row.execution_shares)}</TableCell><TableCell>{row.adjusted_units}</TableCell><TableCell>{row.adjusted_mark}</TableCell><TableCell>{row.market_value_cny}</TableCell><TableCell>{formatPercent(row.weight)}</TableCell>
        </TableRow>)}</TableBody></Table>
      </div>}
      {details.next_cursor && <Button variant="outline" className="self-start" disabled={busy} onClick={() => loadDetails(details.next_cursor, filters)}>{t("holdings.next")}</Button>}
    </>}
  </div>;
  if (embedded) return <section aria-label={t("holdings.title")} className="min-w-0">{content}</section>;
  return <Collapsible open={open} onOpenChange={next => {
    setOpen(next);
    if (next && !status) loadPeriods();
  }} className="min-w-0">
    <CollapsibleTrigger render={<Button variant="outline" />}>{t("holdings.title")}</CollapsibleTrigger>
    <CollapsibleContent keepMounted className="pt-4">{content}</CollapsibleContent>
  </Collapsible>;
}
