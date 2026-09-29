import { Disclosure } from "../components/layout/Disclosure";
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

export function CloseRiskFacts({ session, nav, positions, variant }: {
  session: string; nav: string; positions: CloseRiskPosition[];
  variant?: "panel" | "row";
}) {
  const { t } = useTranslation("strategy");
  return <Disclosure variant={variant} title={t("closeRisk.title")}>
    <p>{t("closeRisk.nav", { session })} <strong>{new Decimal(nav).toString()}</strong></p>
    <p>{t("closeRisk.help")}</p>
    {positions.length === 0 ? <p>{t("closeRisk.empty")}</p> : <ul>{positions.map(position => <li key={position.instrument_id}>
      <strong>{position.instrument_id.replace(/^equity:/, "")}</strong>
      <dl className="grid gap-3 sm:grid-cols-2 [&_dd]:m-0 [&_dd]:font-mono [&_dt]:text-muted-foreground">
        <div><dt>{t("closeRisk.acquisition")}</dt><dd>{new Decimal(position.remaining_acquisition_cost_cny).toString()}</dd></div>
        <div><dt>{t("closeRisk.started")}</dt><dd>{position.holding_cycle_started_session}</dd></div>
        <div><dt>{t("closeRisk.age")}</dt><dd>{position.holding_age}</dd></div>
        <div><dt>{t("closeRisk.shares")}</dt><dd>{position.execution_shares}</dd></div>
        <div><dt>{t("closeRisk.adjustedClose")}</dt><dd>{new Decimal(position.last_close_adjusted_price).toString()}</dd></div>
      </dl>
    </li>)}</ul>}
  </Disclosure>;
}
