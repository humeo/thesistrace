import { coreFetch } from "../auth/coreFetch";
import { i18n, interfaceLocale, type InterfaceLocale } from "../i18n";
import { diagnosticsEn } from "../i18n/messages/diagnostics";

const fact = z.union([z.string(), z.number(), z.array(z.union([z.string(), z.number()]))]);
const position = z.object({ offset: z.number().int().nonnegative(), line: z.number().int().positive(), column: z.number().int().positive() });
export const sourceRangeSchema = z.object({ start: position, end: position }).refine(range => range.end.offset >= range.start.offset);
export const diagnosticDetailsSchema = z.object({
  kind: z.enum(["syntax", "identifier", "callability", "arity", "value_type", "window", "literal", "resource_limit", "common_input"]),
  expected: fact, actual: fact,
});
const formulaDiagnosticSchema = z.object({
  code: z.string(), message: z.string(), severity: z.literal("error"),
  range: sourceRangeSchema, details: diagnosticDetailsSchema,
});
const diagnosticsSchema = z.object({ valid: z.boolean(), diagnostics: z.array(formulaDiagnosticSchema) })
  .refine(result => result.valid === (result.diagnostics.length === 0));
export type DiagnosticDetails = z.infer<typeof diagnosticDetailsSchema>;
export type FormulaDiagnostic = z.infer<typeof formulaDiagnosticSchema>;

/** Core supplies facts; the view translates them without interpreting a server sentence. */
export function formatFormulaDiagnostic(
  diagnostic: { code: string; details: DiagnosticDetails | null },
  locale: InterfaceLocale = interfaceLocale(),
): string {
  const t = i18n.getFixedT(locale, "diagnostics");
  const failure = t("unavailable");
  const details = diagnostic.details;
  if (details == null || typeof details !== "object") return failure;
  const { kind, expected, actual } = details;
  const fact = (value: unknown): string | null => {
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
    if (typeof value !== "string" || !Object.hasOwn(diagnosticsEn.facts, value)) return null;
    return t(`facts.${value as keyof typeof diagnosticsEn.facts}`);
  };
  const facts = (value: unknown, type: "conjunction" | "disjunction"): string | null => {
    const labels = (Array.isArray(value) ? value : [value]).map(fact);
    return labels.length > 0 && labels.every((label) => label !== null)
      ? new Intl.ListFormat(locale, { type }).format(labels) : null;
  };
  const expectedFacts = facts(expected, "disjunction");
  const actualFacts = facts(actual, "conjunction");
  // Window/industry integer literals are decimal strings, including values beyond 2^53.
  const literalFact = typeof actual === "string" && /^-?\d+$/.test(actual) ? actual : actualFacts;
  const counts = typeof expected === "number" && Number.isFinite(expected)
    && typeof actual === "number" && Number.isFinite(actual);
  const bounds = Array.isArray(expected) && expected.length === 2
    && expected.every((value) => typeof value === "number" && Number.isFinite(value)) ? expected : null;
  switch (diagnostic.code) {
    case "SYNTAX_ERROR":
      return kind === "syntax" && expected === "one_complete_expression" ? t("syntax") : failure;
    case "UNSUPPORTED_SYNTAX":
      if (kind === "callability" && expected === "builtin_identifier") return t("directCall");
      if (kind !== "syntax") return failure;
      if (expected === "single_comparison" && actual === "chained_comparison") return t("chainedComparison");
      return actualFacts === null ? failure : t("unsupportedSyntax", { actual: actualFacts });
    case "UNSUPPORTED_OPERATOR":
      return kind === "syntax" && expectedFacts !== null && actualFacts !== null
        ? t("unsupportedOperator", { expected: expectedFacts, actual: actualFacts }) : failure;
    case "UNKNOWN_IDENTIFIER":
      if (kind === "common_input" && typeof expected === "string") return t("adjustedClose", { expected });
      return kind === "identifier" && typeof actual === "string" ? t("unknownIdentifier", { actual }) : failure;
    case "NOT_CALLABLE":
    case "EXPECTED_FIELD":
      return kind === "callability" && typeof actual === "string"
        ? t(diagnostic.code === "NOT_CALLABLE" ? "notCallable" : "expectedCall", { actual }) : failure;
    case "INVALID_ARITY":
      return kind === "arity" && counts ? t("arity", { expected, actual }) : failure;
    case "TYPE_MISMATCH":
    case "ROOT_MUST_BE_SERIES":
    case "EXPOSURE_MUST_BE_ACCOUNT_NUMERIC": {
      if (kind !== "value_type" || actualFacts === null) return failure;
      if (expected === "matching_branch_types") return t("branchTypes", { actual: actualFacts });
      if (expectedFacts === null) return failure;
      const key = diagnostic.code === "TYPE_MISMATCH" ? "valueType"
        : diagnostic.code === "ROOT_MUST_BE_SERIES" ? "root" : "exposureRoot";
      return t(key, { expected: expectedFacts, actual: actualFacts });
    }
    case "BOOLEAN_NOT_ALLOWED":
      return kind === "literal" && actual === "boolean" ? t("booleanLiteral") : failure;
    case "UNSUPPORTED_LITERAL":
      return kind === "literal" && actualFacts !== null ? t("literal", { actual: actualFacts }) : failure;
    case "NON_FINITE_LITERAL":
      return kind === "literal" && actual === "non_finite_number" ? t("finite") : failure;
    case "KEYWORD_ARGUMENT_NOT_ALLOWED":
      return kind === "syntax" && actual === "keyword_argument" ? t("keywords") : failure;
    case "STARRED_ARGUMENT_NOT_ALLOWED":
      return kind === "syntax" && ["starred_argument", "keyword_unpacking"].includes(String(actual)) ? t("starred") : failure;
    case "WINDOW_MUST_BE_INTEGER":
    case "WINDOW_OUT_OF_RANGE":
      return kind === "window" && bounds !== null && literalFact !== null
        ? t(diagnostic.code === "WINDOW_MUST_BE_INTEGER" ? "windowInteger" : "windowRange", {
          minimum: bounds[0], maximum: bounds[1], actual: literalFact,
        }) : failure;
    case "EXPOSURE_OUT_OF_RANGE":
      return kind === "literal" && bounds !== null
        ? t("exposureRange", { minimum: bounds[0], maximum: bounds[1] }) : failure;
    case "INVALID_COMMON_INPUT":
      return kind === "common_input" && expected === "sw2021_l1_integer_literal" && literalFact !== null
        ? t("industry", { actual: literalFact }) : failure;
    case "FORMULA_TOO_LONG":
    case "TOO_MANY_EXPRESSION_NODES":
    case "EXPRESSION_TOO_DEEP":
    case "LOOKBACK_EXCEEDS_LIMIT":
    case "WORK_EXCEEDS_LIMIT": {
      const key = {
        FORMULA_TOO_LONG: "length", TOO_MANY_EXPRESSION_NODES: "nodes", EXPRESSION_TOO_DEEP: "depth",
        LOOKBACK_EXCEEDS_LIMIT: "lookback", WORK_EXCEEDS_LIMIT: "work",
      } as const;
      return kind === "resource_limit" && counts ? t(key[diagnostic.code], { expected, actual }) : failure;
    }
    default: return failure;
  }
}
type FormulaDiagnostics = { valid: boolean; diagnostics: FormulaDiagnostic[] };
export type DiagnosticState =
  | { kind: "idle"; result: null }
  | { kind: "checking"; result: null }
  | { kind: "complete"; result: FormulaDiagnostics }
  | { kind: "unavailable"; result: null };

export function createDiagnosticsScheduler(
  request: typeof fetch = coreFetch,
  delayMilliseconds = 2000,
  context: "signal" | "exposure" = "signal",
) {
  let generation = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let controller: AbortController | null = null;

  function diagnose(source: string, publish: (state: DiagnosticState) => void): void {
    generation += 1;
    const selectedGeneration = generation;
    if (timer !== null) clearTimeout(timer);
    controller?.abort();
    if (source.trim() === "") {
      publish({ kind: "idle", result: null });
      return;
    }
    publish({ kind: "checking", result: null });
    timer = setTimeout(async () => {
      controller = new AbortController();
      try {
        const response = await request("/api/alpha/diagnostics", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source, context }),
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("Formula diagnostics unavailable");
        const result = diagnosticsSchema.parse(await response.json());
        if (selectedGeneration === generation) publish({ kind: "complete", result });
      } catch (reason: unknown) {
        if (selectedGeneration !== generation) return;
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        publish({ kind: "unavailable", result: null });
      }
    }, delayMilliseconds);
  }

  function dispose(): void {
    generation += 1;
    if (timer !== null) clearTimeout(timer);
    controller?.abort();
  }

  return { diagnose, dispose };
}
import { z } from "zod";
