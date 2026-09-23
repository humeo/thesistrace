import Decimal from "decimal.js";

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
  return <details className="strategy-execution-notes">
    <summary>Close risk and holdings</summary>
    <p>{session} · Close Risk NAV (CNY): <strong>{new Decimal(nav).toString()}</strong></p>
    <p>Uses closing prices for risk decisions. Performance charts and returns use post-Open NAV.</p>
    {positions.length === 0 ? <p>No actual holdings.</p> : <ul>{positions.map(position => <li key={position.instrument_id}>
      <strong>{position.instrument_id.replace(/^equity:/, "")}</strong>
      <dl>
        <div><dt>Remaining acquisition cost (CNY)</dt><dd>{new Decimal(position.remaining_acquisition_cost_cny).toString()}</dd></div>
        <div><dt>Holding cycle started</dt><dd>{position.holding_cycle_started_session}</dd></div>
        <div><dt>Holding age (trading sessions)</dt><dd>{position.holding_age}</dd></div>
        <div><dt>Actual shares</dt><dd>{position.execution_shares}</dd></div>
        <div><dt>Adjusted Close</dt><dd>{new Decimal(position.last_close_adjusted_price).toString()}</dd></div>
      </dl>
    </li>)}</ul>}
  </details>;
}
