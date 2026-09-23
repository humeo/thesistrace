import { i18n } from "../i18n";
import { formatNumber } from "../i18n/format";

export function strategyMetricHelp() {
  return i18n.t("analysis:metrics.strategy", { returnObjects: true });
}

export function factorMetricHelp(horizon: number) {
  return i18n.t("analysis:metrics.factor", { returnObjects: true, horizon: formatNumber(horizon) });
}
