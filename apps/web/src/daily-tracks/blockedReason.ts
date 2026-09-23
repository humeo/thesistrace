import { i18n } from "../i18n";

const blockedCodes = {
  DATA_FAMILY_COVERAGE_UNAVAILABLE: "blockedReasons.DATA_FAMILY_COVERAGE_UNAVAILABLE",
  FINANCIAL_COVERAGE_UNAVAILABLE: "blockedReasons.FINANCIAL_COVERAGE_UNAVAILABLE",
  INDUSTRY_COVERAGE_UNAVAILABLE: "blockedReasons.INDUSTRY_COVERAGE_UNAVAILABLE",
  CAPACITY_EXCEEDED: "blockedReasons.CAPACITY_EXCEEDED",
  INFRASTRUCTURE_RETRIES_EXHAUSTED: "blockedReasons.INFRASTRUCTURE_RETRIES_EXHAUSTED",
  WORKER_LOST: "blockedReasons.WORKER_LOST",
  PUBLICATION_PREPARATION_ERROR: "blockedReasons.PUBLICATION_PREPARATION_ERROR",
  TRACKING_EXECUTION_ERROR: "blockedReasons.TRACKING_EXECUTION_ERROR",
  NUMERIC_CONTRACT_ERROR: "blockedReasons.NUMERIC_CONTRACT_ERROR",
  USER_STOPPED: "blockedReasons.USER_STOPPED",
} as const;

export function blockedReason(code: string | null): string {
  return code !== null && Object.hasOwn(blockedCodes, code)
    ? i18n.t(`daily:${blockedCodes[code as keyof typeof blockedCodes]}`)
    : i18n.t("daily:blockedUnknown");
}
