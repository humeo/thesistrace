import { i18n, interfaceLocale, type InterfaceLocale } from "../i18n";
import { researchEn } from "../i18n/messages/research";
import { diagnosticDetailsSchema, sourceRangeSchema, formatFormulaDiagnostic, type DiagnosticDetails, type FormulaDiagnostic } from "./diagnostics";

type AdmissionDetails = { kind: "quota" | "coverage" | "warmup"; expected: string | number; actual: string | string[] };
export type ResearchRunAdmissionIssue = {
  code: string;
  field: string;
  message: string;
  severity: "error";
  range: FormulaDiagnostic["range"] | null;
  details: DiagnosticDetails | AdmissionDetails | null;
};

const issueSchema: z.ZodType<ResearchRunAdmissionIssue> = z.object({
  code: z.string(), field: z.string(), message: z.string(), severity: z.literal("error"),
  range: sourceRangeSchema.nullable(),
  details: z.union([
    diagnosticDetailsSchema,
    z.object({ kind: z.enum(["quota", "coverage", "warmup"]), expected: z.union([z.string(), z.number()]), actual: z.union([z.string(), z.array(z.string())]) }),
  ]).nullable(),
});

export function readResearchIssues(value: unknown): ResearchRunAdmissionIssue[] {
  return z.array(issueSchema).parse(value);
}

export function alphaDetails(details: ResearchRunAdmissionIssue["details"]): DiagnosticDetails | null {
  if (details == null || ["quota", "coverage", "warmup"].includes(details.kind)) return null;
  return details as DiagnosticDetails;
}

export function formatResearchIssue(issue: ResearchRunAdmissionIssue, locale: InterfaceLocale = interfaceLocale()): string {
  const t = i18n.getFixedT(locale, "research");
  const failure = t("admission.unavailable");
  const details = issue.details;
  switch (issue.code) {
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
    case "RUN_UNAVAILABLE": case "FOLDER_NOT_FOUND": case "RERUN_SOURCE_NOT_FOUND": case "RERUN_SOURCE_INVALID":
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
