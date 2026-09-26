import { Tabs, TabsList, TabsTrigger, TabsContent } from "../../src/components/ui/tabs";
import { createRoot } from "react-dom/client";
import { StrategyPerformanceChart } from "../../src/analysis/StrategyPerformanceChart";
import { MetricHelp } from "../../src/analysis/MetricHelp";
import "../../src/styles.css";
import { strategyMetricHelp } from "../../src/research-runs/metricHelp";
import { useTranslation, changeInterfaceLanguage } from "../../src/i18n";

// Trigger locale changes without an outside pointer/focus interaction with a Popover.
window.addEventListener("fixture-language", event => changeInterfaceLanguage((event as CustomEvent<"en" | "zh-CN">).detail));
const curves = Array.from({ length: 550 }, (_, index) => ({
  session: new Date(Date.UTC(2024, 0, 1 + index)).toISOString().slice(0, 10),
  net_strategy_return: index / 1000,
  benchmark_relative_return: index / 2000,
  net_excess_nav: 1 + index / 2000,
  net_excess_return: index / 2000,
}));
function HelpSample() {
  const { t } = useTranslation("analysis");
  return <MetricHelp label={t("chart.strategy")} content={strategyMetricHelp().netCumulative} />;
}
createRoot(document.getElementById("root")!).render(<main style={{ padding: 20 }}>
  <button onClick={() => changeInterfaceLanguage("en")}>English</button>
  <button onClick={() => changeInterfaceLanguage("zh-CN")}>简体中文</button>
  <HelpSample />
  <Tabs defaultValue="chart">
    <TabsList><TabsTrigger value="chart">Performance</TabsTrigger><TabsTrigger value="configuration">Configuration</TabsTrigger></TabsList>
    <TabsContent value="chart" keepMounted><StrategyPerformanceChart curves={curves} /></TabsContent>
    <TabsContent value="configuration" keepMounted>Frozen configuration</TabsContent>
  </Tabs>
</main>);
