export type AuthFailureReason =
  | "CONFIGURATION_INVALID"
  | "DATABASE_OPERATION_FAILED"
  | "DATABASE_PERMISSION_DENIED"
  | "DATABASE_UNAVAILABLE"
  | "INTERNAL_ERROR"
  | "SCHEMA_ARTIFACT_INVALID"
  | "SCHEMA_CATALOG_DRIFT"
  | "SCHEMA_FINGERPRINT_MISMATCH"
  | "SCHEMA_ROLE_CONTRACT_INVALID";

export type AuthFailureDiagnostic = Readonly<{
  reason: AuthFailureReason;
  sqlstate?: string;
}>;

export class AuthConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthConfigurationError";
  }
}

export class AuthSchemaContractError extends Error {
  readonly reason: AuthFailureReason;

  constructor(reason: AuthFailureReason = "SCHEMA_CATALOG_DRIFT", cause?: unknown) {
    super("AUTH_SCHEMA_CONTRACT_INVALID", cause === undefined ? undefined : { cause });
    this.name = "AuthSchemaContractError";
    this.reason = reason;
  }
}

export function diagnoseAuthFailure(error: unknown): AuthFailureDiagnostic {
  if (error instanceof AuthConfigurationError) {
    return { reason: "CONFIGURATION_INVALID" };
  }
  if (error instanceof AuthSchemaContractError) {
    return withSqlstate(error.reason, sqlstateFrom(error.cause));
  }

  const code = errorCode(error);
  const sqlstate = /^[0-9A-Z]{5}$/.test(code ?? "") ? code : undefined;
  if (sqlstate === "42501") {
    return { reason: "DATABASE_PERMISSION_DENIED", sqlstate };
  }
  if (
    sqlstate?.startsWith("08") ||
    sqlstate === "57P01" ||
    connectionErrorCodes.has(code ?? "") ||
    pgConnectionFailureMessages.has(errorMessage(error) ?? "")
  ) {
    return withSqlstate("DATABASE_UNAVAILABLE", sqlstate);
  }
  if (sqlstate !== undefined) {
    return { reason: "DATABASE_OPERATION_FAILED", sqlstate };
  }
  if (pgOperationFailureMessages.has(errorMessage(error) ?? "")) {
    return { reason: "DATABASE_OPERATION_FAILED" };
  }
  return { reason: "INTERNAL_ERROR" };
}

export function schemaContractErrorFrom(error: unknown): AuthSchemaContractError {
  if (error instanceof AuthSchemaContractError) {
    return error;
  }
  const diagnostic = diagnoseAuthFailure(error);
  const reason =
    diagnostic.reason === "INTERNAL_ERROR"
      ? "SCHEMA_CATALOG_DRIFT"
      : diagnostic.reason;
  return new AuthSchemaContractError(reason, error);
}

const connectionErrorCodes = new Set([
  "ECONNREFUSED",
  "ECONNRESET",
  "EAI_AGAIN",
  "ENOTFOUND",
  "ENETUNREACH",
  "EHOSTUNREACH",
  "ETIMEDOUT",
]);
const pgConnectionFailureMessages = new Set([
  "Connection terminated",
  "Connection terminated due to connection timeout",
  "Connection terminated unexpectedly",
  "timeout exceeded when trying to connect",
]);
const pgOperationFailureMessages = new Set(["Query read timeout"]);

function errorCode(error: unknown): string | undefined {
  if (error === null || typeof error !== "object" || !("code" in error)) {
    return undefined;
  }
  return typeof error.code === "string" ? error.code : undefined;
}

function errorMessage(error: unknown): string | undefined {
  if (error === null || typeof error !== "object" || !("message" in error)) {
    return undefined;
  }
  return typeof error.message === "string" ? error.message : undefined;
}

function sqlstateFrom(error: unknown): string | undefined {
  const code = errorCode(error);
  return code !== undefined && /^[0-9A-Z]{5}$/.test(code) ? code : undefined;
}

function withSqlstate(
  reason: AuthFailureReason,
  sqlstate: string | undefined,
): AuthFailureDiagnostic {
  return sqlstate === undefined ? { reason } : { reason, sqlstate };
}
