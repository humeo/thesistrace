import { OperatorPageNotFoundError } from "./operatorDirectoryClient";

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

export type OperatorMutationErrorCode =
  | "conflict"
  | "delivery-failed"
  | "data-not-ready"
  | "invalid-target"
  | "invalid-password"
  | "invalid-proof"
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

export async function confirmOperatorProof(
  operation: InvitationMutationOperation,
  email: string,
  password: string,
  signal: AbortSignal,
): Promise<Readonly<{ expiresAt: string; proof: string }>> {
  const value = await operatorPost(
    "/api/auth/operator/proofs",
    {
      email,
      operation: `invitation.${operation}`,
      password,
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
  password: string,
  signal: AbortSignal,
): Promise<Readonly<{ expiresAt: string; proof: string }>> {
  const value = await operatorPost(
    "/api/auth/operator/proofs",
    {
      operation: "researcher.sessions.revoke",
      password,
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
  password: string,
  signal: AbortSignal,
): Promise<Readonly<{ expiresAt: string; proof: string }>> {
  const value = await operatorPost(
    "/api/auth/operator/proofs",
    {
      as_of: request.asOf,
      idempotency_key: request.idempotencyKey,
      operation: "data.refresh.market.submit",
      password,
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
  if (code === "OPERATOR_PASSWORD_INVALID") return "invalid-password";
  if (code === "OPERATOR_PROOF_INVALID") return "invalid-proof";
  if (code === "OPERATOR_INVITATION_CONFLICT") return "conflict";
  if (code === "OPERATOR_INVITATION_DELIVERY_FAILED") return "delivery-failed";
  if (code === "OPERATOR_SESSION_TARGET_PROTECTED") return "protected-target";
  if (code === "OPERATOR_SESSION_TARGET_INVALID") return "invalid-target";
  if (code === "OPERATOR_REQUEST_INVALID") return "request-invalid";
  if (code === "DATA_NOT_READY") return "data-not-ready";
  if (code === "IDEMPOTENCY_KEY_CONFLICT") return "conflict";
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
