import { useState } from "react";
import { frameworkStages } from "./frameworkModules";
import type { StrategyDecisionState } from "./strategyDecisionState";
import { useTranslation } from "../i18n";

export function FrameworkStateView({ state }: { state: StrategyDecisionState }) {
  const { t } = useTranslation("strategy");
  const [open, setOpen] = useState(false);
  if (state.mode !== "framework" || !("module_states" in state)) return null;
  return <details className="framework-state" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{t("state.summary", { candidates: state.universe.length, signals: state.signals.length })}</summary>
    <p>{t("state.help")}</p>
    {open && <>
      <details><summary>{t("state.signals")}</summary><pre><code>{JSON.stringify(state.signals, null, 2)}</code></pre></details>
      {frameworkStages.map(stage => <details key={stage}>
        <summary>{t("state.module", { stage: t(`stages.${stage}`) })}</summary>
        <pre><code>{JSON.stringify(state.module_states[stage], null, 2)}</code></pre>
      </details>)}
    </>}
  </details>;
}
