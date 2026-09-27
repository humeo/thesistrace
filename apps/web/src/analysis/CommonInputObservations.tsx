import { useTranslation } from "../i18n";
import { formatNumber, formatPercent } from "../i18n/format";
import { useEffect, useState } from "react";
import { coreFetch } from "../auth/coreFetch";
import { Button } from "../components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../components/ui/collapsible";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";

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

export function CommonInputObservations({ endpoint, embedded = false }: { endpoint: string; embedded?: boolean }) {
  const { t } = useTranslation("analysis");
  const reasons = t("commonInputs.reasons", { returnObjects: true });
  const [open, setOpen] = useState(embedded);
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
  const content = <div className="[&>p]:max-w-[90ch] [&>p]:text-[13px] [&>p]:leading-[1.6] [&>p]:text-muted-foreground">
      <p>{t("commonInputs.universe")}</p>
      <p>{t("commonInputs.returns")}</p>
      {error ? <div role="alert"><p>{t(error === "cursor" ? "commonInputs.cursorError" : "commonInputs.loadError")}</p><Button variant="outline" onClick={() => {
        setCursors([null]); setRetry(value => value + 1);
      }}>{t("reloadFirst")}</Button></div> : page === null ? <p role="status">{t("commonInputs.loading")}</p>
        : page.items.length === 0 ? <p>{t("commonInputs.empty")}</p>
        : <div className="max-w-full [&_[data-slot=table-head]]:px-3 [&_[data-slot=table-head]]:py-2.5 [&_[data-slot=table-cell]]:px-3 [&_[data-slot=table-cell]]:py-2.5 [&_[data-slot=table-head]]:align-top [&_[data-slot=table-cell]]:align-top [&_[data-slot=table-cell]:first-child]:tabular-nums [&_[data-slot=table-cell]:nth-child(4)]:tabular-nums [&_[data-slot=table-cell]:nth-child(5)]:tabular-nums [&_[data-slot=table-cell]:last-child]:min-w-[180px] [&_[data-slot=table-cell]:last-child]:whitespace-normal"><Table scrollLabel={t("commonInputs.title")}>
          <TableHeader><TableRow><TableHead>{t("commonInputs.date")}</TableHead><TableHead>{t("commonInputs.metric")}</TableHead><TableHead>{t("commonInputs.scope")}</TableHead><TableHead>{t("commonInputs.value")}</TableHead><TableHead>{t("commonInputs.valid")}</TableHead><TableHead>{t("commonInputs.excluded")}</TableHead></TableRow></TableHeader>
          <TableBody>{page.items.map(item => <TableRow key={`${item.session}:${item.identifier}:${item.industry_code ?? ""}`}>
            <TableCell>{item.session}</TableCell><TableCell>{item.identifier.endsWith("advancing_fraction") ? t("commonInputs.advancing") : t("commonInputs.equalWeight")}</TableCell>
            <TableCell>{item.industry_code ? t("commonInputs.industry", { code: item.industry_code }) : t("commonInputs.researchUniverse")}</TableCell>
            <TableCell>{formatPercent(item.value, { missing: "dash" })}</TableCell>
            <TableCell>{formatNumber(item.valid_count)} / {formatNumber(item.member_count)}</TableCell>
            <TableCell>{Object.entries(item.exclusions).map(([reason, count]) => `${reasons[reason as keyof typeof reasons] ?? t("unknownReason")}: ${formatNumber(count)}`).join("; ") || t("none")}</TableCell>
          </TableRow>)}</TableBody>
        </Table></div>}
      <nav aria-label={t("commonInputs.pages")} className="flex flex-wrap items-center justify-end gap-3 py-4 text-xs text-muted-foreground">
        <Button variant="outline" disabled={cursors.length === 1 || page === null} onClick={() => setCursors(values => values.slice(0, -1))}>{t("previous")}</Button>
        <span>{t("page", { page: formatNumber(cursors.length) })}</span>
        <Button variant="outline" disabled={!page?.next_cursor} onClick={() => {
          if (page?.next_cursor) setCursors(values => [...values, page.next_cursor]);
        }}>{t("next")}</Button>
      </nav>
    </div>;
  return embedded ? <section aria-label={t("commonInputs.title")} className="min-w-0 data-[slot=collapsible]:border-t data-[slot=collapsible]:border-border">{content}</section>
    : <Collapsible open={open} onOpenChange={setOpen} className="min-w-0 data-[slot=collapsible]:border-t data-[slot=collapsible]:border-border">
      <CollapsibleTrigger render={<Button variant="ghost" className="min-h-11" />}>{t("commonInputs.title")}</CollapsibleTrigger>
      <CollapsibleContent>{open ? content : null}</CollapsibleContent>
    </Collapsible>;
}
