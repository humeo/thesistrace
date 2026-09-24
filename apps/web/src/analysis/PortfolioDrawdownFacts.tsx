import Decimal from "decimal.js";
import { useTranslation } from "../i18n";

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
    <p>{t("drawdownFacts.cycle", { start: item.cycle_started_session, nav: new Decimal(item.close_risk_nav_cny).toString(), peak: new Decimal(item.peak_close_nav_cny).toString() })}</p>
    <p>{t("drawdownFacts.drawdown", { drawdown: new Decimal(item.drawdown).mul(100).toString(), threshold: new Decimal(item.drawdown_threshold).mul(100).toString() })}</p>
    {item.triggered_session && <p>{t("drawdownFacts.triggered", { date: item.triggered_session, completed: item.completed_cooldown_sessions, total: item.cooldown_sessions })}</p>}
    <p>{item.maximum_stock_exposure === null ? t("drawdownFacts.noCap") : t("drawdownFacts.cap", { percent: new Decimal(item.maximum_stock_exposure).mul(100).toString() })}</p>
    <p>{t("drawdownFacts.release")}</p>
  </>;
}
