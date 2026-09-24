import Decimal from "decimal.js";
import { useTranslation } from "../i18n";

export type TakeProfitObservation = {
  reason: "take_profit"; instrument_id: string; cycle_ended: boolean;
  holding_return: string | null; profit_threshold: string; cumulative_reduction: string;
  baseline_execution_shares: number; baseline_adjusted_units: string; target_adjusted_units: string;
  executed_reduction_units: string; remaining_reduction_units: string;
  execution_shares: number; position_limit: number | null;
};
const number = (value: string) => new Decimal(value).toString();
const percent = (value: string) => new Decimal(value).mul(100).toString();

export function TakeProfitFacts({ item }: { item: TakeProfitObservation }) {
  const { t } = useTranslation("strategy");
  return <>
    <p>{t("takeProfitFacts.threshold", { threshold: percent(item.profit_threshold), reduction: percent(item.cumulative_reduction) })}
      {item.holding_return !== null && t("takeProfitFacts.return", { return: percent(item.holding_return) })}</p>
    <p>{t("takeProfitFacts.baseline", { shares: item.baseline_execution_shares, units: number(item.baseline_adjusted_units), target: number(item.target_adjusted_units) })}</p>
    <p>{t("takeProfitFacts.executed", { sold: number(item.executed_reduction_units), remaining: number(item.remaining_reduction_units) })}</p>
    <p>{item.cycle_ended ? t("takeProfitFacts.ended") : t("takeProfitFacts.active", { shares: item.execution_shares })}</p>
  </>;
}
