import { useTranslation } from "../i18n";
import { catalogLabel } from "../i18n/catalog";
import { StrategyPerformanceChart } from "./StrategyPerformanceChart";
import type { StrategyComparison } from "./strategyComparison";

export function StrategyComparisonPanel({
  comparison,
}: {
  comparison: StrategyComparison;
}) {
  const { t } = useTranslation("analysis");
  const benchmark = catalogLabel("benchmarks", "csi300-price-index-open");
  if (comparison.status === "unavailable") {
    return (
      <section
        aria-label={t("chart.comparison", { benchmark })}
        className="strategy-comparison-unavailable"
        role="status"
      >
        <strong>{t("chart.unavailable", { benchmark })}</strong>
        <p>
          {comparison.reason === "no_entry_open"
            ? t("chart.noEntry")
            : t("chart.noBenchmark")}
        </p>
      </section>
    );
  }

  return <StrategyPerformanceChart curves={comparison.curves} />;
}
