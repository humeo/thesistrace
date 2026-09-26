import { useState } from "react";
import { Button } from "../components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../components/ui/collapsible";
import { Disclosure } from "../components/layout/Disclosure";
import { frameworkStages } from "./frameworkModules";
import type { StrategyDecisionState } from "./strategyDecisionState";
import { useTranslation } from "../i18n";

export function FrameworkStateView({ state }: { state: StrategyDecisionState }) {
  const { t } = useTranslation("strategy");
  const [open, setOpen] = useState(false);
  if (state.mode !== "framework" || !("module_states" in state)) return null;
  return <Collapsible open={open} onOpenChange={setOpen} className="framework-state min-w-0">
    <CollapsibleTrigger render={<Button variant="outline" className="h-auto min-h-11 whitespace-normal" />}>{t("state.summary", { candidates: state.universe.length, signals: state.signals.length })}</CollapsibleTrigger>
    <CollapsibleContent className="grid min-w-0 gap-3 py-3">
      <p>{t("state.help")}</p>
      {open && <>
        <Disclosure title={t("state.signals")}><StateJson value={state.signals} /></Disclosure>
        {frameworkStages.map(stage => <Disclosure key={stage} title={t("state.module", { stage: t(`stages.${stage}`) })}>
          <StateJson value={state.module_states[stage]} />
        </Disclosure>)}
      </>}
    </CollapsibleContent>
  </Collapsible>;
}

function StateJson({ value }: { value: unknown }) {
  return <pre className="max-h-96 overflow-auto rounded-md bg-muted p-4 font-mono text-sm" tabIndex={0}><code>{JSON.stringify(value, null, 2)}</code></pre>;
}
