import type { EditorDiagnostic } from "./AlphaFormulaEditor";
import type { ResearchRunAdmissionIssue } from "./admission";
import { drawdownFields, type DrawdownField } from "./portfolioDrawdown";
import { frameworkStages, type FrameworkStage } from "./frameworkModules";
import type { DiagnosticState } from "./diagnostics";
import type { ResearchInputField, researchInputIssues } from "./draft";

export type AdmissionFeedback = { key: string; issues: ResearchRunAdmissionIssue[] };
export type ConfigurationFeedback = AdmissionFeedback & {
  checking: boolean;
  status: "checking" | "valid" | "invalid" | "unavailable";
};

/** Attributes only current feedback, keeping local/admission/configuration priority in the Draft. */
export function researchDraftFeedback({ key, inputIssues, admission, configuration, diagnostics }: {
  key: string;
  inputIssues: ReturnType<typeof researchInputIssues>;
  admission: AdmissionFeedback | null;
  configuration: ConfigurationFeedback | null;
  diagnostics: DiagnosticState;
}) {
  const admissionIssues = admission?.key === key ? admission.issues : [];
  const currentConfiguration = configuration?.key === key ? configuration : null;
  const serverIssues = [...admissionIssues, ...(currentConfiguration?.issues ?? [])];
  const admissionDiagnostics: EditorDiagnostic[] = admissionIssues.flatMap(issue =>
    issue.field === "formula" && issue.range !== null ? [{ ...issue, range: issue.range }] : []);
  return {
    inputIssues,
    admissionIssues,
    configuration: currentConfiguration,
    configurationChanged: configuration !== null && configuration.key !== key,
    formulaDiagnostics: admissionDiagnostics.length ? admissionDiagnostics
      : diagnostics.kind === "complete" ? diagnostics.result.diagnostics : [],
    inputIssue(field: ResearchInputField) {
      return inputIssues.find(issue => issue.field === field);
    },
    fieldIssue(field: ResearchInputField) {
      const local = inputIssues.find(issue => issue.field === field);
      if (local) return { kind: "input" as const, issue: local };
      const server = serverIssues.find(issue => matchesField(field, issue.field));
      return server ? { kind: "server" as const, issue: server } : undefined;
    },
    programErrorLine(stage?: FrameworkStage): number | null {
      const field = `${stage ? `modules.${stage}.` : ""}program.source`;
      const issue = serverIssues.find(issue => issue.field === field && issue.details?.kind === "strategy_program");
      return issue?.details?.kind === "strategy_program" ? issue.details.line : null;
    },
  };
}

function matchesField(field: ResearchInputField, server: string): boolean {
  if (field.startsWith("costs.")) return server === field;
  if (drawdownFields.includes(field as DrawdownField)) {
    const key = { drawdownThreshold: "drawdown_threshold", drawdownMaximumExposure: "maximum_stock_exposure", drawdownCooldownSessions: "cooldown_sessions" }[field as DrawdownField];
    return server.includes(`portfolio_drawdown.${key}`);
  }
  if (field.startsWith("takeProfitTiers.")) {
    const [, index, key] = field.split(".");
    return server.includes(`take_profit_tiers.${index}.${key === "profitThreshold" ? "profit_threshold" : "cumulative_reduction"}`);
  }
  const holding = { stopLossThreshold: "stop_loss_threshold", maximumHoldingSessions: "maximum_holding_sessions", minimumHoldingSessions: "minimum_holding_sessions" };
  if (field in holding) return server.includes(holding[field as keyof typeof holding]);
  const [stage, input] = field.includes(".") ? field.split(".") : [null, field];
  if (input !== "programSource") return server === field;
  const path = `${stage ? `modules.${stage}.` : ""}program.source`;
  return server === path || server.startsWith(`${path}.`);
}

/** Canonical authoring attribution; the page chooses how to reveal and focus this stage. */
export function researchInputStage(field: ResearchInputField): FrameworkStage | undefined {
  const stage = field.split(".")[0];
  if (frameworkStages.includes(stage as FrameworkStage)) return stage as FrameworkStage;
  if (field === "universe") return "universe_selection";
  if (field === "formula" || field === "neutralization") return "alpha";
  if (["holdingsCount", "selectionEverySessions", "volatilityWindow", "exposureExpression", "minimumHoldingSessions"].includes(field)) return "portfolio_construction";
  if (drawdownFields.includes(field as DrawdownField) || field.startsWith("takeProfitTiers.") || field === "stopLossThreshold" || field === "maximumHoldingSessions") return "risk_management";
  return undefined;
}
