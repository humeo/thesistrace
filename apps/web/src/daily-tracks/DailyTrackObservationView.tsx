import { useTranslation } from "react-i18next";
import { interfaceLocale } from "../i18n";
import { formatCurrency, formatNumber, formatSessionDate } from "../i18n/format";
import { SelectionEligibilityView } from "../research/SelectionEligibility";
import { CloseRiskFacts, type CloseRiskPosition } from "../analysis/CloseRiskFacts";
import { isBuiltinFrameworkState, strategySelection, type StrategyDecisionState } from "../research/strategyDecisionState";
import { FrameworkStateView } from "../research/FrameworkStateView";
import { useEffect, useRef, useState } from "react";
import { ColorType, LineSeries, createChart, type Time, type IChartApi } from "lightweight-charts";

export type DailyTrackObservation = {
  decision_state: StrategyDecisionState;
  session: string;
  net_asset_value_cny: string;
  close_risk_nav_cny: string;
  cash_cny: string;
  net_change_cny: string;
  net_return: number;
  maximum_drawdown: number;
  transaction_cost_cny: string;
  session_count: number;
  holdings: Array<Omit<CloseRiskPosition, "execution_shares"> & {
    shares: number; market_value_cny: string; weight: number;
  }>;
  selection_interval: number | null;
  pending_target_session: string | null;
  sessions_until_next_signal: number | null;
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
  const selection = strategySelection(observation.decision_state);
  return (
    <section className="track-holdings" aria-label={t("holdings") }>
      <div className="track-section-heading">
        <div><h2>{t("holdings")}</h2><p>{isBuiltinFrameworkState(observation.decision_state)
          ? t("holdingsDescription", { date: observation.session, target: formatReturn(observation.decision_state.exposure), actual: formatReturn(1 - Number(observation.cash_cny) / Number(observation.net_asset_value_cny)) })
          : t("holdingsDescriptionWithoutTarget", { date: observation.session, actual: formatReturn(1 - Number(observation.cash_cny) / Number(observation.net_asset_value_cny)) })}</p></div>
        <input aria-label={t("filterHoldings")} placeholder={t("findSymbol")} type="search"
          value={query} onChange={(event) => setQuery(event.target.value)} />
      </div>
      {selection && <SelectionEligibilityView selection={selection} />}
      <FrameworkStateView state={observation.decision_state} />
      <CloseRiskFacts session={observation.session} nav={observation.close_risk_nav_cny}
        positions={observation.holdings.map(item => ({ ...item, execution_shares: item.shares }))} />
      <div className="track-table-scroll" tabIndex={0} role="region" aria-label={t("holdingsTable")}>
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
    <section className="track-rebalance" aria-label={t("schedule")}>
      <div className="track-section-heading"><div><h2>{t("schedule")}</h2>
        <p>{t(observation.selection_interval === null ? "scheduleConditionDescription" : "scheduleDescription")}</p></div></div>
      <dl className="track-schedule-facts">
        <div><dt>{t("frequency")}</dt><dd>{observation.selection_interval === null ? t("conditionDriven") : t("every", { count: observation.selection_interval })}</dd></div>
        <div><dt>{t("lastSignal")}</dt><dd>{observation.pending_target_session ?? t("noSignal")}</dd></div>
        <div><dt>{t("nextStep")}</dt><dd>{isStopped ? t("trackingStopped") : observation.pending_target_session ? t("nextOpen") : observation.selection_interval === null ? t("nextCondition") : t("nextSignal", { count: observation.sessions_until_next_signal! })}</dd></div>
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
