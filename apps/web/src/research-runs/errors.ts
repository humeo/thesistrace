import { z } from "zod";
import { i18n } from "../i18n";
import { formatNumber } from "../i18n/format";

export type RunError = { code: "loadError" | "trackingError" | "trackingExists" | "trackingResult" | "trackingNotCompleted" | "trackingStrategy" | "trackingRequestConflict" }
  | { code: "trackingLimit"; limit: number };
export type CancelError = "cancelError" | "cancelBatch" | "cancelConflict" | "cancelState";
export type HttpActionError = { status: number | null };
const errorSchema = z.object({ detail: z.object({ code: z.string(), limit: z.number().int().nonnegative().safe().nullable().optional() }) });

export async function readTrackingError(response: Response): Promise<RunError> {
  if (response.status !== 409) return { code: "trackingError" };
  const result = errorSchema.safeParse(await response.json().catch(() => null));
  if (!result.success) return { code: "trackingError" };
  const detail = result.data.detail;
  switch (detail.code) {
    case "ACTIVE_DAILY_TRACK_LIMIT_REACHED": return detail.limit == null ? { code: "trackingError" } : { code: "trackingLimit", limit: detail.limit };
    case "DAILY_TRACK_ALREADY_EXISTS": return { code: "trackingExists" };
    case "TRACKING_RESULT_UNAVAILABLE": return { code: "trackingResult" };
    case "TRACKING_RUN_NOT_SUCCEEDED": return { code: "trackingNotCompleted" };
    case "TRACKING_STRATEGY_REQUIRED": return { code: "trackingStrategy" };
    case "TRACKING_REQUEST_CONFLICT": return { code: "trackingRequestConflict" };
    default: return { code: "trackingError" };
  }
}

export async function readCancelError(response: Response): Promise<CancelError> {
  if (response.status !== 409) return "cancelError";
  const result = errorSchema.safeParse(await response.json().catch(() => null));
  if (!result.success) return "cancelError";
  switch (result.data.detail.code) {
    case "BATCH_CANCELLATION_REQUIRED": return "cancelBatch";
    case "CANCEL_REQUEST_CONFLICT": return "cancelConflict";
    case "RUN_NOT_CANCELLABLE": return "cancelState";
    default: return "cancelError";
  }
}

export function formatRunError(error: RunError): string {
  return error.code === "trackingLimit" ? i18n.t("runs:trackingLimit", { limit: formatNumber(error.limit) }) : i18n.t(`runs:${error.code}`);
}

const executionFailures = {
  "InsufficientCalculationWarmup": "failures.InsufficientCalculationWarmup",
  "SelectedDataInvalid": "failures.SelectedDataInvalid",
  "ResourceExhausted": "failures.ResourceExhausted",
  "InfrastructureUnavailable": "failures.InfrastructureUnavailable",
  "CheckpointIntegrityFailure": "failures.CheckpointIntegrityFailure",
  "ContractMismatch": "failures.ContractMismatch",
  "CalculationFailure": "failures.CalculationFailure",
  "PermanentExecutionFailure": "failures.PermanentExecutionFailure",
  "WorkerLost": "failures.WorkerLost",
  "UserCancelled": "failures.UserCancelled"
} as const;

export function formatExecutionFailure(reason: string): string {
  return Object.hasOwn(executionFailures, reason) ? i18n.t(`runs:${executionFailures[reason as keyof typeof executionFailures]}`) : i18n.t("runs:executionFailure");
}

export type OrganizationError = HttpActionError | { code: "folderMissing" };
export async function readOrganizationError(response: Response): Promise<OrganizationError> {
  const result = errorSchema.safeParse(await response.json().catch(() => null));
  return response.status === 409 && result.success && result.data.detail.code === "FOLDER_NOT_FOUND"
    ? { code: "folderMissing" } : { status: response.status };
}

export type BatchCancelError = "cancelError" | "cancelConflict" | "cancelRequestConflict";
export async function readBatchCancelError(response: Response): Promise<BatchCancelError> {
  if (response.status !== 409) return "cancelError";
  const result = errorSchema.safeParse(await response.json().catch(() => null));
  if (!result.success) return "cancelError";
  switch (result.data.detail.code) {
    case "BATCH_NOT_CANCELLABLE": return "cancelConflict";
    case "BATCH_CANCEL_REQUEST_CONFLICT": return "cancelRequestConflict";
    default: return "cancelError";
  }
}
