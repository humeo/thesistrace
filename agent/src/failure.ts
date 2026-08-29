export class AgentConfigurationError extends Error {
  constructor() {
    super("Agent configuration is invalid");
    this.name = "AgentConfigurationError";
  }
}

export class AgentAuthenticationUnavailableError extends Error {
  constructor() {
    super("Agent authentication is unavailable");
    this.name = "AgentAuthenticationUnavailableError";
  }
}

export type AgentFailureReason =
  | "CONFIGURATION_INVALID"
  | "DATABASE_OPERATION_FAILED"
  | "DATABASE_PERMISSION_DENIED"
  | "DATABASE_UNAVAILABLE"
  | "INTERNAL_ERROR"
  | "SCHEMA_ARTIFACT_INVALID"
  | "SCHEMA_CATALOG_DRIFT"
  | "SCHEMA_FINGERPRINT_MISMATCH"
  | "SCHEMA_ROLE_CONTRACT_INVALID";

export type AgentFailureDiagnostic = Readonly<{
  reason: AgentFailureReason;
  sqlstate?: string;
}>;

export class AgentSchemaContractError extends Error {
  readonly reason: AgentFailureReason;

  constructor(reason: AgentFailureReason = "SCHEMA_CATALOG_DRIFT", cause?: unknown) {
    super("AGENT_SCHEMA_CONTRACT_INVALID", cause === undefined ? undefined : { cause });
    this.name = "AgentSchemaContractError";
    this.reason = reason;
  }
}

export function diagnoseAgentFailure(error: unknown): AgentFailureDiagnostic {
  if (error instanceof AgentConfigurationError) {
    return { reason: "CONFIGURATION_INVALID" };
  }
  if (error instanceof AgentSchemaContractError) {
    return withSqlstate(error.reason, sqlstateFrom(error.cause));
  }

  const code = errorCode(error);
  const sqlstate = /^[0-9A-Z]{5}$/.test(code ?? "") ? code : undefined;
  if (sqlstate === "42501") {
    return { reason: "DATABASE_PERMISSION_DENIED", sqlstate };
  }
  if (
    sqlstate?.startsWith("08")
    || sqlstate === "57P01"
    || connectionErrorCodes.has(code ?? "")
    || connectionFailureMessages.has(errorMessage(error) ?? "")
  ) {
    return withSqlstate("DATABASE_UNAVAILABLE", sqlstate);
  }
  if (sqlstate !== undefined) {
    return { reason: "DATABASE_OPERATION_FAILED", sqlstate };
  }
  return { reason: "INTERNAL_ERROR" };
}

export function schemaContractErrorFrom(error: unknown): AgentSchemaContractError {
  if (error instanceof AgentSchemaContractError) return error;
  const diagnostic = diagnoseAgentFailure(error);
  return new AgentSchemaContractError(
    diagnostic.reason === "INTERNAL_ERROR" ? "SCHEMA_CATALOG_DRIFT" : diagnostic.reason,
    error,
  );
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
const connectionFailureMessages = new Set([
  "Connection terminated",
  "Connection terminated due to connection timeout",
  "Connection terminated unexpectedly",
  "timeout exceeded when trying to connect",
  "Query read timeout",
]);

function errorCode(error: unknown): string | undefined {
  return error !== null && typeof error === "object" && "code" in error
    && typeof error.code === "string"
    ? error.code
    : undefined;
}

function errorMessage(error: unknown): string | undefined {
  return error !== null && typeof error === "object" && "message" in error
    && typeof error.message === "string"
    ? error.message
    : undefined;
}

function sqlstateFrom(error: unknown): string | undefined {
  const code = errorCode(error);
  return code !== undefined && /^[0-9A-Z]{5}$/.test(code) ? code : undefined;
}

function withSqlstate(
  reason: AgentFailureReason,
  sqlstate: string | undefined,
): AgentFailureDiagnostic {
  return sqlstate === undefined ? { reason } : { reason, sqlstate };
}
