import Decimal from "decimal.js";
import { useTranslation } from "../i18n";

export type CloseRiskPosition = {
  instrument_id: string;
  execution_shares: number;
  remaining_acquisition_cost_cny: string;
  holding_cycle_started_session: string;
  holding_age: number;
  adjusted_units: string;
  last_close_adjusted_price: string;
};

export function CloseRiskFacts({ session, nav, positions }: {
  session: string; nav: string; positions: CloseRiskPosition[];
}) {
  const { t } = useTranslation("strategy");
  return <details className="strategy-execution-notes">
    <summary>{t("closeRisk.title")}</summary>
    <p>{t("closeRisk.nav", { session })} <strong>{new Decimal(nav).toString()}</strong></p>
    <p>{t("closeRisk.help")}</p>
    {positions.length === 0 ? <p>{t("closeRisk.empty")}</p> : <ul>{positions.map(position => <li key={position.instrument_id}>
      <strong>{position.instrument_id.replace(/^equity:/, "")}</strong>
      <dl>
        <div><dt>{t("closeRisk.acquisition")}</dt><dd>{new Decimal(position.remaining_acquisition_cost_cny).toString()}</dd></div>
        <div><dt>{t("closeRisk.started")}</dt><dd>{position.holding_cycle_started_session}</dd></div>
        <div><dt>{t("closeRisk.age")}</dt><dd>{position.holding_age}</dd></div>
        <div><dt>{t("closeRisk.shares")}</dt><dd>{position.execution_shares}</dd></div>
        <div><dt>{t("closeRisk.adjustedClose")}</dt><dd>{new Decimal(position.last_close_adjusted_price).toString()}</dd></div>
      </dl>
    </li>)}</ul>}
  </details>;
}
