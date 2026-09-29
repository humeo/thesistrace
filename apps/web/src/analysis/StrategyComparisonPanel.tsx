import { Alert, AlertDescription, AlertTitle } from "../components/ui/alert";
import { useTranslation } from "../i18n";
import { catalogLabel } from "../i18n/catalog";
import { StrategyPerformanceChart } from "./StrategyPerformanceChart";
import type { StrategyComparison } from "./strategyComparison";

export function StrategyComparisonPanel({
  comparison,
  variant,
}: {
  comparison: StrategyComparison;
  variant?: "default" | "result";
}) {
  const { t } = useTranslation("analysis");
  const benchmark = catalogLabel("benchmarks", "csi300-price-index-open");
  if (comparison.status === "unavailable") {
    return (
      <Alert
        aria-label={t("chart.comparison", { benchmark })}
        role="status"
      >
        <AlertTitle>{t("chart.unavailable", { benchmark })}</AlertTitle>
        <AlertDescription>
          {comparison.reason === "no_entry_open"
            ? t("chart.noEntry")
            : t("chart.noBenchmark")}
        </AlertDescription>
      </Alert>
    );
  }

  return <StrategyPerformanceChart curves={comparison.curves} variant={variant} />;
}
