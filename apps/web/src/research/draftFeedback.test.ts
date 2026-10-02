import { describe, expect, it } from "vitest";
import { researchDraftFeedback, researchInputStage } from "./draftFeedback";
import type { ResearchRunAdmissionIssue } from "./admission";

const issue = (field: string, code = "STRATEGY_PROGRAM_INVALID"): ResearchRunAdmissionIssue => ({
  field, code, message: "untrusted server text", severity: "error", range: null,
  details: { kind: "strategy_program", error_type: "SyntaxError", line: 7 },
});
const base = { key: "current", inputIssues: [], admission: null, configuration: null, diagnostics: { kind: "idle" as const, result: null } };

describe("current Browser Draft feedback", () => {
  it("isolates stale admission and configuration after edits", () => {
    const feedback = researchDraftFeedback({ ...base,
      admission: { key: "previous", issues: [issue("program.source")] },
      configuration: { key: "previous", checking: false, status: "invalid", issues: [issue("program.source")] },
    });
    expect(feedback.admissionIssues).toEqual([]);
    expect(feedback.configuration).toBeNull();
    expect(feedback.configurationChanged).toBe(true);
    expect(feedback.fieldIssue("programSource")).toBeUndefined();
    expect(feedback.programErrorLine()).toBeNull();
    expect(researchDraftFeedback(base).configurationChanged).toBe(false);
  });
  it("keeps local, admission and configuration priority within the exact input", () => {
    const admission = issue("modules.alpha.program.source");
    const configuration = issue("modules.alpha.program.source", "CONFIGURATION_ERROR");
    const args = { ...base, admission: { key: "current", issues: [admission] },
      configuration: { key: "current", checking: false, status: "invalid" as const, issues: [configuration] } };
    expect(researchDraftFeedback(args).fieldIssue("alpha.programSource")).toEqual({ kind: "server", issue: admission });
    expect(researchDraftFeedback(args).fieldIssue("risk_management.programSource")).toBeUndefined();
    expect(researchDraftFeedback({ ...args, inputIssues: [{ field: "alpha.programSource", code: "programSource" }] }).fieldIssue("alpha.programSource")?.kind).toBe("input");
    expect(researchDraftFeedback({ ...args, admission: null }).fieldIssue("alpha.programSource")).toEqual({ kind: "server", issue: configuration });
  });
  it("maps nested authoring paths while keeping Python line evidence exact", () => {
    const feedback = researchDraftFeedback({ ...base, admission: { key: "current", issues: [
      issue("modules.risk_management.program.source.syntax"), issue("costs.slippage_bps"),
      issue("modules.risk_management.portfolio_drawdown.drawdown_threshold"),
      issue("take_profit_tiers.2.cumulative_reduction"),
    ] } });
    expect(feedback.fieldIssue("risk_management.programSource")?.kind).toBe("server");
    expect(feedback.programErrorLine("risk_management")).toBeNull();
    expect(feedback.fieldIssue("costs.slippage_bps")?.kind).toBe("server");
    expect(feedback.fieldIssue("drawdownThreshold")?.kind).toBe("server");
    expect(feedback.fieldIssue("takeProfitTiers.2.cumulativeReduction")?.kind).toBe("server");
    expect(researchInputStage("risk_management.programSource")).toBe("risk_management");
  });
  it("does not turn configuration-only Formula issues into editor admission markers", () => {
    const range = { start: { offset: 0, line: 1, column: 1 }, end: { offset: 4, line: 1, column: 5 } };
    const formula = { ...issue("formula"), range };
    const configuration = { key: "current", checking: false, status: "invalid" as const, issues: [formula] };
    expect(researchDraftFeedback({ ...base, configuration }).formulaDiagnostics).toEqual([]);
    expect(researchDraftFeedback({ ...base, configuration, admission: { key: "current", issues: [formula] } }).formulaDiagnostics).toEqual([formula]);
  });
});
