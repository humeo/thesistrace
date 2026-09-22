import type { SelectionEligibility } from "./SelectionEligibility";

export type StrategyDecisionState = {
  mode: "framework";
  selection: SelectionEligibility;
  selection_interval: number;
  exposure: number;
} | {
  mode: "direct";
  program_sha256: string;
  state: Record<string, unknown>;
};
