import { i18n, interfaceLocale, type InterfaceLocale } from "../i18n";
import { researchEn } from "../i18n/messages/research";
import { diagnosticDetailsSchema, sourceRangeSchema, formatFormulaDiagnostic, type DiagnosticDetails, type FormulaDiagnostic } from "./diagnostics";

type AdmissionDetails = { kind: "quota" | "coverage" | "warmup"; expected: string | number; actual: string | string[] };
const rerunDetailsSchema = z.object({
  kind: z.literal("rerun_source"),
  reason: z.enum(["unsupported_setting", "checkpoint_boundary", "research_kind", "invalid_field", "invalid_source"]),
  expected: z.union([z.string(), z.number()]).nullable(), actual: z.string().nullable(), validation_type: z.string().nullable(),
});
const strategyProgramDetailsSchema = z.object({
  kind: z.literal("strategy_program"), error_type: z.string().min(1), line: z.number().int().positive().nullable(),
});
export type ResearchRunAdmissionIssue = {
  code: string;
  field: string;
  message: string;
  severity: "error";
  range: FormulaDiagnostic["range"] | null;
  details: DiagnosticDetails | AdmissionDetails | z.infer<typeof rerunDetailsSchema> | z.infer<typeof strategyProgramDetailsSchema> | null;
};

const issueSchema: z.ZodType<ResearchRunAdmissionIssue> = z.object({
  code: z.string(), field: z.string(), message: z.string(), severity: z.literal("error"),
  range: sourceRangeSchema.nullable(),
  details: z.union([
    diagnosticDetailsSchema,
    rerunDetailsSchema,
    strategyProgramDetailsSchema,
    z.object({ kind: z.enum(["quota", "coverage", "warmup"]), expected: z.union([z.string(), z.number()]), actual: z.union([z.string(), z.array(z.string())]) }),
  ]).nullable(),
});

export function readResearchIssues(value: unknown): ResearchRunAdmissionIssue[] {
  return z.array(issueSchema).parse(value);
}

export function alphaDetails(details: ResearchRunAdmissionIssue["details"]): DiagnosticDetails | null {
  if (details == null || ["quota", "coverage", "warmup", "rerun_source", "strategy_program"].includes(details.kind)) return null;
  return details as DiagnosticDetails;
}

export function formatResearchIssue(issue: ResearchRunAdmissionIssue, locale: InterfaceLocale = interfaceLocale()): string {
  const t = i18n.getFixedT(locale, "research");
  const failure = t("admission.unavailable");
  const details = issue.details;
  switch (issue.code) {
    case "STRATEGY_PROGRAM_INVALID": {
      if (details?.kind !== "strategy_program") return failure;
      const problem = details.error_type === "SyntaxError"
        ? t("programIssues.syntax") : t("programIssues.type", { errorType: details.error_type });
      return details.line !== null
        ? t("programIssues.withLine", { problem, line: details.line })
        : t("programIssues.withoutLine", { problem });
    }
    case "DAILY_RUN_QUOTA_EXCEEDED":
      return details?.kind === "quota" && Number.isSafeInteger(details.expected) && typeof details.actual === "string"
        ? t("admission.DAILY_RUN_QUOTA_EXCEEDED", { limit: details.expected, timezone: details.actual }) : failure;
    case "INDUSTRY_CALCULATION_OUTSIDE_COVERAGE":
    case "FINANCIAL_CALCULATION_OUTSIDE_COVERAGE":
    case "FIELD_CALCULATION_OUTSIDE_COVERAGE": {
      if (details?.kind !== "coverage" || typeof details.expected !== "string"
        || !Object.hasOwn(researchEn.families, details.expected) || !Array.isArray(details.actual)) return failure;
      const family = t(`families.${details.expected as keyof typeof researchEn.families}`);
      if (details.actual.length === 0) return t("admission.coverageUnavailable", { family });
      return details.actual.length === 2 && details.actual.every(isDate)
        ? t("admission.coverage", { family, start: details.actual[0], end: details.actual[1] }) : failure;
    }
    case "INSUFFICIENT_CALCULATION_WARMUP":
      return details?.kind === "warmup" && typeof details.expected === "number" && Number.isSafeInteger(details.expected) && isDate(details.actual)
        ? t("admission.INSUFFICIENT_CALCULATION_WARMUP", { count: details.expected, date: details.actual }) : failure;
    case "RERUN_SOURCE_INVALID": {
      if (details?.kind !== "rerun_source") return failure;
      switch (details.reason) {
        case "unsupported_setting": return t("rerunIssues.unsupportedSetting");
        case "research_kind": return t("rerunIssues.researchKind");
        case "invalid_source": return t("rerunIssues.invalidSource");
        case "checkpoint_boundary": return isDate(details.expected) && isDate(details.actual)
          ? t("rerunIssues.checkpointBoundary", { expected: details.expected, actual: details.actual }) : failure;
        case "invalid_field": {
          switch (details.validation_type) {
            case "greater_than": case "greater_than_equal": case "less_than": case "less_than_equal":
            case "string_too_short": case "string_too_long": case "initial_cash":
              return typeof details.expected === "number" && Number.isFinite(details.expected)
                ? t(`rerunIssues.${details.validation_type}`, { expected: details.expected }) : failure;
            case "missing": case "int_type": case "string_type": case "string_pattern_mismatch": case "literal_error": case "natural_date":
              return t(`rerunIssues.${details.validation_type}`);
            default: return t("rerunIssues.invalidField");
          }
        }
      }
    }
    case "RUN_UNAVAILABLE": case "FOLDER_NOT_FOUND": case "RERUN_SOURCE_NOT_FOUND":
    case "DATA_NOT_READY": case "RESEARCH_PERIOD_OUTSIDE_COVERAGE": case "RESEARCH_PERIOD_HAS_NO_SESSIONS":
    case "FIELD_UNAVAILABLE_IN_CURRENT_DATA": case "RESEARCH_SESSION_EXCEEDS_WORKER_CAPACITY":
      return t(`admission.${issue.code}`);
    default:
      return ["formula", "exposure_expression"].includes(issue.field)
        ? formatFormulaDiagnostic({ code: issue.code, details: alphaDetails(details) }, locale) : failure;
  }
}

function isDate(value: unknown): value is string {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

export function researchIssueField(field: string, locale: InterfaceLocale = interfaceLocale()): string {
  const t = i18n.getFixedT(locale, "research");
  return Object.hasOwn(researchEn.issueFields, field)
    ? t(`issueFields.${field as keyof typeof researchEn.issueFields}`) : field;
}
import { z } from "zod";
