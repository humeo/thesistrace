import { useTranslation } from "../i18n";
import type { ResearchInputs } from "./draft";
import { exposurePercentage, readScoringRule } from "./strategyRules";
import { RuleDisclosure } from "./RuleDisclosure";

export function StrategyRuleSummary({ inputs }: { inputs: ResearchInputs }) {
  const { t } = useTranslation("strategy");
  const direct = inputs.strategyMode === "direct";
  const modules = inputs.frameworkModules;
  const rule = readScoringRule(inputs.formula);
  const percent = exposurePercentage(inputs.exposureExpression);
  const rows = [
    { label: t("workbench.summarySelection"), text: modules.universe_selection.kind === "python"
      ? t("workbench.summaryUniversePython")
      : inputs.universe ? t("workbench.summaryUniverse", { count: Number(inputs.universe.replace("top", "")) }) : t("workbench.summaryUniverseMissing") },
    { label: t("workbench.summaryRanking"), text: modules.alpha.kind === "python" ? t("workbench.summaryAlphaPython")
      : rule ? t(`workbench.summaryScoring.${rule.kind}`, { count: Number(rule.sessions) || 0 })
      : inputs.formula.trim() ? t("workbench.summaryCustomFormula") : t("workbench.summaryRankingMissing") },
    { label: t("workbench.summaryPortfolio"), text: modules.portfolio_construction.kind === "python" ? t("workbench.summaryPortfolioPython")
      : t("workbench.summaryHoldings", { holdings: inputs.holdingsCount || "—", sessions: inputs.selectionEverySessions || "—", exposure: percent === null ? t("workbench.dynamicExposureShort") : `${percent}%` }) },
  ];
  const risk: string[] = [];
  if (modules.risk_management.kind === "python") risk.push(t("workbench.summaryRiskPython"));
  else {
    if (inputs.stopLossThreshold) risk.push(t("workbench.summaryStop", { percent: inputs.stopLossThreshold }));
    if (inputs.maximumHoldingSessions) risk.push(t("workbench.summaryMaxHolding", { count: Number(inputs.maximumHoldingSessions) }));
    if (inputs.takeProfitTiers.length) risk.push(t("workbench.summaryProfit", { count: inputs.takeProfitTiers.length }));
    if (inputs.drawdownThreshold || inputs.drawdownMaximumExposure || inputs.drawdownCooldownSessions) {
      risk.push(t("workbench.summaryDrawdown", { threshold: inputs.drawdownThreshold || "—", exposure: inputs.drawdownMaximumExposure || "—" }));
    }
  }
  return <RuleDisclosure title={t("workbench.summaryTitle")}>
    <section aria-label={t("workbench.summaryTitle")} className="grid gap-3 rounded-lg bg-secondary p-4">
    {direct ? <p className="m-0 text-sm">{t("workbench.summaryDirect")}</p>
      : <dl className="m-0 grid gap-3 text-sm">
        {rows.map(row => <div key={row.label}><dt className="text-muted-foreground">{row.label}</dt><dd className="m-0 mt-1">{row.text}</dd></div>)}
        {modules.portfolio_construction.kind === "builtin" && <div><dt className="text-muted-foreground">{t("workbench.summaryWeighting")}</dt>
          <dd className="m-0 mt-1">{t(`workbench.weighting.${inputs.weighting}`)}</dd></div>}
        {modules.portfolio_construction.kind === "builtin" && inputs.minimumHoldingSessions && <div><dt className="text-muted-foreground">{t("workbench.summaryMinHolding")}</dt>
          <dd className="m-0 mt-1">{t("workbench.sessions", { count: Number(inputs.minimumHoldingSessions) })}</dd></div>}
        <div><dt className="text-muted-foreground">{t("workbench.summaryExit")}</dt>
          <dd className="m-0 mt-1">{risk.length ? risk.join(t("workbench.listSeparator")) : t("workbench.summaryNoRisk")}</dd></div>
      </dl>}
    </section>
  </RuleDisclosure>;
}
