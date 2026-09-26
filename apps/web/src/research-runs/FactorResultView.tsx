import { Metric, MetricGroup } from "../components/product/MetricGroup";
import { Section } from "../components/layout/Page";
import { MetricHelp } from "../analysis/MetricHelp";
import { useTranslation } from "../i18n";
import { formatDecimal, formatNumber } from "../i18n/format";
import { factorMetricHelp } from "./metricHelp";
import type { FactorEvaluationResearchResult, FactorHorizon } from "./ResearchRunsPage";

const HORIZONS = ["1", "5", "20"] as const;

/** Presentation of the frozen factor result; no requests or mutable Run state. */
export function FactorResultView({ result }: { result: FactorEvaluationResearchResult }) {
  const { t } = useTranslation("runs");
  return <Section title={t("result.factor")}>
    <div className="grid min-w-0 gap-6">
      {HORIZONS.map((horizon) => <FactorHorizonView horizon={result.factor.horizons[horizon]} key={horizon} />)}
    </div>
  </Section>;
}

function FactorHorizonView({ horizon }: { horizon: FactorHorizon }) {
  const { t } = useTranslation("runs");
  const help = factorMetricHelp(horizon.horizon);
  const context = t("result.horizon", { horizon: formatNumber(horizon.horizon) });
  const label = t("result.horizonFactor", { horizon: formatNumber(horizon.horizon) });
  return <section aria-label={label} className="flex min-w-0 flex-col gap-3">
    <h3 className="m-0 text-sm font-semibold">{context}</h3>
    <MetricGroup label={label}>
      <Metric label="Rank IC" help={<MetricHelp label={`${context} Rank IC`} content={help.rankIc} />}
        value={formatDecimal(horizon.summary.rank_ic.mean, 3, "dash")}
        detail={t("result.rankCoverage", { valid: formatNumber(horizon.coverage.rank_ic_valid_session_count), total: formatNumber(horizon.coverage.signal_session_count) })} />
      <Metric label="Rank ICIR" help={<MetricHelp label={`${context} Rank ICIR`} content={help.rankIcir} />}
        value={formatDecimal(horizon.summary.rank_ic.icir, 3, "dash")} />
      <Metric label="IC" help={<MetricHelp label={`${context} IC`} content={help.ic} />}
        value={formatDecimal(horizon.summary.ic.mean, 3, "dash")}
        detail={t("result.icCoverage", { valid: formatNumber(horizon.coverage.ic_valid_session_count), total: formatNumber(horizon.coverage.signal_session_count) })} />
      <Metric label="ICIR" help={<MetricHelp label={`${context} ICIR`} content={help.icir} />}
        value={formatDecimal(horizon.summary.ic.icir, 3, "dash")} />
    </MetricGroup>
  </section>;
}
