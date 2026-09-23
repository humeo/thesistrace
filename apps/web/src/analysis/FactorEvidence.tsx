import { i18n, useTranslation } from "../i18n";
import { formatDecimal, formatNumber, formatPercent } from "../i18n/format";
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
function reasonLabel(reason: string) {
  const labels = i18n.t("analysis:factor.reasons", { returnObjects: true });
  return labels[reason as keyof typeof labels] ?? i18n.t("analysis:unknownReason");
}
const number = (value: number | null) => formatDecimal(value, 3, "dash");
const percent = (value: number | null) => formatPercent(value, { missing: "dash" });
function Exclusions({ values }: { values: Record<string, number> }) {
  useTranslation("analysis");
  return <>{Object.entries(values).map(([reason, count]) =>
    <span className="factor-exclusion" key={reason}>{reasonLabel(reason)}: {formatNumber(count)}</span>)}</>;
}
function SampleCoverage({ value }: { value: Coverage }) {
  const { t } = useTranslation("analysis");
  return <><p>{t("factor.samples", { candidates: formatNumber(value.alpha_candidate_count), signals: formatNumber(value.alpha_sample_count), labels: formatNumber(value.sample_count) })}</p>
    <Exclusions values={value.alpha_exclusions} /><Exclusions values={value.label_exclusions} /></>;
}

export function FactorEvidence({ runId }: { runId: string }) {
  const { t } = useTranslation("analysis");
  const [open, setOpen] = useState(false);
  const [filters, setFilters] = useState<Filters>({ horizon: "5", view: "month", start: "", end: "" });
  const id = useId();
  return <details className="factor-evidence" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{t("factor.title")}</summary>
    {open && <div className="factor-evidence-content">
      <p>{t("factor.explanation")}</p>
      <div className="factor-evidence-controls">
        <label htmlFor={`${id}-horizon`}>{t("factor.horizon")}<select id={`${id}-horizon`} value={filters.horizon}
          onChange={event => setFilters({ ...filters, horizon: event.target.value })}>
          {[1, 5, 20].map(h => <option value={h} key={h}>{t("factor.sessions", { count: h })}</option>)}
        </select></label>
        <label htmlFor={`${id}-view`}>{t("factor.view")}<select id={`${id}-view`} value={filters.view}
          onChange={event => setFilters({ ...filters, view: event.target.value as Filters["view"] })}>
          <option value="daily">{t("factor.daily")}</option><option value="month">{t("factor.month")}</option>
          <option value="year">{t("factor.year")}</option><option value="all">{t("factor.all")}</option>
        </select></label>
        {filters.view === "daily" && <>
          <label htmlFor={`${id}-start`}>{t("factor.from")}<input id={`${id}-start`} type="date" value={filters.start}
            onChange={event => setFilters({ ...filters, start: event.target.value })} /></label>
          <label htmlFor={`${id}-end`}>{t("factor.through")}<input id={`${id}-end`} type="date" value={filters.end}
            onChange={event => setFilters({ ...filters, end: event.target.value })} /></label>
        </>}
      </div>
      {filters.view !== "daily" && <p>{t("factor.grouping")}</p>}
      <EvidencePage key={`${runId}:${JSON.stringify(filters)}`} runId={runId} filters={filters} />
    </div>}
  </details>;
}

function EvidencePage({ runId, filters }: { runId: string; filters: Filters }) {
  const { t } = useTranslation("analysis");
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<"cursor" | "load" | null>(null);
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
        if (!response.ok) { if (!controller.signal.aborted) setError(response.status === 400 ? "cursor" : "load"); return; }
        const result = await response.json() as Page;
        if (!controller.signal.aborted) setPage(result);
      }).catch(() => {
        if (!controller.signal.aborted) setError("load");
      });
    return () => controller.abort();
  }, [runId, filters, cursor, retry, invalidRange]);
  if (invalidRange) return <p role="alert">{t("factor.invalidRange")}</p>;
  return <>
    {error ? <div role="alert"><p>{t(error === "cursor" ? "factor.cursorError" : "factor.loadError")}</p><button type="button" onClick={() => { setCursors([null]); setRetry(value => value + 1); }}>{t("reloadFirst")}</button></div>
      : page === null ? <p role="status">{t("factor.loading")}</p>
      : page.items.length === 0 ? <p>{t("factor.empty")}</p>
      : <div className="factor-evidence-table"><table>
        <caption>{page.section === "factor_observations" ? t("factor.dailyCaption") : t("factor.periodCaption")}</caption>
        <thead><tr><th>{page.section === "factor_observations" ? t("factor.signalDate") : t("factor.period")}</th><th>IC</th><th>Rank IC</th>
          {page.section === "factor_periods" && <><th>ICIR</th><th>Rank ICIR</th></>}
          {groups.map(group => <th key={group}>{group.toUpperCase()}</th>)}<th>Q5 − Q1</th><th>{t("factor.evidence")}</th></tr></thead>
        <tbody>{page.section === "factor_observations" ? page.items.map(row => <tr key={row.session}>
          <td>{row.session}</td><td>{number(row.ic)}</td><td>{number(row.rank_ic)}</td>
          {groups.map(group => <td key={group}>{percent(row.quantile_returns[group])}<small>n={row.quantile_counts[group] === null ? "—" : formatNumber(row.quantile_counts[group])}</small></td>)}
          <td>{percent(row.top_bottom_return)}</td><td><details><summary>{t("factor.coverage")}</summary>
            <SampleCoverage value={row} />
            <p>{t("factor.open", { start: row.label_entry_session ?? "—", end: row.label_exit_session ?? "—" })}</p>
            {row.label_status === "right_censored_by_research_period_end" && <p>{t("factor.reasons.right_censored_by_research_period_end")}</p>}
            {row.correlation_reason && <p>{reasonLabel(row.correlation_reason)}</p>}
          </details></td></tr>) : page.items.map(row => <tr key={row.period}>
          <td>{row.period}</td><td>{number(row.summary.ic.mean)}</td><td>{number(row.summary.rank_ic.mean)}</td>
          <td>{number(row.summary.ic.icir)}</td><td>{number(row.summary.rank_ic.icir)}</td>
          {groups.map(group => <td key={group}>{percent(row.summary.quantile_returns[group])}</td>)}
          <td>{percent(row.summary.top_bottom_return)}</td><td><details><summary>{t("factor.coverageCount", { valid: formatNumber(row.coverage.label_evaluable_session_count), total: formatNumber(row.coverage.signal_session_count) })}</summary>
            <p>{t("factor.signals", { start: row.coverage.first_signal_session, end: row.coverage.last_signal_session })}</p>
            <p>{t("factor.evaluable", { start: row.coverage.first_evaluable_signal_session ?? "—", end: row.coverage.last_evaluable_signal_session ?? "—" })}</p>
            <p>{t("factor.validDays", { ic: formatNumber(row.coverage.ic_valid_session_count), rankIc: formatNumber(row.coverage.rank_ic_valid_session_count), tail: formatNumber(row.coverage.right_censored_session_count) })}</p>
            <SampleCoverage value={row.coverage} />
          </details></td></tr>)}</tbody>
      </table></div>}
    <nav aria-label={t("factor.pages")}><button type="button" disabled={cursors.length === 1 || page === null || error !== null}
      onClick={() => setCursors(values => values.slice(0, -1))}>{t("previous")}</button>
      <span>{t("page", { page: formatNumber(cursors.length) })}</span><button type="button" disabled={!page?.next_cursor || error !== null}
        onClick={() => { if (page?.next_cursor) setCursors(values => [...values, page.next_cursor]); }}>{t("next")}</button></nav>
  </>;
}
