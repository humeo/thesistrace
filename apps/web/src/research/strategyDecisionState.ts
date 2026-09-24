import type { SelectionEligibility } from "./SelectionEligibility";
import type { FrameworkStage } from "./frameworkModules";

type BuiltinPortfolioState = { selection: SelectionEligibility; exposure: number };
type BuiltinFrameworkState = BuiltinPortfolioState & {
  mode: "framework";
  selection_interval: number;
};
export type FrameworkModulesState = {
  mode: "framework";
  contract_checksum: string;
  universe: string[];
  signals: { instrument_id: string; value: number; created_session: string; created_session_number: number; valid_for_sessions: number }[];
  retained_proposal: unknown;
} & ({
  selection_interval: null;
  module_states: Record<FrameworkStage, Record<string, unknown>>;
} | {
  selection_interval: number;
  module_states: Record<FrameworkStage, Record<string, unknown>> & { portfolio_construction: BuiltinPortfolioState };
});

export type StrategyDecisionState = BuiltinFrameworkState | FrameworkModulesState | {
  mode: "direct";
  program_sha256: string;
  state: Record<string, unknown>;
};

export function isBuiltinFrameworkState(state: StrategyDecisionState): state is BuiltinFrameworkState {
  return state.mode === "framework" && "selection" in state;
}

export function strategySelection(state: StrategyDecisionState): SelectionEligibility | null {
  if (state.mode === "direct") return null;
  if (isBuiltinFrameworkState(state)) return state.selection;
  return state.selection_interval === null ? null : state.module_states.portfolio_construction.selection;
}
