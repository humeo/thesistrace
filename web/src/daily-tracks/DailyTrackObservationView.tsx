import { useEffect, useRef, useState } from "react";
import { ColorType, LineSeries, createChart, type Time } from "lightweight-charts";

export type DailyTrackObservation = {
  session: string;
  net_asset_value_cny: string;
  cash_cny: string;
  net_change_cny: string;
  net_return: number;
  maximum_drawdown: number;
  transaction_cost_cny: string;
  session_count: number;
  holdings: Array<{ instrument_id: string; shares: number; market_value_cny: string; weight: number }>;
  rebalance_interval: number;
  pending_signal_session: string | null;
  sessions_until_next_signal: number;
  returns: Array<{ session: string; net_return: number }>;
};

export function formatMoney(value: string | number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency", currency: "CNY", maximumFractionDigits: 2,
  }).format(Number(value));
}

export function formatReturn(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(value);
}

export function ObservationSummary({ observation, originSession }: {
  observation: DailyTrackObservation; originSession: string;
}) {
  return (
    <dl className="track-account-strip" aria-label="Tracking account">
      <div>
        <dt>Return since tracking</dt>
        <dd className={observation.net_return < 0 ? "track-negative" : ""}>
          {formatReturn(observation.net_return)}
        </dd>
        <span>Since {originSession}</span>
      </div>
      <div><dt>Maximum drawdown</dt><dd>{formatReturn(observation.maximum_drawdown)}</dd>
        <span>Since {originSession}</span></div>
      <div><dt>Net account value</dt><dd>{formatMoney(observation.net_asset_value_cny)}</dd>
        <span>{formatMoney(observation.net_change_cny)} since tracking</span></div>
      <div><dt>Available cash</dt><dd>{formatMoney(observation.cash_cny)}</dd>
        <span>Simulated account · CNY</span></div>
      <div><dt>Current holdings</dt><dd>{observation.holdings.length}<small> securities</small></dd>
        <span>As of {observation.session}</span></div>
    </dl>
  );
}

export function CurrentHoldings({ observation }: { observation: DailyTrackObservation }) {
  const [query, setQuery] = useState("");
  const holdings = observation.holdings.filter((item) => item.instrument_id.toLowerCase().includes(query.toLowerCase()));
  return (
    <section className="track-holdings" aria-label="Current holdings">
      <div className="track-section-heading">
        <div><h2>Current holdings</h2><p>Published positions as of {observation.session}.</p></div>
        <input aria-label="Filter holdings by symbol" placeholder="Find a symbol…" type="search"
          value={query} onChange={(event) => setQuery(event.target.value)} />
      </div>
      <div className="track-table-scroll" tabIndex={0} role="region" aria-label="Holdings table">
        <table className="track-table">
          <thead><tr><th scope="col">Symbol</th><th scope="col">Shares</th><th scope="col">Market value</th><th scope="col">Weight</th></tr></thead>
          <tbody>
            {holdings.map((item) => (
              <tr key={item.instrument_id}>
                <th scope="row" title={item.instrument_id}>{item.instrument_id.replace(/^equity:/, "")}</th>
                <td>{item.shares.toLocaleString("en-US")}</td>
                <td>{formatMoney(item.market_value_cny)}</td>
                <td><span className="track-weight"><span aria-hidden="true" className="track-weight-bar"
                  style={{ width: `${Math.min(100, Math.max(0, item.weight * 100))}%` }} />{formatReturn(item.weight)}</span></td>
              </tr>
            ))}
            {holdings.length === 0 ? <tr><td colSpan={4} className="track-table-empty">
              {query ? "No symbols match your search." : "This account currently holds cash only."}
            </td></tr> : null}
          </tbody>
          <tfoot><tr><th scope="row">Cash</th><td>—</td><td>{formatMoney(observation.cash_cny)}</td>
            <td>{formatReturn(Number(observation.cash_cny) / Number(observation.net_asset_value_cny))}</td></tr></tfoot>
        </table>
      </div>
      <p className="track-footnote">Market values include corporate action adjustments. These are simulated positions.</p>
    </section>
  );
}

export function RebalanceSchedule({ observation, isStopped, isBehind }: {
  observation: DailyTrackObservation; isStopped: boolean; isBehind: boolean;
}) {
  return (
    <section className="track-rebalance" aria-label="Rebalance schedule">
      <div className="track-section-heading"><div><h2>Rebalance schedule</h2>
        <p>The strategy keeps the rebalance cycle selected in the original backtest.</p></div></div>
      <dl className="track-schedule-facts">
        <div><dt>Frequency</dt><dd>Every {observation.rebalance_interval} {observation.rebalance_interval === 1 ? "trading session" : "trading sessions"}</dd></div>
        <div><dt>Signal at last observation</dt><dd>{observation.pending_signal_session ?? "No pending signal"}</dd></div>
        <div><dt>Next scheduled step</dt><dd>{isStopped ? "Tracking stopped" : observation.pending_signal_session
          ? "Rebalance at the next trading session open"
          : `Next signal in ${observation.sessions_until_next_signal} trading ${observation.sessions_until_next_signal === 1 ? "session" : "sessions"}`}</dd></div>
      </dl>
      {isBehind && !isStopped ? <p className="track-inline-notice">Tracking is behind the available data. Update the track before using its next signal.</p> : null}
      <div className="track-guidance-empty">
        <h3>Buy and sell instructions are not available yet</h3>
        <p>The current result publishes holdings and the rebalance schedule. It does not publish a target portfolio or an order list for the next session.</p>
      </div>
    </section>
  );
}

export function TrackingReturnChart({ observation, originSession }: {
  observation: DailyTrackObservation; originSession: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<{ session: string; net_return: number } | null>(null);
  useEffect(() => {
    const element = containerRef.current;
    if (!element || observation.returns.length < 2) return;
    setSelected(null);
    const chart = createChart(element, {
      width: element.clientWidth, height: 280,
      layout: { background: { type: ColorType.Solid, color: "#0f1011" }, textColor: "#8a8f98", attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: "#23252a" } },
      rightPriceScale: { borderColor: "#34343a" },
      timeScale: { borderColor: "#34343a", fixLeftEdge: true, fixRightEdge: true },
      localization: { priceFormatter: formatReturn },
    });
    const series = chart.addSeries(LineSeries, { color: "#828fff", lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
    series.setData(observation.returns.map((point) => ({ time: point.session as Time, value: point.net_return })));
    series.createPriceLine({ price: 0, color: "#62666d", lineStyle: 2, lineWidth: 1, axisLabelVisible: false, title: "" });
    chart.timeScale().fitContent();
    chart.subscribeCrosshairMove((event) => {
      setSelected(observation.returns.find((point) => point.session === event.time) ?? null);
    });
    const resize = new ResizeObserver(([entry]) => {
      if (entry) chart.applyOptions({ width: Math.floor(entry.contentRect.width) });
    });
    resize.observe(element);
    return () => { resize.disconnect(); chart.remove(); };
  }, [observation.returns]);
  if (observation.returns.length < 2) {
    return <div className="track-chart-empty">
      <h3>Your daily observations start here</h3>
      <p>Tracking began on {originSession}. The first successful update will add the next observation.</p></div>;
  }
  return <figure className="track-return-chart" aria-label="Return since tracking began">
    <figcaption><span>Net return since {originSession}</span><span>{observation.returns.length} observations</span></figcaption>
    <div ref={containerRef} />
    <div className="track-chart-footer"><span>{selected ? `${selected.session}  ${formatReturn(selected.net_return)}` : "Move across the chart to inspect a session."}</span>
      <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView Lightweight Charts™</a></div>
  </figure>;
}
