export type RunSelection = Readonly<{
  modelKey: string;
  providerModelId: string;
  reasoningEffort: "none" | "minimal" | "low" | "medium" | "high" | "xhigh";
}>;
export function readRunSelection(value: unknown): RunSelection | null;
