import { Disclosure } from "../components/layout/Disclosure";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "../components/ui/card";
import { lazy, Suspense, useId, useState, type ReactNode } from "react";
import { cn } from "cn";
import Decimal from "decimal.js";
import { takeProfitDraft } from "./takeProfit";
import { frameworkStages, frozenStopLossPercentage } from "./frameworkModules";
import type { FrozenResearchAuthorableInput } from "./draft";
import type { PythonProgram } from "./pythonStrategy";
import { costFields, type SimulationCosts } from "./simulationCosts";
import { i18n, useTranslation } from "../i18n";
import { formatDecimalString, formatNumber } from "../i18n/format";
import { CopyButton } from "../mcp/CopyButton";

const PythonSourceEditor = lazy(() => import("./PythonSourceEditor").then(module => ({ default: module.PythonSourceEditor })));

export function FrozenFact({ label, children }: { label: string; children: ReactNode }) {
  return <div className="grid min-w-0 gap-1">
    <dt className="text-muted-foreground">{label}</dt>
    <dd className="m-0 min-w-0 tabular-nums [overflow-wrap:anywhere]">{children}</dd>
  </div>;
}

export function FrozenSimulationCosts({ costs }: { costs: SimulationCosts }) {
  const { t } = useTranslation("strategy");
  return <Card className="min-w-0 self-start" role="region" aria-label={t("frozen.fees")}>
    <CardHeader><CardTitle role="heading" aria-level={2}>{t("frozen.fees")}</CardTitle></CardHeader>
    <CardContent>
      <dl className="m-0 grid gap-0">
        {costFields.map(({ key }) => <div key={key} className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-4 border-b border-border py-3 first:pt-0 last:border-0 last:pb-0">
          <dt className="min-w-0 text-muted-foreground">{t(`cost.labels.${key}`)}</dt>
          <dd className="m-0 text-right tabular-nums" title={costs[key]}>{key.endsWith("_rate") || key === "commission_rate_all_in"
            ? `${formatNumber(new Decimal(costs[key]).mul(100).toNumber(), { maximumFractionDigits: 8 })}%`
            : key === "commission_min_cny" ? formatDecimalString(costs[key], 2)
            : formatNumber(Number(costs[key]), { maximumFractionDigits: 2 })}</dd>
        </div>)}
      </dl>
    </CardContent>
    <CardFooter><p className="m-0 text-muted-foreground">{t("frozen.feesHelp")}</p></CardFooter>
  </Card>;
}

export function FrozenPythonProgram({ program, title }: {
  program: PythonProgram; title?: string;
}) {
  const { t } = useTranslation("strategy");
  const id = useId();
  const [hasOpened, setHasOpened] = useState(false);
  const label = title ?? t("frozen.python");
  return <Disclosure title={label} onOpenChange={open => { if (open) setHasOpened(true); }}>
    <div className="mb-2 flex items-center justify-between gap-3">
      <span className="text-xs text-muted-foreground">Python · {t("frozen.readOnly")}</span>
      <CopyButton text={program.source} label={t("frozen.copySource")} />
    </div>
    {hasOpened && <Suspense fallback={<p role="status" className="m-0 py-3 text-muted-foreground">{t("frozen.loadingSource")}</p>}>
      <PythonSourceEditor id={id} label={label} source={program.source} readOnly />
    </Suspense>}
  </Disclosure>;
}

type FrozenFrameworkInput = Extract<FrozenResearchAuthorableInput, { strategy_mode: "framework" }>;

export function FrozenFrameworkModules({ input }: { input: FrozenFrameworkInput }) {
  const { t } = useTranslation("strategy");
  const { modules } = input;
  return <div className="grid min-w-0 gap-5" aria-label={t("frozen.modules")}>
    {frameworkStages.map(stage => {
      const module = modules[stage];
      return <section key={stage} className="grid min-w-0 items-start gap-4 border-t border-border pt-4 lg:grid-cols-[132px_minmax(0,1fr)]" aria-label={t(`stages.${stage}`)}>
        <h3 className="m-0 text-base font-semibold">{t(`stages.${stage}`)}</h3>
        <div className="grid min-w-0 gap-3">
        {typeof module !== "string" && module.kind === "python" ? <FrozenPythonProgram title={t("frozen.modulePython", { stage: t(`stages.${stage}`) })} program={module.program} /> : <>
          {(typeof module === "string" || module.kind === "periodic_top_n/v1") && <p className="m-0 text-muted-foreground">{t(`builtin.${stage}`)}</p>}
          <dl className={cn("m-0 grid min-w-0 gap-4 empty:hidden sm:grid-cols-2", stage === "portfolio_construction" && "lg:grid-cols-3")}>
            {stage === "alpha" && <>
              {input.formula !== undefined && <FrozenFact label={i18n.t("runs:formula")}><code>{input.formula}</code></FrozenFact>}
              {input.neutralization !== undefined && <FrozenFact label={i18n.t("research:neutralization")}>{i18n.t(`research:${input.neutralization}`)}</FrozenFact>}
            </>}
            {stage === "portfolio_construction" && <>
              {input.selection_every_sessions !== undefined && <>
                <FrozenFact label={i18n.t("runs:selection")}>{i18n.t(input.selection_every_sessions === 1 ? "runs:everySession" : "runs:everySessions", { sessions: formatNumber(input.selection_every_sessions) })}</FrozenFact>
                <FrozenFact label={i18n.t("research:holdings")}>{formatNumber(input.holdings_count!)}</FrozenFact>
                {input.weighting !== undefined && <FrozenFact label={i18n.t("research:weighting")}>{i18n.t(`research:weightings.${input.weighting}`)}</FrozenFact>}
                {input.weighting === "inverse_volatility" && <FrozenFact label={i18n.t("runs:volatilityWindow")}>{formatNumber(input.volatility_window!)} {i18n.t("runs:sessions")}</FrozenFact>}
                <FrozenFact label={i18n.t("runs:exposureExpression")}><code>{input.exposure_expression}</code></FrozenFact>
              </>}
              {typeof module !== "string" && module.kind === "periodic_top_n/v1" && <FrozenFact label={t("frozen.minimumHolding")}>{formatNumber(module.minimum_holding_sessions)}</FrozenFact>}
            </>}
            {typeof module !== "string" && module.kind === "builtin_risk/v1" && <>
              {module.stop_loss_threshold !== undefined && <FrozenFact label={t("frozen.stopLoss")}>{frozenStopLossPercentage(modules)}%</FrozenFact>}
              {module.maximum_holding_sessions !== undefined && <FrozenFact label={t("frozen.maximumHolding")}>{formatNumber(module.maximum_holding_sessions)}</FrozenFact>}
              {module.portfolio_drawdown && <FrozenFact label={t("frozen.drawdown")}>{t("frozen.drawdownSummary", { threshold: new Decimal(module.portfolio_drawdown.drawdown_threshold).mul(100).toString(), cap: new Decimal(module.portfolio_drawdown.maximum_stock_exposure).mul(100).toString(), cooldown: formatNumber(module.portfolio_drawdown.cooldown_sessions) })}</FrozenFact>}
              {module.take_profit_tiers && <FrozenFact label={t("frozen.takeProfit")}><ol className="m-0 grid gap-2 pl-4">{takeProfitDraft(module.take_profit_tiers).map((tier, index) => <li key={index}>{t("frozen.tier", { profit: tier.profitThreshold, reduction: tier.cumulativeReduction })}</li>)}</ol><p className="mb-0 mt-3 text-muted-foreground">{t("frozen.baseline")}</p></FrozenFact>}
            </>}
          </dl>
          {typeof module !== "string" && module.kind === "builtin_risk/v1" && <p className="m-0 text-muted-foreground">{t("frozen.evaluated")}</p>}
        </>}
        </div>
      </section>;
    })}
  </div>;
}
