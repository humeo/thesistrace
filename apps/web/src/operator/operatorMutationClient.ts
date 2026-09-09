import { OperatorPageNotFoundError } from "./operatorDirectoryClient";
import { decodeFinancialRefreshProgress, type FinancialRefreshProgress } from "./financialRefreshProgress";

const pythonBoundaryWhitespace = /^[\u0009-\u000D\u001C-\u0020\u0085\u00A0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000]$/u;

export type InvitationMutationOperation = "issue" | "reissue";

export type MarketRefreshRequest = Readonly<{
  asOf: string;
  idempotencyKey: string;
}>;

export type MarketRefreshOperation = Readonly<{
  asOf: string;
  attemptCount: number;
  dataThroughSession: string | null;
  failureCode: string | null;
  idempotencyKey: string;
  kind: "market";
  lastFailureCode: string | null;
  lastRefreshAt: string | null;
  outcome: "published" | "no_change" | null;
  status: "accepted" | "running" | "succeeded" | "failed";
}>;

export type FinancialRefreshRequest = Readonly<{
  idempotencyKey: string;
  observationThroughSession: string;
}>;

export type FinancialRefreshOperation = Readonly<{
  progress: FinancialRefreshProgress | null;
  acceptedInstrumentCount: number | null;
  attemptCount: number;
  checkedNoStructuredChangeCount: number | null;
  dataThroughSession: string | null;
  discoveryGapCount: number | null;
  failedInstrumentCount: number | null;
  failureCode: string | null;
  financialCompleteThroughSession: string | null;
  idempotencyKey: string;
  kind: "financial";
  lastFailureCode: string | null;
  lastRefreshAt: string | null;
  matchedTriggerCount: number | null;
  observationThroughSession: string;
  outcome: "published" | "no_change" | "degraded" | "business_rejected" | "infrastructure_failed" | null;
  pendingInstrumentCount: number | null;
  status: "accepted" | "running" | "succeeded" | "failed";
}>;

export type IndustryRefreshRequest = Readonly<{
  idempotencyKey: string;
  observationThroughSession: string;
}>;

export type IndustryRefreshOperation = Readonly<{
  attemptCount: number;
  dataThroughSession: string | null;
  failureCode: string | null;
  idempotencyKey: string;
  kind: "industry";
  lastFailureCode: string | null;
  lastRefreshAt: string | null;
  observationThroughSession: string;
  outcome: "published" | "no_change" | "business_rejected" | "infrastructure_failed" | null;
  status: "accepted" | "running" | "succeeded" | "failed";
}>;

export type DataRefreshKind = "market" | "financial" | "industry";

type DataRefreshActionBase = Readonly<{
  kind: DataRefreshKind;
  sourceIdempotencyKey: string;
  target: string;
}>;

export type DataRefreshActionRequest =
  | (DataRefreshActionBase & Readonly<{ action: "cancel" }>)
  | (DataRefreshActionBase & Readonly<{
      action: "retry";
      newIdempotencyKey: string;
    }>);

export type DataRefreshActionReceipt = Readonly<{
  asOf: string | null;
  idempotencyKey: string;
  kind: DataRefreshKind;
  observationThroughSession: string | null;
  status: "accepted" | "cancelled";
}>;

export type OperatorMutationErrorCode =
  | "conflict"
  | "delivery-failed"
  | "data-not-ready"
  | "invalid-target"
  | "invalid-otp"
  | "invalid-proof"
  | "not-cancellable"
  | "not-retryable"
  | "protected-target"
  | "rate-limited"
  | "request-invalid"
  | "unavailable";

export class OperatorMutationError extends Error {
  readonly code: OperatorMutationErrorCode;

  constructor(code: OperatorMutationErrorCode) {
    super(code);
    this.name = "OperatorMutationError";
    this.code = code;
  }
}

export function isMarketRefreshIdempotencyKey(value: string): boolean {
  const characters = Array.from(value);
  return characters.length > 0
    && characters.length <= 512
    && !value.includes("\0")
    && !containsLoneSurrogate(value)
    && !hasPythonBoundaryWhitespace(characters);
}

export function isIsoResearchSession(value: unknown): value is string {
  if (
    typeof value !== "string"
    || !/^(?!0000)\d{4}-\d{2}-\d{2}$/.test(value)
  ) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

export async function confirmOperatorProof(
  operation: InvitationMutationOperation,
  email: string,
  otp: string,
  signal: AbortSignal,
): Promise<Readonly<{ expiresAt: string; proof: string }>> {
  const value = await operatorPost(
    "/api/auth/operator/proofs",
    {
      email,
      operation: `invitation.${operation}`,
      otp,
    },
    signal,
  );
  if (
    !hasExactKeys(value, ["expires_at", "proof"])
    || !isIsoTimestamp(value.expires_at)
    || typeof value.proof !== "string"
    || !isOpaqueProof(value.proof)
  ) {
    throw new OperatorMutationError("unavailable");
  }
  return { expiresAt: value.expires_at, proof: value.proof };
}

export async function submitInvitationMutation(
  operation: InvitationMutationOperation,
  email: string,
  proof: string,
  signal: AbortSignal,
): Promise<Readonly<{ email: string; invitationId: string }>> {
  const value = await operatorPost(
    `/api/auth/operator/invitations/${operation}`,
    { email, proof },
    signal,
  );
  if (
    !hasExactKeys(value, ["email", "invitation_id", "status"])
    || typeof value.email !== "string"
    || value.email !== value.email.trim().toLowerCase()
    || !isEmail(value.email)
    || typeof value.invitation_id !== "string"
    || !isUuid(value.invitation_id)
    || value.status !== "delivered"
  ) {
    throw new OperatorMutationError("unavailable");
  }
  return { email: value.email, invitationId: value.invitation_id };
}

export async function confirmSessionRevocationProof(
  researcherId: string,
  otp: string,
  signal: AbortSignal,
): Promise<Readonly<{ expiresAt: string; proof: string }>> {
  const value = await operatorPost(
    "/api/auth/operator/proofs",
    {
      operation: "researcher.sessions.revoke",
      otp,
      researcher_id: researcherId,
    },
    signal,
  );
  if (
    !hasExactKeys(value, ["expires_at", "proof"])
    || !isIsoTimestamp(value.expires_at)
    || typeof value.proof !== "string"
    || !isOpaqueProof(value.proof)
  ) {
    throw new OperatorMutationError("unavailable");
  }
  return { expiresAt: value.expires_at, proof: value.proof };
}

export async function confirmMarketRefreshProof(
  request: MarketRefreshRequest,
  signal: AbortSignal,
): Promise<Readonly<{ expiresAt: string; proof: string }>> {
  const value = await operatorPost(
    "/api/auth/operator/proofs",
    {
      as_of: request.asOf,
      idempotency_key: request.idempotencyKey,
      operation: "data.refresh.market.submit",
    },
    signal,
  );
  if (
    !hasExactKeys(value, ["expires_at", "proof"])
    || !isIsoTimestamp(value.expires_at)
    || typeof value.proof !== "string"
    || !isOpaqueProof(value.proof)
  ) {
    throw new OperatorMutationError("unavailable");
  }
  return { expiresAt: value.expires_at, proof: value.proof };
}

export async function submitMarketRefresh(
  request: MarketRefreshRequest,
  proof: string,
  signal: AbortSignal,
): Promise<MarketRefreshOperation> {
  return marketRefreshOperation(await operatorPost(
    "/api/operator/data/refreshes/market",
    {
      as_of: request.asOf,
      idempotency_key: request.idempotencyKey,
      proof,
    },
    signal,
  ));
}

export async function loadMarketRefresh(
  request: MarketRefreshRequest,
  signal: AbortSignal,
): Promise<MarketRefreshOperation> {
  const query = new URLSearchParams({
    as_of: request.asOf,
    idempotency_key: request.idempotencyKey,
  });
  return marketRefreshOperation(await operatorGet(
    `/api/operator/data/refreshes/market?${query.toString()}`,
    signal,
  ));
}

export async function confirmFinancialRefreshProof(
  request: FinancialRefreshRequest,
  signal: AbortSignal,
): Promise<Readonly<{ expiresAt: string; proof: string }>> {
  const value = await operatorPost(
    "/api/auth/operator/proofs",
    {
      idempotency_key: request.idempotencyKey,
      observation_through_session: request.observationThroughSession,
      operation: "data.refresh.financial.submit",
    },
    signal,
  );
  if (
    !hasExactKeys(value, ["expires_at", "proof"])
    || !isIsoTimestamp(value.expires_at)
    || typeof value.proof !== "string"
    || !isOpaqueProof(value.proof)
  ) {
    throw new OperatorMutationError("unavailable");
  }
  return { expiresAt: value.expires_at, proof: value.proof };
}

export async function submitFinancialRefresh(
  request: FinancialRefreshRequest,
  proof: string,
  signal: AbortSignal,
): Promise<FinancialRefreshOperation> {
  return financialRefreshOperation(await operatorPost(
    "/api/operator/data/refreshes/financial",
    {
      idempotency_key: request.idempotencyKey,
      observation_through_session: request.observationThroughSession,
      proof,
    },
    signal,
  ));
}

export async function loadFinancialRefresh(
  request: FinancialRefreshRequest,
  signal: AbortSignal,
): Promise<FinancialRefreshOperation> {
  const query = new URLSearchParams({
    idempotency_key: request.idempotencyKey,
    observation_through_session: request.observationThroughSession,
  });
  return financialRefreshOperation(await operatorGet(
    `/api/operator/data/refreshes/financial?${query.toString()}`,
    signal,
  ));
}

export async function confirmIndustryRefreshProof(
  request: IndustryRefreshRequest,
  signal: AbortSignal,
): Promise<Readonly<{ expiresAt: string; proof: string }>> {
  const value = await operatorPost(
    "/api/auth/operator/proofs",
    {
      idempotency_key: request.idempotencyKey,
      observation_through_session: request.observationThroughSession,
      operation: "data.refresh.industry.submit",
    },
    signal,
  );
  if (
    !hasExactKeys(value, ["expires_at", "proof"])
    || !isIsoTimestamp(value.expires_at)
    || typeof value.proof !== "string"
    || !isOpaqueProof(value.proof)
  ) {
    throw new OperatorMutationError("unavailable");
  }
  return { expiresAt: value.expires_at, proof: value.proof };
}

export async function submitIndustryRefresh(
  request: IndustryRefreshRequest,
  proof: string,
  signal: AbortSignal,
): Promise<IndustryRefreshOperation> {
  return industryRefreshOperation(await operatorPost(
    "/api/operator/data/refreshes/industry",
    {
      idempotency_key: request.idempotencyKey,
      observation_through_session: request.observationThroughSession,
      proof,
    },
    signal,
  ));
}

export async function loadIndustryRefresh(
  request: IndustryRefreshRequest,
  signal: AbortSignal,
): Promise<IndustryRefreshOperation> {
  const query = new URLSearchParams({
    idempotency_key: request.idempotencyKey,
    observation_through_session: request.observationThroughSession,
  });
  return industryRefreshOperation(await operatorGet(
    `/api/operator/data/refreshes/industry?${query.toString()}`,
    signal,
  ));
}

export async function confirmDataRefreshActionProof(
  request: DataRefreshActionRequest,
  otp: string,
  signal: AbortSignal,
): Promise<Readonly<{ expiresAt: string; proof: string }>> {
  let body: Readonly<Record<string, string>>;
  if (request.action === "cancel") {
    body = {
      kind: request.kind,
      operation: "data.refresh.cancel",
      otp,
      source_idempotency_key: request.sourceIdempotencyKey,
      target: request.target,
    };
  } else {
    body = {
      kind: request.kind,
      new_idempotency_key: request.newIdempotencyKey,
      operation: "data.refresh.retry",
      otp,
      source_idempotency_key: request.sourceIdempotencyKey,
      target: request.target,
    };
  }
  const value = await operatorPost(
    "/api/auth/operator/proofs",
    body,
    signal,
  );
  if (
    !hasExactKeys(value, ["expires_at", "proof"])
    || !isIsoTimestamp(value.expires_at)
    || typeof value.proof !== "string"
    || !isOpaqueProof(value.proof)
  ) {
    throw new OperatorMutationError("unavailable");
  }
  return { expiresAt: value.expires_at, proof: value.proof };
}

export async function submitDataRefreshAction(
  request: DataRefreshActionRequest,
  proof: string,
  signal: AbortSignal,
): Promise<DataRefreshActionReceipt> {
  let body: Readonly<Record<string, string>>;
  if (request.action === "cancel") {
    body = {
      kind: request.kind,
      proof,
      source_idempotency_key: request.sourceIdempotencyKey,
      target: request.target,
    };
  } else {
    body = {
      kind: request.kind,
      new_idempotency_key: request.newIdempotencyKey,
      proof,
      source_idempotency_key: request.sourceIdempotencyKey,
      target: request.target,
    };
  }
  return dataRefreshActionReceipt(
    await operatorPost(
      `/api/operator/data/refreshes/${request.action}`,
      body,
      signal,
    ),
    request,
  );
}

export async function submitSessionRevocation(
  researcherId: string,
  proof: string,
  signal: AbortSignal,
): Promise<Readonly<{
  researcherId: string;
  revokedSessionCount: number;
}>> {
  const value = await operatorPost(
    "/api/auth/operator/researchers/sessions/revoke",
    { proof, researcher_id: researcherId },
    signal,
  );
  if (
    !hasExactKeys(value, [
      "researcher_id",
      "revoked_session_count",
      "status",
    ])
    || value.researcher_id !== researcherId
    || typeof value.revoked_session_count !== "number"
    || !Number.isSafeInteger(value.revoked_session_count)
    || value.revoked_session_count < 0
    || (value.status !== "updated" && value.status !== "no_change")
  ) {
    throw new OperatorMutationError("unavailable");
  }
  return {
    researcherId: value.researcher_id,
    revokedSessionCount: value.revoked_session_count,
  };
}

async function operatorPost(
  path: string,
  body: Readonly<Record<string, string>>,
  signal: AbortSignal,
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, {
      body: JSON.stringify(body),
      credentials: "same-origin",
      headers: { "content-type": "application/json" },
      method: "POST",
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new OperatorMutationError("unavailable");
  }
  if (response.status === 404) throw new OperatorPageNotFoundError();
  if (!response.ok) {
    throw new OperatorMutationError(await responseErrorCode(response));
  }
  try {
    return await response.json();
  } catch {
    throw new OperatorMutationError("unavailable");
  }
}

async function operatorGet(path: string, signal: AbortSignal): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, {
      credentials: "same-origin",
      headers: { accept: "application/json" },
      method: "GET",
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new OperatorMutationError("unavailable");
  }
  if (response.status === 404) throw new OperatorPageNotFoundError();
  if (!response.ok) {
    throw new OperatorMutationError(await responseErrorCode(response));
  }
  try {
    return await response.json();
  } catch {
    throw new OperatorMutationError("unavailable");
  }
}

async function responseErrorCode(
  response: Response,
): Promise<OperatorMutationErrorCode> {
  let code: unknown;
  try {
    const value: unknown = await response.json();
    code = isRecord(value) ? value.code : undefined;
  } catch {
    return "unavailable";
  }
  if (code === "OPERATOR_CODE_INVALID") return "invalid-otp";
  if (code === "OPERATOR_PROOF_INVALID") return "invalid-proof";
  if (code === "OPERATOR_INVITATION_CONFLICT") return "conflict";
  if (code === "OPERATOR_INVITATION_DELIVERY_FAILED") return "delivery-failed";
  if (code === "OPERATOR_SESSION_TARGET_PROTECTED") return "protected-target";
  if (code === "OPERATOR_SESSION_TARGET_INVALID") return "invalid-target";
  if (code === "OPERATOR_REQUEST_INVALID") return "request-invalid";
  if (code === "DATA_NOT_READY") return "data-not-ready";
  if (code === "IDEMPOTENCY_KEY_CONFLICT") return "conflict";
  if (code === "REFRESH_NOT_CANCELLABLE") return "not-cancellable";
  if (code === "REFRESH_NOT_RETRYABLE") return "not-retryable";
  if (code === "REFRESH_NOT_FOUND") return "invalid-target";
  if (code === "REFRESH_TARGET_CONFLICT") return "invalid-target";
  if (code === "AUTH_RATE_LIMITED") return "rate-limited";
  return "unavailable";
}

function hasExactKeys(
  value: unknown,
  keys: readonly string[],
): value is Record<string, unknown> {
  return isRecord(value)
    && Object.keys(value).sort().join(",") === [...keys].sort().join(",");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isIsoTimestamp(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime())
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value);
}

function dataRefreshActionReceipt(
  value: unknown,
  request: DataRefreshActionRequest,
): DataRefreshActionReceipt {
  if (
    !hasExactKeys(value, [
      "as_of",
      "idempotency_key",
      "kind",
      "observation_through_session",
      "status",
    ])
    || !isDataRefreshKind(value.kind)
    || value.kind !== request.kind
    || typeof value.idempotency_key !== "string"
    || value.idempotency_key !== (request.action === "cancel"
      ? request.sourceIdempotencyKey
      : request.newIdempotencyKey)
    || (value.status !== "accepted" && value.status !== "cancelled")
    || value.status !== (request.action === "cancel" ? "cancelled" : "accepted")
    || (value.as_of !== null && !isIsoTimestamp(value.as_of))
    || (value.observation_through_session !== null
      && !isIsoResearchSession(value.observation_through_session))
    || !actionTargetMatches(
      request,
      value.as_of,
      value.observation_through_session,
    )
  ) {
    throw new OperatorMutationError("unavailable");
  }
  return {
    asOf: value.as_of,
    idempotencyKey: value.idempotency_key,
    kind: value.kind,
    observationThroughSession: value.observation_through_session,
    status: value.status,
  };
}

function isDataRefreshKind(value: unknown): value is DataRefreshKind {
  return value === "market" || value === "financial" || value === "industry";
}

function actionTargetMatches(
  request: DataRefreshActionRequest,
  asOf: unknown,
  observationThroughSession: unknown,
): asOf is string | null {
  if (request.kind === "market") {
    return isIsoTimestamp(asOf)
      && observationThroughSession === null
      && new Date(asOf).getTime() === new Date(request.target).getTime();
  }
  return asOf === null && observationThroughSession === request.target;
}

function marketRefreshOperation(value: unknown): MarketRefreshOperation {
  const keys = [
    "as_of",
    "attempt_count",
    "data_through_session",
    "failure_code",
    "idempotency_key",
    "kind",
    "last_failure_code",
    "last_refresh_at",
    "outcome",
    "status",
  ] as const;
  if (
    !hasExactKeys(value, keys)
    || !isIsoTimestamp(value.as_of)
    || typeof value.attempt_count !== "number"
    || !Number.isSafeInteger(value.attempt_count)
    || value.attempt_count < 0
    || (value.data_through_session !== null
      && (typeof value.data_through_session !== "string"
        || !/^\d{4}-\d{2}-\d{2}$/.test(value.data_through_session)))
    || (value.failure_code !== null && typeof value.failure_code !== "string")
    || typeof value.idempotency_key !== "string"
    || !isMarketRefreshIdempotencyKey(value.idempotency_key)
    || value.kind !== "market"
    || (value.last_failure_code !== null
      && typeof value.last_failure_code !== "string")
    || (value.last_refresh_at !== null && !isIsoTimestamp(value.last_refresh_at))
    || (value.outcome !== null
      && value.outcome !== "published"
      && value.outcome !== "no_change")
    || (value.status !== "accepted"
      && value.status !== "running"
      && value.status !== "succeeded"
      && value.status !== "failed")
    || (value.status === "succeeded" && value.outcome === null)
    || (value.status !== "succeeded" && value.outcome !== null)
    || (value.status === "failed" && value.failure_code === null)
    || (value.status !== "failed" && value.failure_code !== null)
  ) {
    throw new OperatorMutationError("unavailable");
  }
  return {
    asOf: value.as_of,
    attemptCount: value.attempt_count,
    dataThroughSession: value.data_through_session,
    failureCode: value.failure_code,
    idempotencyKey: value.idempotency_key,
    kind: value.kind,
    lastFailureCode: value.last_failure_code,
    lastRefreshAt: value.last_refresh_at,
    outcome: value.outcome,
    status: value.status,
  };
}

function financialRefreshOperation(value: unknown): FinancialRefreshOperation {
  const keys = [
    "progress",
    "accepted_instrument_count",
    "attempt_count",
    "checked_no_structured_change_count",
    "data_through_session",
    "discovery_gap_count",
    "failed_instrument_count",
    "failure_code",
    "financial_complete_through_session",
    "idempotency_key",
    "kind",
    "last_failure_code",
    "last_refresh_at",
    "matched_trigger_count",
    "observation_through_session",
    "outcome",
    "pending_instrument_count",
    "status",
  ] as const;
  if (
    !hasExactKeys(value, keys)
    || !isOptionalCount(value.accepted_instrument_count)
    || !isCount(value.attempt_count)
    || !isOptionalCount(value.checked_no_structured_change_count)
    || !isOptionalSession(value.data_through_session)
    || !isOptionalCount(value.discovery_gap_count)
    || !isOptionalCount(value.failed_instrument_count)
    || (value.failure_code !== null && typeof value.failure_code !== "string")
    || !isOptionalSession(value.financial_complete_through_session)
    || typeof value.idempotency_key !== "string"
    || !isMarketRefreshIdempotencyKey(value.idempotency_key)
    || value.kind !== "financial"
    || (value.last_failure_code !== null && typeof value.last_failure_code !== "string")
    || (value.last_refresh_at !== null && !isIsoTimestamp(value.last_refresh_at))
    || !isOptionalCount(value.matched_trigger_count)
    || !isIsoResearchSession(value.observation_through_session)
    || (value.outcome !== null
      && value.outcome !== "published"
      && value.outcome !== "no_change"
      && value.outcome !== "degraded"
      && value.outcome !== "business_rejected"
      && value.outcome !== "infrastructure_failed")
    || !isOptionalCount(value.pending_instrument_count)
    || (value.status !== "accepted"
      && value.status !== "running"
      && value.status !== "succeeded"
      && value.status !== "failed")
    || (value.status === "succeeded"
      && !["published", "no_change", "degraded"].includes(String(value.outcome)))
    || (value.status === "failed"
      && !["business_rejected", "infrastructure_failed"].includes(String(value.outcome)))
    || (["accepted", "running"].includes(String(value.status)) && value.outcome !== null)
    || (value.status === "failed" && value.failure_code === null)
    || (value.status !== "failed" && value.failure_code !== null)
  ) {
    throw new OperatorMutationError("unavailable");
  }
  return {
    acceptedInstrumentCount: value.accepted_instrument_count,
    progress: financialProgress(value.progress),
    attemptCount: value.attempt_count,
    checkedNoStructuredChangeCount: value.checked_no_structured_change_count,
    dataThroughSession: value.data_through_session,
    discoveryGapCount: value.discovery_gap_count,
    failedInstrumentCount: value.failed_instrument_count,
    failureCode: value.failure_code,
    financialCompleteThroughSession: value.financial_complete_through_session,
    idempotencyKey: value.idempotency_key,
    kind: value.kind,
    lastFailureCode: value.last_failure_code,
    lastRefreshAt: value.last_refresh_at,
    matchedTriggerCount: value.matched_trigger_count,
    observationThroughSession: value.observation_through_session,
    outcome: value.outcome,
    pendingInstrumentCount: value.pending_instrument_count,
    status: value.status,
  };
}

function financialProgress(value: unknown): FinancialRefreshProgress | null {
  try {
    return decodeFinancialRefreshProgress(value);
  } catch {
    throw new OperatorMutationError("unavailable");
  }
}

function industryRefreshOperation(value: unknown): IndustryRefreshOperation {
  const keys = [
    "attempt_count",
    "data_through_session",
    "failure_code",
    "idempotency_key",
    "kind",
    "last_failure_code",
    "last_refresh_at",
    "observation_through_session",
    "outcome",
    "status",
  ] as const;
  if (
    !hasExactKeys(value, keys)
    || !isCount(value.attempt_count)
    || !isOptionalSession(value.data_through_session)
    || (value.failure_code !== null && typeof value.failure_code !== "string")
    || typeof value.idempotency_key !== "string"
    || !isMarketRefreshIdempotencyKey(value.idempotency_key)
    || value.kind !== "industry"
    || (value.last_failure_code !== null && typeof value.last_failure_code !== "string")
    || (value.last_refresh_at !== null && !isIsoTimestamp(value.last_refresh_at))
    || !isIsoResearchSession(value.observation_through_session)
    || (value.outcome !== null
      && value.outcome !== "published"
      && value.outcome !== "no_change"
      && value.outcome !== "business_rejected"
      && value.outcome !== "infrastructure_failed")
    || (value.status !== "accepted"
      && value.status !== "running"
      && value.status !== "succeeded"
      && value.status !== "failed")
    || (value.status === "succeeded"
      && value.outcome !== "published"
      && value.outcome !== "no_change")
    || (value.status === "failed"
      && value.outcome !== "business_rejected"
      && value.outcome !== "infrastructure_failed")
    || (["accepted", "running"].includes(String(value.status)) && value.outcome !== null)
    || (value.status === "failed" && value.failure_code === null)
    || (value.status !== "failed" && value.failure_code !== null)
  ) {
    throw new OperatorMutationError("unavailable");
  }
  return {
    attemptCount: value.attempt_count,
    dataThroughSession: value.data_through_session,
    failureCode: value.failure_code,
    idempotencyKey: value.idempotency_key,
    kind: value.kind,
    lastFailureCode: value.last_failure_code,
    lastRefreshAt: value.last_refresh_at,
    observationThroughSession: value.observation_through_session,
    outcome: value.outcome,
    status: value.status,
  };
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isOptionalCount(value: unknown): value is number | null {
  return value === null || isCount(value);
}

function isOptionalSession(value: unknown): value is string | null {
  return value === null || isIsoResearchSession(value);
}

function isOpaqueProof(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.[A-Za-z0-9_-]{43}$/i
    .test(value);
}

function hasPythonBoundaryWhitespace(characters: readonly string[]): boolean {
  const first = characters[0];
  const last = characters.at(-1);
  return (first !== undefined && pythonBoundaryWhitespace.test(first))
    || (last !== undefined && pythonBoundaryWhitespace.test(last));
}

function containsLoneSurrogate(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const codeUnit = value.charCodeAt(index);
    if (codeUnit >= 0xD800 && codeUnit <= 0xDBFF) {
      const next = value.charCodeAt(index + 1);
      if (next < 0xDC00 || next > 0xDFFF) return true;
      index += 1;
    } else if (codeUnit >= 0xDC00 && codeUnit <= 0xDFFF) {
      return true;
    }
  }
  return false;
}

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
    .test(value);
}

function isEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}
