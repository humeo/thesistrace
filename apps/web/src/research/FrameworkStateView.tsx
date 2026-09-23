import { useState } from "react";
import { frameworkStageLabels, frameworkStages } from "./frameworkModules";
import type { StrategyDecisionState } from "./strategyDecisionState";

export function FrameworkStateView({ state }: { state: StrategyDecisionState }) {
  const [open, setOpen] = useState(false);
  if (state.mode !== "framework" || !("module_states" in state)) return null;
  return <details className="framework-state" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Framework state · {state.universe.length} candidates · {state.signals.length} active signals</summary>
    <p>Signals and module state inform later decisions. They do not represent orders or fills.</p>
    {open && <>
      <details><summary>Active signals</summary><pre><code>{JSON.stringify(state.signals, null, 2)}</code></pre></details>
      {frameworkStages.map(stage => <details key={stage}>
        <summary>{frameworkStageLabels[stage]} state</summary>
        <pre><code>{JSON.stringify(state.module_states[stage], null, 2)}</code></pre>
      </details>)}
    </>}
  </details>;
}
