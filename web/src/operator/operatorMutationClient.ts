import { OperatorPageNotFoundError } from "./operatorDirectoryClient";

export type InvitationMutationOperation = "issue" | "reissue";

export type OperatorMutationErrorCode =
  | "conflict"
  | "delivery-failed"
  | "invalid-password"
  | "invalid-proof"
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
  if (code === "OPERATOR_REQUEST_INVALID") return "request-invalid";
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
  return Number.isFinite(parsed.getTime()) && parsed.toISOString() === value;
}

function isOpaqueProof(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.[A-Za-z0-9_-]{43}$/i
    .test(value);
}

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
    .test(value);
}

function isEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}
