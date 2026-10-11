import { useTranslation } from "react-i18next";
import { CaretDown, CheckCircle, WarningCircle } from "@phosphor-icons/react";
import { Button } from "../components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../components/ui/collapsible";
import type { BulkRefreshItem } from "./refreshAll";

export function BulkRefreshFeedback({ items }: { items: readonly BulkRefreshItem[] }) {
  const { t } = useTranslation("daily");
  const queued = items.filter(item => item.outcome === "queued").length;
  const failed = items.filter(item => item.outcome === "failed").length;
  return <Collapsible defaultOpen={failed > 0} role="status" className="rounded-lg border border-border bg-card px-4 py-2">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="m-0 flex items-center gap-2 text-sm text-muted-foreground">
        {failed ? <WarningCircle aria-hidden="true" className="size-4 shrink-0 text-destructive" /> : <CheckCircle aria-hidden="true" className="size-4 shrink-0" />}
        {t("bulkSummary", { queued, skipped: items.length - queued - failed, failed })}
      </p>
      <CollapsibleTrigger render={<Button variant="ghost" size="sm" />}>
        {t("bulkDetails")}<CaretDown aria-hidden="true" />
      </CollapsibleTrigger>
    </div>
    <CollapsibleContent className="grid gap-3 pt-3 pb-2">
      {queued > 0 && <p className="m-0 text-sm text-muted-foreground">{t("bulkAccepted")}</p>}
      {items.some(item => item.outcome !== "queued") && <ul className="m-0 grid gap-2 pl-4 text-sm text-muted-foreground">
        {items.map(item => item.outcome === "queued" ? null : <li key={item.id} className={item.outcome === "failed" ? "text-destructive" : undefined}>
          {item.name ?? `${t("trackHeading")} ${item.id.replace(/^track_/, "").slice(0, 6)}`} · {t(`bulkOutcomes.${item.outcome}`)}
        </li>)}
      </ul>}
    </CollapsibleContent>
  </Collapsible>;
}
