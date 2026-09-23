import { useTranslation } from "../i18n";
import { formatNumber, formatPercent } from "../i18n/format";
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

export function CommonInputObservations({ endpoint }: { endpoint: string }) {
  const { t } = useTranslation("analysis");
  const reasons = t("commonInputs.reasons", { returnObjects: true });
  const [open, setOpen] = useState(false);
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<"cursor" | "load" | null>(null);
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
      if (!response.ok) { if (!controller.signal.aborted) setError(response.status === 400 ? "cursor" : "load"); return; }
      const result = await response.json() as Page;
      if (!controller.signal.aborted) setPage(result);
    }).catch(() => {
      if (!controller.signal.aborted) setError("load");
    });
    return () => controller.abort();
  }, [open, endpoint, cursor, retry]);
  return <details className="common-input-observations" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{t("commonInputs.title")}</summary>
    {open && <div className="common-input-content">
      <p>{t("commonInputs.universe")}</p>
      <p>{t("commonInputs.returns")}</p>
      {error ? <div role="alert"><p>{t(error === "cursor" ? "commonInputs.cursorError" : "commonInputs.loadError")}</p><button type="button" onClick={() => {
        setCursors([null]); setRetry(value => value + 1);
      }}>{t("reloadFirst")}</button></div> : page === null ? <p role="status">{t("commonInputs.loading")}</p>
        : page.items.length === 0 ? <p>{t("commonInputs.empty")}</p>
        : <div className="common-input-table"><table>
          <thead><tr><th>{t("commonInputs.date")}</th><th>{t("commonInputs.metric")}</th><th>{t("commonInputs.scope")}</th><th>{t("commonInputs.value")}</th><th>{t("commonInputs.valid")}</th><th>{t("commonInputs.excluded")}</th></tr></thead>
          <tbody>{page.items.map(item => <tr key={`${item.session}:${item.identifier}:${item.industry_code ?? ""}`}>
            <td>{item.session}</td><td>{item.identifier.endsWith("advancing_fraction") ? t("commonInputs.advancing") : t("commonInputs.equalWeight")}</td>
            <td>{item.industry_code ? t("commonInputs.industry", { code: item.industry_code }) : t("commonInputs.researchUniverse")}</td>
            <td>{formatPercent(item.value, { missing: "dash" })}</td>
            <td>{formatNumber(item.valid_count)} / {formatNumber(item.member_count)}</td>
            <td>{Object.entries(item.exclusions).map(([reason, count]) => `${reasons[reason as keyof typeof reasons] ?? t("unknownReason")}: ${formatNumber(count)}`).join("; ") || t("none")}</td>
          </tr>)}</tbody>
        </table></div>}
      <nav aria-label={t("commonInputs.pages")}>
        <button type="button" disabled={cursors.length === 1 || page === null} onClick={() => setCursors(values => values.slice(0, -1))}>{t("previous")}</button>
        <span>{t("page", { page: formatNumber(cursors.length) })}</span>
        <button type="button" disabled={!page?.next_cursor} onClick={() => {
          if (page?.next_cursor) setCursors(values => [...values, page.next_cursor]);
        }}>{t("next")}</button>
      </nav>
    </div>}
  </details>;
}
