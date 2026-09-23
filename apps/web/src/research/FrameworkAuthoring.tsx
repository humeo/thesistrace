import type { ReactNode } from "react";
import type { ResearchInputField } from "./draft";
import {
  frameworkStageLabels, frameworkStages, type FrameworkModulesDraft, type FrameworkStage,
} from "./frameworkModules";
import type { ProgramInputs } from "./pythonStrategy";
import { PythonStrategyAuthoring } from "./PythonStrategyAuthoring";

const builtinNames: Record<FrameworkStage, string> = {
  universe_selection: "Dataset candidates", alpha: "Alpha formula",
  portfolio_construction: "Periodic Top-N", risk_management: "Holding risk rules",
};
const explanations: Record<FrameworkStage, string> = {
  universe_selection: "Choose candidates from the Dataset Universe selected above.",
  alpha: "Produce scores or signals for the selected candidates.",
  portfolio_construction: "Propose holdings when the selected policy calls for an update. Built-in Top-N uses the selection and sizing settings below.",
  risk_management: "Inspect actual holdings and the new proposal at every Close. Adjustments combine into one final target before execution.",
};

export function FrameworkAuthoring({ modules, selectModule, updateProgram, stopLossThreshold, updateStopLoss, error, fieldsButton, alphaEditor }: {
  modules: FrameworkModulesDraft;
  stopLossThreshold: string;
  updateStopLoss: (value: string) => void;
  selectModule: (stage: FrameworkStage, kind: "builtin" | "python") => void;
  updateProgram: (stage: FrameworkStage, changes: Partial<ProgramInputs>) => void;
  error: (field: ResearchInputField) => string | undefined;
  fieldsButton: () => ReactNode;
  alphaEditor: ReactNode;
}) {
  return <div className="framework-authoring">
    <p className="framework-order">Each Close: Universe → Alpha / Signals → Portfolio → Risk → final target.</p>
    {frameworkStages.map((stage, index) => <section key={stage} className="framework-module" aria-label={`${frameworkStageLabels[stage]} module`}>
      <div className="framework-module-heading">
        <h3><span>{index + 1}</span> {frameworkStageLabels[stage]}</h3>
        <select aria-label={`${frameworkStageLabels[stage]} module`} value={modules[stage].kind} onChange={event => {
          if (event.target.value === "builtin" || event.target.value === "python") selectModule(stage, event.target.value);
        }}>
          <option value="builtin">Built-in · {builtinNames[stage]}</option>
          <option value="python">Python module</option>
        </select>
      </div>
      <p className="framework-module-help">{explanations[stage]}</p>
      {modules[stage].kind === "python" ? <PythonStrategyAuthoring stage={stage}
        inputs={modules[stage].program} onChange={changes => updateProgram(stage, changes)}
        error={field => error(`${stage}.${field}`)} fieldsButton={fieldsButton()} />
        : stage === "alpha" ? alphaEditor : stage === "risk_management" ? <div className="research-parameter-field">
          <label htmlFor="stop-loss-threshold">Stop loss (%)</label>
          <input id="stop-loss-threshold" type="text" inputMode="decimal" placeholder="Off" maxLength={128}
            value={stopLossThreshold} onChange={event => updateStopLoss(event.target.value)}
            aria-invalid={Boolean(error("stopLossThreshold"))}
            aria-describedby={error("stopLossThreshold") ? "stop-loss-help stop-loss-error" : "stop-loss-help"} />
          <p id="stop-loss-help" className="framework-module-help">Leave blank to disable. Uses actual acquisition cost including buy fees. Checks at Close and attempts to sell at the next Open; gaps or trading restrictions can increase the loss.</p>
          {error("stopLossThreshold") && <p id="stop-loss-error" className="inline-status-error">{error("stopLossThreshold")}</p>}
        </div> : null}
    </section>)}
  </div>;
}
