import { expect, test, vi } from "vitest";
import { createDiagnosticsScheduler, formatFormulaDiagnostic, type DiagnosticDetails, type DiagnosticState } from "./diagnostics";

test.each([
  ["UNKNOWN_IDENTIFIER", { kind: "identifier", expected: ["close"], actual: "closes" }, "Unknown Alpha identifier: closes", "未知 Alpha 标识：closes"],
  ["INVALID_ARITY", { kind: "arity", expected: 2, actual: 1 }, "Expected 2 arguments; received 1.", "需要 2 个参数，实际收到 1 个。"],
  ["WINDOW_OUT_OF_RANGE", { kind: "window", expected: [1, 252], actual: "0" }, "Window must be between 1 and 252; received 0.", "窗口必须在 1 到 252 之间，实际为 0。"],
  ["TYPE_MISMATCH", { kind: "value_type", expected: "numeric_series", actual: "boolean_series" }, "Expected numeric series; received Boolean series.", "需要数值序列，实际为布尔序列。"],
  ["INVALID_COMMON_INPUT", { kind: "common_input", expected: "sw2021_l1_integer_literal", actual: "123456" }, "Industry must be a literal SW2021 L1 code from the catalog; received 123456.", "行业参数必须是目录中的 SW2021 一级行业整数字面量，实际为 123456。"],
  ["FORMULA_TOO_LONG", { kind: "resource_limit", expected: 4096, actual: 4097 }, "Formula exceeds 4096 characters (4097 received).", "公式超过 4096 个字符（实际 4097 个）。"],
] satisfies [string, DiagnosticDetails, string, string][])("%s renders facts without interpreting the server sentence", (code, details, en, zh) => {
  const diagnostic = { code, details, message: "untrusted server diagnostic" };
  expect(formatFormulaDiagnostic(diagnostic, "en")).toBe(en);
  expect(formatFormulaDiagnostic(diagnostic, "zh-CN")).toBe(zh);
  expect(formatFormulaDiagnostic(diagnostic, "en")).toBe(en);
});

test("unknown and malformed diagnostics are explicit localized failures without private messages", () => {
  for (const diagnostic of [
    { code: "FUTURE_CODE", details: null, message: "private stack trace" },
    { code: "INVALID_ARITY", details: null, message: "private stack trace" },
    { code: "INVALID_ARITY", details: { kind: "arity", expected: "unknown", actual: 1 } as DiagnosticDetails, message: "private stack trace" },
  ]) {
    expect(formatFormulaDiagnostic(diagnostic, "en")).toBe("Formula validation failed. Please check the expression and try again.");
    expect(formatFormulaDiagnostic(diagnostic, "zh-CN")).toBe("未能完成公式验证，请检查表达式后重试。");
  }
});

test("integer diagnostic literals survive the JSON boundary exactly", () => {
  const diagnostic = JSON.parse('{"code":"WINDOW_OUT_OF_RANGE","details":{"kind":"window","expected":[1,252],"actual":"9007199254740993"}}');
  expect(formatFormulaDiagnostic(diagnostic, "en")).toBe("Window must be between 1 and 252; received 9007199254740993.");
  expect(formatFormulaDiagnostic(diagnostic, "zh-CN")).toBe("窗口必须在 1 到 252 之间，实际为 9007199254740993。");
});

test("a malformed formula response becomes an unavailable validation state", async () => {
  vi.useFakeTimers();
  const scheduler = createDiagnosticsScheduler(async () => Response.json({ valid: false, diagnostics: [{ code: "SYNTAX_ERROR", message: "private", range: null }] }), 0);
  const states: DiagnosticState[] = [];
  try {
    scheduler.diagnose("close", (state) => states.push(state));
    await vi.runAllTimersAsync();
    expect(states.at(-1)).toEqual({ kind: "unavailable", result: null });
  } finally {
    scheduler.dispose();
    vi.useRealTimers();
  }
});
