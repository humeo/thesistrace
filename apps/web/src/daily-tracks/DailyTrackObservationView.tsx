import { useTranslation } from "react-i18next";
import { interfaceLocale } from "../i18n";
import { formatCurrency, formatNumber, formatSessionDate } from "../i18n/format";
import { SelectionEligibilityView, type SelectionEligibility } from "../research/SelectionEligibility";
import { useEffect, useRef, useState } from "react";
import { ColorType, LineSeries, createChart, type Time, type IChartApi } from "lightweight-charts";

export type DailyTrackObservation = {
  target_selection: SelectionEligibility;
  session: string;
  net_asset_value_cny: string;
  cash_cny: string;
  net_change_cny: string;
  net_return: number;
  maximum_drawdown: number;
  transaction_cost_cny: string;
  session_count: number;
  holdings: Array<{ instrument_id: string; shares: number; market_value_cny: string; weight: number }>;
  target_exposure: number;
  selection_interval: number;
  pending_target_session: string | null;
  sessions_until_next_signal: number;
  returns: Array<{ session: string; net_return: number }>;
};

export function formatMoney(value: string | number) { return formatCurrency(Number(value)); }

export function formatReturn(value: number) { return formatNumber(value, { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 }); }

export function ObservationSummary({ observation, originSession }: {
  observation: DailyTrackObservation; originSession: string;
}) {
  const { t } = useTranslation("daily");
  return (
    <dl className="track-account-strip" aria-label={t("account") }>
      <div>
        <dt>{t("returnSince")} </dt>
        <dd className={observation.net_return < 0 ? "track-negative" : ""}>
          {formatReturn(observation.net_return)}
        </dd>
        <span>{t("sinceDate", { date: originSession })}</span>
      </div>
      <div><dt>{t("maximumDrawdown")} </dt><dd>{formatReturn(observation.maximum_drawdown)}</dd>
        <span>{t("sinceDate", { date: originSession })}</span></div>
      <div><dt>{t("nav")} </dt><dd>{formatMoney(observation.net_asset_value_cny)}</dd>
        <span>{t("changeSince", { amount: formatMoney(observation.net_change_cny) })}</span></div>
      <div><dt>{t("cashAvailable")} </dt><dd>{formatMoney(observation.cash_cny)}</dd>
        <span>{t("simulatedCny")} </span></div>
      <div><dt>{t("holdings")} </dt><dd>{formatNumber(observation.holdings.length)}<small>{t("securities")} </small></dd>
        <span>{t("asOf", { date: observation.session })}</span></div>
    </dl>
  );
}

export function CurrentHoldings({ observation }: { observation: DailyTrackObservation }) {
  const { t } = useTranslation("daily");
  const [query, setQuery] = useState("");
  const holdings = observation.holdings.filter((item) => item.instrument_id.toLowerCase().includes(query.toLowerCase()));
  return (
    <section className="track-holdings" aria-label={t("holdings") }>
      <div className="track-section-heading">
        <div><h2>{t("holdings")} </h2><p>{t("holdingsDescription", { date: observation.session, target: formatReturn(observation.target_exposure), actual: formatReturn(1 - Number(observation.cash_cny) / Number(observation.net_asset_value_cny)) })}</p></div>
        <input aria-label={t("filterHoldings") } placeholder={t("findSymbol") } type="search"
          value={query} onChange={(event) => setQuery(event.target.value)} />
      </div>
      <SelectionEligibilityView selection={observation.target_selection} />
      <div className="track-table-scroll" tabIndex={0} role="region" aria-label={t("holdingsTable") }>
        <table className="track-table">
          <thead><tr><th scope="col">{t("symbol")} </th><th scope="col">{t("shares")} </th><th scope="col">{t("marketValue")} </th><th scope="col">{t("weight")} </th></tr></thead>
          <tbody>
            {holdings.map((item) => (
              <tr key={item.instrument_id}>
                <th scope="row" title={item.instrument_id}>{item.instrument_id.replace(/^equity:/, "")}</th>
                <td>{formatNumber(item.shares)}</td>
                <td>{formatMoney(item.market_value_cny)}</td>
                <td><span className="track-weight"><span aria-hidden="true" className="track-weight-bar"
                  style={{ width: `${Math.min(100, Math.max(0, item.weight * 100))}%` }} />{formatReturn(item.weight)}</span></td>
              </tr>
            ))}
            {holdings.length === 0 ? <tr><td colSpan={4} className="track-table-empty">
              {t(query ? "noSymbols" : "cashOnly")}
            </td></tr> : null}
          </tbody>
          <tfoot><tr><th scope="row">{t("cash")} </th><td>—</td><td>{formatMoney(observation.cash_cny)}</td>
            <td>{formatReturn(Number(observation.cash_cny) / Number(observation.net_asset_value_cny))}</td></tr></tfoot>
        </table>
      </div>
      <p className="track-footnote">{t("holdingsNote")} </p>
    </section>
  );
}

export function SelectionSchedule({ observation, isStopped, isBehind }: {
  observation: DailyTrackObservation; isStopped: boolean; isBehind: boolean;
}) {
  const { t } = useTranslation("daily");
  return (
    <section className="track-rebalance" aria-label={t("schedule") }>
      <div className="track-section-heading"><div><h2>{t("schedule")} </h2>
        <p>{t("scheduleDescription")} </p></div></div>
      <dl className="track-schedule-facts">
        <div><dt>{t("frequency")} </dt><dd>{t("every", { count: observation.selection_interval })}</dd></div>
        <div><dt>{t("lastSignal")} </dt><dd>{observation.pending_target_session ?? t("noSignal")}</dd></div>
        <div><dt>{t("nextStep")} </dt><dd>{isStopped ? t("trackingStopped") : observation.pending_target_session ? t("nextOpen") : t("nextSignal", { count: observation.sessions_until_next_signal })}</dd></div>
      </dl>
      {isBehind && !isStopped ? <p className="track-inline-notice">{t("behindNote")} </p> : null}
      <div className="track-guidance-empty">
        <h3>{t("ordersUnavailable")} </h3>
        <p>{t("ordersDescription")} </p>
      </div>
    </section>
  );
}

export function TrackingReturnChart({ observation, originSession }: {
  observation: DailyTrackObservation; originSession: string;
}) {
  const { t, i18n } = useTranslation("daily");
  const chartRef = useRef<IChartApi | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<{ session: string; net_return: number } | null>(null);
  useEffect(() => {
    const element = containerRef.current;
    if (!element || observation.returns.length < 2) return;
    setSelected(null);
    const chart = createChart(element, {
      width: element.clientWidth, height: 280,
      layout: { background: { type: ColorType.Solid, color: "#0f1011" }, textColor: "#8a8f98", fontFamily: "Inter, Noto Sans SC, -apple-system, BlinkMacSystemFont, sans-serif", attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: "#23252a" } },
      rightPriceScale: { borderColor: "#34343a" },
      timeScale: { borderColor: "#34343a", fixLeftEdge: true, fixRightEdge: true },
      localization: { locale: interfaceLocale(), priceFormatter: formatReturn },
    });
    chartRef.current = chart;
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
    return () => { chartRef.current = null; resize.disconnect(); chart.remove(); };
  }, [observation.returns]);
  useEffect(() => {
    chartRef.current?.applyOptions({ localization: { locale: interfaceLocale(), priceFormatter: formatReturn } });
  }, [i18n.language, observation.returns]);
  if (observation.returns.length < 2) {
    return <div className="track-chart-empty">
      <h3>{t("chartEmpty")} </h3>
      <p>{t("chartEmptyDescription", { date: originSession })}</p></div>;
  }
  return <figure className="track-return-chart" aria-label={t("chartTitle") }>
    <figcaption><span>{t("netReturnSince", { date: originSession })}</span><span>{t("observations", { count: observation.returns.length })}</span></figcaption>
    <div ref={containerRef} />
    <div className="track-chart-footer"><span>{selected ? `${formatSessionDate(selected.session)}  ${formatReturn(selected.net_return)}` : t("chartHint")}</span>
      <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView Lightweight Charts™</a></div>
  </figure>;
}
