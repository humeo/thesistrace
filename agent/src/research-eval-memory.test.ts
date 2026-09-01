import type { MastraDBMessage } from "@mastra/core/agent";
import { describe, expect, it, vi } from "vitest";

import { researchEvalMemoryFacts, type ResearchEvalMemoryExpectation } from "./research-eval-memory.js";

const run = {
  id: "run_0123456789abcdef0123", formula: "rank(close)", start_date: "2026-07-20", end_date: "2026-08-04",
  universe: "top300", neutralization: "none", research_kind: "factor_evaluation" as const,
};
const { id: _runId, ...runInput } = run;
const formula: ResearchEvalMemoryExpectation = { kind: "formula", original_formula: "rank(not_a_market_field)", run };
const admission: ResearchEvalMemoryExpectation = { kind: "admission", requested_start: "2010-01-04", run };
function message(index: number, name: string, args: Record<string, unknown>, result: Record<string, unknown>): MastraDBMessage {
  return {
    id: `message-${index}`, role: "assistant", createdAt: new Date(1000 * index),
    threadId: "433643b2-5aeb-42bc-bbff-f5db8a09f706", resourceId: "00000000-0000-4000-8000-000000000101",
    content: { format: 2, parts: [{ type: "tool-invocation", toolInvocation: {
      state: "result", toolCallId: `call-${index}`, toolName: `thesistrace_${name}`, args, result,
    } }] },
  };
}
const bad = () => message(1, "diagnose_alpha_formula", { source: formula.original_formula }, { valid: false, diagnostics: [{ code: "UNKNOWN_IDENTIFIER", message: "private-eval-canary" }] });
const good = () => message(2, "diagnose_alpha_formula", { source: run.formula }, { valid: true, diagnostics: [] });
const accepted = (input: Record<string, unknown> = {}) => message(3, "submit_research_run", { ...runInput, request_id: "corrected-request", ...input }, { outcome: "accepted", run_id: run.id, status: "queued", replayed: false, retry_after_seconds: 1 });
const rejected = (input: Record<string, unknown> = {}, code = "INSUFFICIENT_CALCULATION_WARMUP") => message(1, "submit_research_run",
  { ...runInput, start_date: admission.requested_start, request_id: "original-request", ...input },
  { outcome: "rejected", issues: [{ code, field: "start_date", message: "private-eval-canary" }], replayed: false });
function facts(history: MastraDBMessage[], expectation: ResearchEvalMemoryExpectation | null) {
  // Native Memory orders by its persisted clock, not the supplied array order.
  const timeline = history.map((item, index) => ({ ...item, id: `ordered-${index}`, createdAt: new Date(1000 * index) }));
  return researchEvalMemoryFacts(timeline, expectation);
}
function steps(...groups: MastraDBMessage[][]): MastraDBMessage {
  return { ...groups[0]![0]!, content: { format: 2, parts: groups.flatMap((group) => [
    { type: "step-start" as const }, ...group.flatMap((item) => item.content.parts),
  ]) } };
}
function pending(item: MastraDBMessage): MastraDBMessage {
  return { ...item, content: { format: 2, parts: item.content.parts.map((part) => {
    if (part.type !== "tool-invocation" || part.toolInvocation.state !== "result") return part;
    const { result: _result, ...call } = part.toolInvocation;
    return { ...part, toolInvocation: { ...call, state: "call" as const } };
  }) } };
}
function implicitFirstStep(...groups: MastraDBMessage[][]): MastraDBMessage {
  const history = steps(...groups);
  return { ...history, content: { ...history.content, parts: history.content.parts.slice(1) } };
}

describe("content-free native Memory outcome oracle", () => {
  it("distinguishes invalid-to-valid Formula correction from two already-valid diagnoses", () => {
    expect(facts([bad(), good(), accepted()], formula)).toEqual({ formula_corrected: true, admission_corrected: false, unresolved_admission_rejection: false, batch_results_inspected: false });
    for (const history of [[good(), good(), accepted()], [good(), bad(), accepted()], [accepted(), bad(), good()], [bad(), good()]]) {
      expect(facts(history, formula).formula_corrected).toBe(false);
    }
    expect(facts([bad(), good(), accepted({ formula: "-rank(close)" })], formula).formula_corrected).toBe(false);
  });
  it("requires real warmup rejection followed by a revised idempotency key and unchanged research", () => {
    expect(facts([rejected(), accepted()], admission)).toEqual({ formula_corrected: false, admission_corrected: true, unresolved_admission_rejection: false, batch_results_inspected: false });
    for (const history of [
      [accepted()], [accepted(), rejected()], [bad(), good(), accepted()],
      [rejected({}, "FOLDER_NOT_FOUND"), accepted()],
      [rejected(), accepted({ request_id: "original-request" })],
      [rejected(), accepted({ formula: "rank(volume)" })],
      [rejected(), accepted({ start_date: admission.requested_start })],
      [rejected({ formula: "rank(volume)" }), accepted()],
    ]) expect(facts(history, admission).admission_corrected).toBe(false);
  });
  it("does not credit an admission revision already started before the rejection was observed", () => {
    for (const history of [
      [steps([rejected(), accepted()])], [steps([accepted(), rejected()])],
      [steps([pending(accepted()), rejected()], [accepted()])],
      [steps([pending(accepted()), rejected()]), accepted()],
    ]) expect(facts(history, admission).admission_corrected).toBe(false);
    expect(facts([steps([rejected()], [accepted()])], admission).admission_corrected).toBe(true);
  });
  it("requires a later model step for each Formula repair decision and its submission", () => {
    for (const history of [
      [steps([bad(), good()], [accepted()])],
      [steps([bad()], [good(), accepted()])],
      [steps([pending(good()), bad()], [good()], [accepted()])],
      [steps([pending(accepted()), bad()], [good()], [accepted()])],
    ]) expect(facts(history, formula).formula_corrected).toBe(false);
    expect(facts([steps([bad()], [good()], [accepted()])], formula).formula_corrected).toBe(true);
  });
  it("preserves native step boundaries when the initial step-start is omitted", () => {
    expect(facts([implicitFirstStep([bad()], [good()], [accepted()])], formula).formula_corrected).toBe(true);
    expect(facts([implicitFirstStep([rejected()], [accepted()])], admission).admission_corrected).toBe(true);
    expect(facts([implicitFirstStep([rejected()], [accepted()])], null).unresolved_admission_rejection).toBe(false);
    for (const history of [
      implicitFirstStep([bad(), good()], [accepted()]),
      implicitFirstStep([bad()], [good(), accepted()]),
      implicitFirstStep([pending(good()), bad()], [good()], [accepted()]),
      implicitFirstStep([pending(accepted()), bad()], [good()], [accepted()]),
    ]) expect(facts([history], formula).formula_corrected).toBe(false);
    for (const history of [
      implicitFirstStep([rejected(), accepted()]),
      implicitFirstStep([pending(accepted()), rejected()], [accepted()]),
    ]) {
      expect(facts([history], admission).admission_corrected).toBe(false);
      expect(facts([history], null).unresolved_admission_rejection).toBe(true);
    }
  });
  it("does not let a prestarted parallel admission erase a structured rejection", () => {
    for (const history of [
      [steps([rejected(), accepted()])], [steps([accepted(), rejected()])],
      [steps([pending(accepted()), rejected()]), accepted()],
    ]) expect(facts(history, null).unresolved_admission_rejection).toBe(true);
    expect(facts([steps([rejected()], [accepted()])], null).unresolved_admission_rejection).toBe(false);
  });
  it("requires successful Factor Result reads for both distinct Batch children", () => {
    const childIds = [run.id, "run_abcdef0123456789abcd"];
    const expectation: ResearchEvalMemoryExpectation = { kind: "batch-results", run_ids: [childIds[0]!, childIds[1]!] };
    const resultRead = (index: number, runId: string, output: Record<string, unknown> = {}) => message(index,
      "get_research_run_result", { run_id: runId, section: "factor" }, {
        run_id: runId, section: "factor", research_kind: "factor_evaluation",
        factor: { horizons: {}, private_canary: "private-eval-canary" }, ...output,
      });
    const first = () => resultRead(1, childIds[0]!);
    const second = () => resultRead(2, childIds[1]!);
    for (const history of [
      [], [first()], [first(), resultRead(2, childIds[0]!)],
      [first(), resultRead(2, "run_00000000000000000001")],
      [first(), resultRead(2, childIds[1]!, { run_id: childIds[0] })],
      [first(), resultRead(2, childIds[1]!, { section: "provenance" })],
      [first(), resultRead(2, childIds[1]!, { isError: true })],
      [first(), pending(second())],
      [first(), message(2, "get_research_run_result", { run_id: childIds[1], section: "factor" }, { outcome: "completed" })],
    ]) expect(facts(history, expectation)).toMatchObject({ batch_results_inspected: false });
    for (const history of [[first(), second()], [second(), first()], [steps([first(), second()])]]) {
      expect(facts(history, expectation)).toMatchObject({ batch_results_inspected: true });
      expect(JSON.stringify(facts(history, expectation))).not.toContain("private-eval-canary");
    }
  });
  it("distinguishes an unresolved structured admission rejection from a recovered one", () => {
    expect(researchEvalMemoryFacts([rejected()], null).unresolved_admission_rejection).toBe(true);
    expect(researchEvalMemoryFacts([rejected(), accepted()], null).unresolved_admission_rejection).toBe(false);
    expect(researchEvalMemoryFacts([bad(), good()], null).unresolved_admission_rejection).toBe(false);
  });
  it("uses the public MCP outcome, not the internal Core service's nested Run object", () => {
    const internal = message(3, "submit_research_run", { ...runInput, request_id: "corrected-request" }, { outcome: "accepted", run: { id: run.id }, replayed: false });
    expect(facts([bad(), good(), internal], formula).formula_corrected).toBe(false);
  });
  it("exports booleans only and closes malformed expectations without logging private input", () => {
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    try {
      expect(JSON.stringify(researchEvalMemoryFacts([bad(), good(), accepted()], formula))).not.toContain("private-eval-canary");
      expect(() => researchEvalMemoryFacts([bad()], { ...formula, prompt: "private-eval-canary" } as ResearchEvalMemoryExpectation)).toThrow("RESEARCH_EVAL_REPORT_INVALID");
      expect(() => researchEvalMemoryFacts([], { kind: "batch-results", run_ids: [run.id, run.id] })).toThrow("RESEARCH_EVAL_REPORT_INVALID");
      expect(warning).not.toHaveBeenCalled(); expect(error).not.toHaveBeenCalled();
    } finally { vi.restoreAllMocks(); }
  });
});
