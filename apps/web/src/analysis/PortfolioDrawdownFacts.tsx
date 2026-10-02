import Decimal from "decimal.js";
import { useTranslation } from "../i18n";
import { formatDecimal, formatDecimalString } from "../i18n/format";

export type PortfolioDrawdownObservation = {
  reason: "portfolio_drawdown";
  status: "observing" | "threshold_reached" | "cooldown" | "awaiting_new_portfolio" | "new_portfolio_recovery";
  cycle_started_session: string; peak_close_nav_cny: string; close_risk_nav_cny: string;
  drawdown: string; drawdown_threshold: number; maximum_stock_exposure: number | null;
  cooldown_sessions: number; completed_cooldown_sessions: number; triggered_session: string | null;
};
export function PortfolioDrawdownFacts({ item }: { item: PortfolioDrawdownObservation }) {
  const { t } = useTranslation("strategy");
  return <>
    <strong>{t("drawdownFacts.title", { status: t(`drawdownFacts.statuses.${item.status}`) })}</strong>
    <p>{t("drawdownFacts.cycle", { start: item.cycle_started_session, nav: formatDecimalString(item.close_risk_nav_cny, 2), peak: formatDecimalString(item.peak_close_nav_cny, 2) })}</p>
    <p>{t("drawdownFacts.drawdown", { drawdown: formatDecimal(new Decimal(item.drawdown).mul(100).toNumber(), 2), threshold: formatDecimal(item.drawdown_threshold * 100, 2) })}</p>
    {item.triggered_session && <p>{t("drawdownFacts.triggered", { date: item.triggered_session, completed: item.completed_cooldown_sessions, total: item.cooldown_sessions })}</p>}
    <p>{item.maximum_stock_exposure === null ? t("drawdownFacts.noCap") : t("drawdownFacts.cap", { percent: formatDecimal(item.maximum_stock_exposure * 100, 2) })}</p>
    <p>{t("drawdownFacts.release")}</p>
  </>;
}
