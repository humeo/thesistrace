export type RunSelection = Readonly<{
  modelKey: string;
  providerModelId: string;
  reasoningEffort: "none" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";
}>;
export function readRunSelection(value: unknown): RunSelection | null;
