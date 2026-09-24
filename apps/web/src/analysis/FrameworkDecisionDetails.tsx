import { PortfolioDrawdownFacts, type PortfolioDrawdownObservation } from "./PortfolioDrawdownFacts";
import { TakeProfitFacts, type TakeProfitObservation } from "./TakeProfitFacts";
import Decimal from "decimal.js";
import { useTranslation } from "../i18n";
import { formatNumber } from "../i18n/format";
import type { FrameworkStage } from "../research/frameworkModules";

type Proposal = {
  reason: string;
  allocation: { mode: "rebalance" | "reduce" | "increase"; instrument_ids: string[];
    relative_weights: Record<string, string>; exposure: number; retained_instrument_ids?: string[] } | null;
  position_limits: Record<string, number>; maximum_stock_exposure?: number;
};
type Signal = { instrument_id: string; value: number; created_session: string;
  created_session_number: number; valid_for_sessions: number };
export type FrameworkRecord = {
  decision_session: string;
  modules: Record<string, string>;
  universe: { instrument_ids: string[]; updated: boolean; reason: string | null };
  alpha: { kind: "formula"; values: { instrument_id: string; value: number }[] }
    | { kind: "signals"; signals: Signal[]; updated: boolean; reason: string | null;
      expired_signals: string[]; removed_signals: string[] };
  proposal: Proposal | null;
  portfolio_retentions?: { reason: "minimum_holding_period"; instrument_id: string;
    execution_shares: number; holding_age: number; minimum_holding_sessions: number }[];
  risk_adjustment: { mode: "replace"; reason: string; target: Proposal | null }
    | { mode: "builtin_risk"; reason: string; position_limits: Record<string, number>;
      observations: ({ reason: "stop_loss"; instrument_id: string; remaining_acquisition_cost_cny: string;
        close_market_value_cny: string; holding_return: string; stop_loss_threshold: string;
        execution_shares: number; holding_age: number } | { reason: "maximum_holding_period";
        instrument_id: string; execution_shares: number; holding_age: number;
        maximum_holding_sessions: number } | TakeProfitObservation | PortfolioDrawdownObservation)[] }
    | { mode: "limit_positions"; reason: string; position_limits: Record<string, number> } | null;
  target_id: string | null;
};
const stock = (id: string) => id.replace(/^equity:/, "");
function Limits({ limits }: { limits: Record<string, number> }) {
  const { t } = useTranslation("strategy");
  return <ul>{Object.entries(limits).map(([id, shares]) => <li key={id}>
    {t("decision.limit", { stock: stock(id), shares: formatNumber(shares) })}
  </li>)}</ul>;
}

function Portfolio({ value }: { value: Proposal }) {
  const { t } = useTranslation("strategy");
  return <>
    <p>{t("decision.reason", { reason: value.reason })}</p>
    {value.allocation && <>
      <p>{t(`decision.${value.allocation.mode}`)} · {t("decision.targetExposure", { percent: (value.allocation.exposure * 100).toFixed(2) })}</p>
      <details><summary>{t("decision.weights", { count: value.allocation.instrument_ids.length })}</summary>
        <ul>{value.allocation.instrument_ids.map(id => <li key={id}>
          {stock(id)}：{value.allocation!.relative_weights[id]}
        </li>)}</ul>
      </details>
      {value.allocation.retained_instrument_ids?.length ? <p>{t("decision.retained", { stocks: value.allocation.retained_instrument_ids.map(stock).join(", ") })}</p> : null}
    </>}
    {value.maximum_stock_exposure !== undefined && <p>{t("decision.cap", { percent: new Decimal(value.maximum_stock_exposure).mul(100).toString() })}</p>}
    {Object.keys(value.position_limits).length > 0 && <Limits limits={value.position_limits} />}
  </>;
}

export function FrameworkDecisionDetails({ row }: { row: FrameworkRecord }) {
  const alpha = row.alpha;
  const risk = row.risk_adjustment;
  const { t } = useTranslation("strategy");
  return <div className="framework-decision-details">
    <p>{t("decision.close", { session: row.decision_session })}</p>
    <section aria-label={t("decision.stages.universe_selection")}><h4>1 · {t("decision.stages.universe_selection")}</h4>
      <p>{t(row.universe.updated ? "decision.universeUpdated" : "decision.universeRetained")}
        {" · " + t("decision.instrumentCount", { count: row.universe.instrument_ids.length })}</p>
      {row.universe.reason && <p>{t("decision.reason", { reason: row.universe.reason })}</p>}
      <details><summary>{t("decision.candidates")}</summary><p className="framework-instruments">
        {row.universe.instrument_ids.map(stock).join(", ") || t("decision.emptyCandidates")}
      </p></details>
    </section>
    <section aria-label={t("decision.stages.alpha")}><h4>2 · {t(alpha.kind === "formula" ? "decision.alphaValues" : "decision.strategySignals")}</h4>
      {alpha.kind === "formula" ? <>
        <p>{t("decision.formulaValues", { count: alpha.values.length })}</p>
        <details><summary>{t("decision.viewAlpha")}</summary><ul>{alpha.values.map(item =>
          <li key={item.instrument_id}>{stock(item.instrument_id)}: {item.value}</li>)}</ul></details>
      </> : <>
        <p>{t(alpha.updated ? "decision.signalsUpdated" : "decision.signalsRetained")}
          {" · " + t("decision.signalCount", { count: alpha.signals.length })}</p>
        {alpha.reason && <p>{t("decision.reason", { reason: alpha.reason })}</p>}
        {alpha.expired_signals.length > 0 && <p>{t("decision.expired", { stocks: alpha.expired_signals.map(stock).join(", ") })}</p>}
        {alpha.removed_signals.length > 0 && <p>{t("decision.removed", { stocks: alpha.removed_signals.map(stock).join(", ") })}</p>}
        <p>{t("decision.signalsHelp")}</p>
        {alpha.signals.length > 0 && <details><summary>{t("decision.signalValidity")}</summary><ul>{alpha.signals.map(item =>
          <li key={item.instrument_id}>{t("decision.signalRow", { stock: stock(item.instrument_id), value: item.value, session: item.created_session, count: item.valid_for_sessions })}</li>)}</ul></details>}
      </>}
    </section>
    <section aria-label={t("decision.stages.portfolio_construction")}><h4>3 · {t("decision.stages.portfolio_construction")}</h4>
      {row.proposal ? <Portfolio value={row.proposal} /> : <p>{t("decision.noProposal")}</p>}
      {row.portfolio_retentions?.length ? <ul aria-label={t("decision.retentionReasons")}>{row.portfolio_retentions.map(item => <li key={item.instrument_id}>
        {t("decision.retentionRow", { stock: stock(item.instrument_id), age: item.holding_age, minimum: item.minimum_holding_sessions, shares: item.execution_shares })}
      </li>)}</ul> : null}
    </section>
    <section aria-label={t("decision.stages.risk_management")}><h4>4 · {t("decision.stages.risk_management")}</h4>
      {!risk ? <p>{t("decision.noRisk")}</p> : <>
        <p>{t("decision.reason", { reason: risk.reason })}</p>
        {risk.mode !== "replace" ? <><p>{t("decision.limitHelp")}</p>
          <Limits limits={risk.position_limits} />
          {risk.mode === "builtin_risk" && <ul aria-label={t("decision.riskReasons")}>{risk.observations.map(item => <li key={item.reason === "portfolio_drawdown" ? item.reason : `${item.instrument_id}:${item.reason}`}>
            {item.reason === "portfolio_drawdown" ? <PortfolioDrawdownFacts item={item} /> : <>
            <strong>{stock(item.instrument_id)}</strong>
            {item.reason === "take_profit" ? <TakeProfitFacts item={item} /> : <>
            {item.reason === "stop_loss" ? <>
              <p>{t("decision.stopLossValues", { cost: new Decimal(item.remaining_acquisition_cost_cny).toString(), value: new Decimal(item.close_market_value_cny).toString() })}</p>
              <p>{t("decision.stopLossThreshold", { return: new Decimal(item.holding_return).mul(100).toString(), threshold: new Decimal(item.stop_loss_threshold).mul(100).toString() })}</p>
            </> : <p>{t("decision.maximumReached", { count: item.maximum_holding_sessions })}</p>}
            <p>{t("decision.positionAtDecision", { shares: item.execution_shares, age: item.holding_age })}</p>
            </>}
            </>}
          </li>)}</ul>}</>
          : risk.target ? <><p>{t("decision.replaced")}</p><Portfolio value={risk.target} /></>
            : <p>{t("decision.cancelled")}</p>}
      </>}
    </section>
    <p>{t(row.target_id ? "decision.targetFormed" : "decision.noTarget")}</p>
    <details><summary>{t("decision.identities")}</summary><dl>{Object.entries(row.modules).map(([stage, identity]) =>
      <div key={stage}><dt>{t(`decision.stages.${stage as FrameworkStage}`)}</dt><dd>{identity}</dd></div>)}</dl></details>
  </div>;
}
