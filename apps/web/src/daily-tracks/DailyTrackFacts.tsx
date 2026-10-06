import { useTranslation } from "react-i18next";
import { formatCurrency, formatNumber, formatUtcTimestamp } from "../i18n/format";
import { Button } from "../components/ui/button";
import { Section } from "../components/layout/Page";
import { followCoreLink } from "../shell/navigation";
import type { DailyTrackDetail } from "./DailyTracksPage";

export function TrackingProgressView({
  progress,
}: {
  progress: DailyTrackDetail["progress"];
}) {
  const { t } = useTranslation("daily");
  return (
    <>
      <p><strong>{t("advancePhase")} </strong> {t(`phases.${progress.phase}`)}</p>
      {progress.target_start_session && progress.target_end_session ? (
        <p>
          <strong>{t("frozenTarget")} </strong>{" "}
          {t("targetRange", { start: progress.target_start_session, end: progress.target_end_session, count: progress.target_session_count })}
        </p>
      ) : null}
      {progress.current_session ? (
        <p><strong>{t("currentSession")} </strong> {progress.current_session}</p>
      ) : null}
      {progress.cycle_attempt ? (
        <p><strong>{t("attemptCycle")} </strong> {formatNumber(progress.cycle_attempt)}/{formatNumber(progress.cycle_attempt_limit)}</p>
      ) : null}
      {progress.retry_wait && progress.next_attempt_eligible_at ? (
        <p><strong>{t("retryEligible")} </strong> {formatUtcTimestamp(progress.next_attempt_eligible_at, true)}</p>
      ) : null}
    </>
  );
}

export function TrackingOriginView({ origin }: { origin: DailyTrackDetail["origin"] }) {
  const { t } = useTranslation("daily");
  return (
    <Section title={t("origin")}><p className="m-0 text-sm text-muted-foreground">{t("immutableAccount")}</p>
      <div className="grid gap-4 text-sm [overflow-wrap:anywhere] sm:grid-cols-2 [&_p]:m-0">
        <p>
          <strong>{t("seed")} </strong>{" "}
          {origin.seed_research_available ? (
            <Button variant="link" nativeButton={false} role="link" render={<a href={`/research-runs/${origin.seed_run_id}`} onClick={followCoreLink} />} className="h-auto min-h-11 max-w-full whitespace-normal p-0 text-left [overflow-wrap:anywhere]">{origin.seed_run_id}</Button>
          ) : (
            <span>{origin.seed_run_id}{t("deleted")}</span>
          )}
        </p>
        <p><strong>{t("originSession")} </strong> {origin.strategy_session}</p>
        <p>{t("originDescription")} </p>
        <p>
          <strong>{t("originNav")} </strong>{" "}
          <span title={origin.terminal_account.net_nav}>
            {formatCnyDecimal(origin.terminal_account.net_nav)}
          </span>
        </p>
        <p>
          <strong>{t("originCash")} </strong>{" "}
          <span title={origin.terminal_account.net_cash}>
            {formatCnyDecimal(origin.terminal_account.net_cash)}
          </span>
        </p>
        <p><strong>{t("originHoldings")} </strong> {formatNumber(origin.terminal_account.positions.length)}</p>
        <p><strong>{t("checksum")} </strong> {origin.result_checksum_sha256}</p>
      </div>
    </Section>
  );
}

function formatCnyDecimal(value: string): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  return formatCurrency(numeric);
}
