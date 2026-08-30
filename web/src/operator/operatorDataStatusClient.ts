import {
  OperatorPageNotFoundError,
  OperatorPageUnavailableError,
} from "./operatorDirectoryClient";
import { isIsoResearchSession, isMarketRefreshIdempotencyKey } from "./operatorMutationClient";

export type DataRefreshKind = "market" | "financial" | "industry";
export type DataRefreshStatus = "accepted" | "running" | "succeeded" | "failed" | "cancelled";
export type DataRefreshOutcome =
  | "published"
  | "no_change"
  | "degraded"
  | "business_rejected"
  | "infrastructure_failed";

export type DatasetOperationalHead = Readonly<{
  dataIdentity: string | null;
  preparedAt: string | null;
  dataThroughSession: string | null;
  marketResearchReadiness: boolean;
  benchmarkResearchReadiness: boolean;
  financialResearchReadiness: "ready" | "ready_with_pending" | "ready_with_gaps" | "not_ready";
  industryResearchReadiness: boolean;
}>;

export type DataOperatorWorkerStatus = Readonly<{
  available: boolean;
  lastHeartbeatAt: string | null;
}>;

export type DataRefreshOperationalStatus = Readonly<{
  idempotencyKey: string;
  kind: DataRefreshKind;
  status: DataRefreshStatus;
  outcome: DataRefreshOutcome | null;
  asOf: string | null;
  observationThroughSession: string | null;
  phase: string | null;
  attemptCount: number;
  lastHeartbeatAt: string | null;
  dataThroughSession: string | null;
  lastRefreshAt: string | null;
  financialCompleteThroughSession: string | null;
  matchedTriggerCount: number | null;
  checkedNoStructuredChangeCount: number | null;
  acceptedInstrumentCount: number | null;
  failedInstrumentCount: number | null;
  pendingInstrumentCount: number | null;
  discoveryGapCount: number | null;
  failureCode: string | null;
  lastFailureCode: string | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  updatedAt: string;
}>;

export type DatasetOperationalStatus = Readonly<{
  head: DatasetOperationalHead;
  worker: DataOperatorWorkerStatus;
  latestByKind: readonly DataRefreshOperationalStatus[];
  operations: readonly DataRefreshOperationalStatus[];
  nextCursor: string | null;
}>;

const operationKeys = [
  "idempotency_key",
  "kind",
  "status",
  "outcome",
  "as_of",
  "observation_through_session",
  "phase",
  "attempt_count",
  "last_heartbeat_at",
  "data_through_session",
  "last_refresh_at",
  "financial_complete_through_session",
  "matched_trigger_count",
  "checked_no_structured_change_count",
  "accepted_instrument_count",
  "failed_instrument_count",
  "pending_instrument_count",
  "discovery_gap_count",
  "failure_code",
  "last_failure_code",
  "created_at",
  "started_at",
  "finished_at",
  "updated_at",
] as const;

const phases = new Set([
  "claim",
  "current_head",
  "market",
  "validation",
  "benchmark",
  "materialization",
  "candidate_validation",
  "publication",
  "financial",
  "industry",
]);

export async function loadDatasetOperationalStatus(
  cursor: string | null,
  signal: AbortSignal,
): Promise<DatasetOperationalStatus> {
  const suffix = cursor === null ? "" : `?cursor=${encodeURIComponent(cursor)}`;
  let response: Response;
  try {
    response = await fetch(`/api/operator/data/status${suffix}`, {
      credentials: "same-origin",
      headers: { accept: "application/json" },
      method: "GET",
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new OperatorPageUnavailableError();
  }
  if (response.status === 404) throw new OperatorPageNotFoundError();
  if (!response.ok) throw new OperatorPageUnavailableError();
  try {
    return decodeDatasetOperationalStatus(await response.json());
  } catch (error) {
    if (error instanceof OperatorPageNotFoundError) throw error;
    throw new OperatorPageUnavailableError();
  }
}

export function decodeDatasetOperationalStatus(value: unknown): DatasetOperationalStatus {
  if (
    !hasExactKeys(value, ["head", "worker", "latest_by_kind", "operations", "next_cursor"])
    || !Array.isArray(value.latest_by_kind)
    || !Array.isArray(value.operations)
    || value.operations.length > 50
  ) invalid();
  const head = decodeHead(value.head);
  const worker = decodeWorker(value.worker);
  const latestByKind = value.latest_by_kind.map(decodeOperation);
  const operations = value.operations.map(decodeOperation);
  const kindOrder: Record<DataRefreshKind, number> = { market: 0, financial: 1, industry: 2 };
  if (
    latestByKind.length > 3
    || latestByKind.some((item, index) => (
      latestByKind.findIndex((candidate) => candidate.kind === item.kind) !== index
      || (index > 0 && kindOrder[latestByKind[index - 1]!.kind] >= kindOrder[item.kind])
    ))
  ) invalid();
  const nextCursor = decodeCursor(value.next_cursor);
  return { head, worker, latestByKind, operations, nextCursor };
}

function decodeWorker(value: unknown): DataOperatorWorkerStatus {
  if (
    !hasExactKeys(value, ["available", "last_heartbeat_at"])
    || typeof value.available !== "boolean"
    || !isOptionalTimestamp(value.last_heartbeat_at)
    || (value.available && value.last_heartbeat_at === null)
  ) invalid();
  return {
    available: value.available,
    lastHeartbeatAt: value.last_heartbeat_at,
  };
}

function decodeHead(value: unknown): DatasetOperationalHead {
  if (
    !hasExactKeys(value, [
      "data_identity",
      "prepared_at",
      "data_through_session",
      "market_research_readiness",
      "benchmark_research_readiness",
      "financial_research_readiness",
      "industry_research_readiness",
    ])
    || (value.data_identity !== null
      && (typeof value.data_identity !== "string" || !/^[0-9a-f]{64}$/.test(value.data_identity)))
    || !isOptionalTimestamp(value.prepared_at)
    || !isOptionalSession(value.data_through_session)
    || typeof value.market_research_readiness !== "boolean"
    || typeof value.benchmark_research_readiness !== "boolean"
    || !isFinancialReadiness(value.financial_research_readiness)
    || typeof value.industry_research_readiness !== "boolean"
    || !(
      (value.data_identity === null
        && value.prepared_at === null
        && value.data_through_session === null)
      || (value.data_identity !== null
        && value.prepared_at !== null
        && value.data_through_session !== null)
    )
  ) invalid();
  return {
    dataIdentity: value.data_identity,
    preparedAt: value.prepared_at,
    dataThroughSession: value.data_through_session,
    marketResearchReadiness: value.market_research_readiness,
    benchmarkResearchReadiness: value.benchmark_research_readiness,
    financialResearchReadiness: value.financial_research_readiness,
    industryResearchReadiness: value.industry_research_readiness,
  };
}

function decodeOperation(value: unknown): DataRefreshOperationalStatus {
  if (
    !hasExactKeys(value, operationKeys)
    || typeof value.idempotency_key !== "string"
    || !isMarketRefreshIdempotencyKey(value.idempotency_key)
    || !isKind(value.kind)
    || !isStatus(value.status)
    || !isOptionalOutcome(value.outcome)
    || !isOptionalTimestamp(value.as_of)
    || !isOptionalSession(value.observation_through_session)
    || (value.phase !== null && (typeof value.phase !== "string" || !phases.has(value.phase)))
    || !isCount(value.attempt_count)
    || !isOptionalTimestamp(value.last_heartbeat_at)
    || !isOptionalSession(value.data_through_session)
    || !isOptionalTimestamp(value.last_refresh_at)
    || !isOptionalSession(value.financial_complete_through_session)
    || !isOptionalCount(value.matched_trigger_count)
    || !isOptionalCount(value.checked_no_structured_change_count)
    || !isOptionalCount(value.accepted_instrument_count)
    || !isOptionalCount(value.failed_instrument_count)
    || !isOptionalCount(value.pending_instrument_count)
    || !isOptionalCount(value.discovery_gap_count)
    || !isOptionalCode(value.failure_code)
    || !isOptionalCode(value.last_failure_code)
    || !isIsoTimestamp(value.created_at)
    || !isOptionalTimestamp(value.started_at)
    || !isOptionalTimestamp(value.finished_at)
    || !isIsoTimestamp(value.updated_at)
    || !targetMatchesKind(value.kind, value.as_of, value.observation_through_session)
    || !stateRelationshipIsValid(value)
    || !financialFieldsMatchKind(value)
  ) invalid();
  return {
    idempotencyKey: value.idempotency_key,
    kind: value.kind,
    status: value.status,
    outcome: value.outcome,
    asOf: value.as_of,
    observationThroughSession: value.observation_through_session,
    phase: value.phase,
    attemptCount: value.attempt_count,
    lastHeartbeatAt: value.last_heartbeat_at,
    dataThroughSession: value.data_through_session,
    lastRefreshAt: value.last_refresh_at,
    financialCompleteThroughSession: value.financial_complete_through_session,
    matchedTriggerCount: value.matched_trigger_count,
    checkedNoStructuredChangeCount: value.checked_no_structured_change_count,
    acceptedInstrumentCount: value.accepted_instrument_count,
    failedInstrumentCount: value.failed_instrument_count,
    pendingInstrumentCount: value.pending_instrument_count,
    discoveryGapCount: value.discovery_gap_count,
    failureCode: value.failure_code,
    lastFailureCode: value.last_failure_code,
    createdAt: value.created_at,
    startedAt: value.started_at,
    finishedAt: value.finished_at,
    updatedAt: value.updated_at,
  };
}

function stateRelationshipIsValid(value: Record<string, unknown>): boolean {
  const status = value.status as DataRefreshStatus;
  const kind = value.kind as DataRefreshKind;
  const outcome = value.outcome as DataRefreshOutcome | null;
  if (status === "accepted") {
    return outcome === null && value.phase === null && value.failure_code === null
      && value.finished_at === null;
  }
  if (status === "running") {
    return outcome === null && value.phase !== null && value.last_heartbeat_at !== null
      && Number(value.attempt_count) > 0 && value.failure_code === null
      && value.started_at !== null && value.finished_at === null;
  }
  if (status === "cancelled") {
    return outcome === null && value.failure_code === null && value.finished_at !== null;
  }
  if (status === "failed") {
    return value.phase !== null && value.last_heartbeat_at !== null
      && value.started_at !== null && value.finished_at !== null
      && value.failure_code !== null
      && (kind === "market"
        ? outcome === null
        : outcome === "business_rejected" || outcome === "infrastructure_failed");
  }
  return value.phase !== null && value.last_heartbeat_at !== null
    && value.started_at !== null && value.finished_at !== null
    && value.failure_code === null
    && value.data_through_session !== null && value.last_refresh_at !== null
    && (kind === "financial"
      ? outcome === "published" || outcome === "no_change" || outcome === "degraded"
      : outcome === "published" || outcome === "no_change");
}

function financialFieldsMatchKind(value: Record<string, unknown>): boolean {
  const fields = [
    value.financial_complete_through_session,
    value.matched_trigger_count,
    value.checked_no_structured_change_count,
    value.accepted_instrument_count,
    value.failed_instrument_count,
    value.pending_instrument_count,
    value.discovery_gap_count,
  ];
  if (value.kind !== "financial") return fields.every((field) => field === null);
  if (value.status === "succeeded") return fields.every((field) => field !== null);
  if (value.status === "failed") {
    return value.financial_complete_through_session === null
      && (fields.slice(1).every((field) => field === null)
        || fields.slice(1).every((field) => field !== null));
  }
  return fields.every((field) => field === null);
}

function targetMatchesKind(
  kind: DataRefreshKind,
  asOf: unknown,
  observationThroughSession: unknown,
): boolean {
  return kind === "market"
    ? asOf !== null && observationThroughSession === null
    : asOf === null && observationThroughSession !== null;
}

function isKind(value: unknown): value is DataRefreshKind {
  return value === "market" || value === "financial" || value === "industry";
}

function isStatus(value: unknown): value is DataRefreshStatus {
  return value === "accepted" || value === "running" || value === "succeeded"
    || value === "failed" || value === "cancelled";
}

function isOptionalOutcome(value: unknown): value is DataRefreshOutcome | null {
  return value === null || value === "published" || value === "no_change"
    || value === "degraded" || value === "business_rejected"
    || value === "infrastructure_failed";
}

function isFinancialReadiness(
  value: unknown,
): value is DatasetOperationalHead["financialResearchReadiness"] {
  return value === "ready" || value === "ready_with_pending"
    || value === "ready_with_gaps" || value === "not_ready";
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isOptionalCount(value: unknown): value is number | null {
  return value === null || isCount(value);
}

function isOptionalCode(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && value.length > 0 && value.length <= 256);
}

function isOptionalSession(value: unknown): value is string | null {
  return value === null || isIsoResearchSession(value);
}

function isIsoTimestamp(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime())
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value);
}

function isOptionalTimestamp(value: unknown): value is string | null {
  return value === null || isIsoTimestamp(value);
}

function decodeCursor(value: unknown): string | null {
  if (value === null) return null;
  if (typeof value !== "string" || value.length === 0 || value.length > 1_024) invalid();
  return value;
}

function hasExactKeys(
  value: unknown,
  keys: readonly string[],
): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).sort().join(",") === [...keys].sort().join(",");
}

function invalid(): never {
  throw new Error("Dataset operational status response is invalid");
}
