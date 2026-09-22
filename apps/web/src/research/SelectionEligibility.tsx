export type SelectionEligibility = {
  signal_session: string;
  eligibility_exclusions: Partial<Record<"zero_volatility" | "insufficient_history" | "unavailable_return", number>>;
};

const reasons = ["zero_volatility", "insufficient_history", "unavailable_return"] as const;

export function SelectionEligibilityView({ selection }: { selection: SelectionEligibility }) {
  const { t } = useTranslation("research");
  const counts = selection.eligibility_exclusions;
  return <div aria-label={t("eligibility")}>
    <p>{t("eligibilityAt", { date: selection.signal_session })}</p>
    {Object.keys(counts).length === 0
      ? <p>{t("noExclusions")}</p>
      : <ul>{reasons.filter(reason => counts[reason] !== undefined)
        .map(reason => <li key={reason}>{t(`exclusions.${reason}`)}: {counts[reason]}</li>)}</ul>}
  </div>;
}
import { useTranslation } from "../i18n";
