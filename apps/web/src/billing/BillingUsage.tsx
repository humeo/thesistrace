import { Alert, AlertDescription } from "../components/ui/alert";
import { Progress, ProgressLabel, ProgressValue } from "../components/ui/progress";
import { Skeleton } from "../components/ui/skeleton";
import { useTranslation } from "../i18n";
import { formatNumber } from "../i18n/format";
import type { z } from "zod";
import type { coreUsageSchema, modelUsageSchema } from "./client";

export function BillingUsage({
  core,
  model,
  coreFailed,
  modelFailed,
}: {
  core?: z.infer<typeof coreUsageSchema>;
  model?: z.infer<typeof modelUsageSchema>;
  coreFailed: boolean;
  modelFailed: boolean;
}) {
  const { t } = useTranslation("billing");
  const percent = model && model.remaining_nanodollars !== null
    ? Math.floor((model.remaining_nanodollars * 100) / (model.limit_nanodollars || 1))
    : null;
  const remaining = percent === null ? null
    : t("weeklyRemaining", { percent: formatNumber(percent / 100, { style: "percent" }) });

  return (
    <section aria-labelledby="billing-usage-title" className="grid gap-4">
      <h2 id="billing-usage-title" className="m-0 text-xl font-semibold">{t("usage")}</h2>
      {core ? (
        <dl className="m-0 divide-y divide-border border-y border-border">
          <div className="flex min-h-14 items-center justify-between gap-4 text-sm text-muted-foreground">
            <dt>{t("research")}</dt>
            <dd className="m-0 font-medium text-foreground tabular-nums">
              {formatNumber(core.research.actual + core.research.reserved)} / {core.research.limit === null ? t("unlimited") : formatNumber(core.research.limit)}
            </dd>
          </div>
          <div className="flex min-h-14 items-center justify-between gap-4 text-sm text-muted-foreground">
            <dt>{t("tracks")}</dt>
            <dd className="m-0 font-medium text-foreground tabular-nums">
              {formatNumber(core.tracking.selected_track_ids.length)} / {core.tracking.limit === null ? t("unlimited") : formatNumber(core.tracking.limit)}
            </dd>
          </div>
        </dl>
      ) : coreFailed ? <p className="text-sm text-muted-foreground">{t("usageUnavailable")}</p> : <Skeleton className="h-28" />}
      {core?.tracking.selection_required ? (
        <Alert><AlertDescription>{t("selectionRequired")}</AlertDescription></Alert>
      ) : null}
      {percent !== null ? (
        <Progress
          size="lg"
          value={percent}
          getAriaValueText={() => remaining ?? ""}
          className="items-center gap-y-3 [&_[data-slot=progress-indicator]]:rounded-full [&_[data-slot=progress-track]]:h-1 [&_[data-slot=progress-track]]:bg-border"
        >
          <ProgressLabel className="text-sm text-muted-foreground">{t("ai")}</ProgressLabel>
          <ProgressValue className="text-sm font-medium text-foreground">
            {() => remaining}
          </ProgressValue>
        </Progress>
      ) : (
        <div className="flex items-center justify-between gap-4">
          <span>{t("ai")}</span>
          {model ? <span className="text-muted-foreground">{t("unlimited")}</span>
            : modelFailed ? <span className="text-sm text-muted-foreground">{t("usageUnavailable")}</span>
              : <Skeleton className="h-5 w-28" />}
        </div>
      )}
    </section>
  );
}
