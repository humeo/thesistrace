import {
  APICallError, EmptyResponseBodyError, InvalidResponseDataError,
  JSONParseError, LoadAPIKeyError, NoContentGeneratedError, TypeValidationError,
} from "@ai-sdk/provider";
import { EventType, type RunErrorEvent } from "@ag-ui/core";

import { runFailureEvent as failureEvent, type AgentFailureCode } from "@thesistrace/contracts/agent-failure";

export function runFailureEvent(code: unknown): RunErrorEvent {
  return { ...failureEvent(code), type: EventType.RUN_ERROR };
}

export class AgentRunFailure extends Error {
  constructor(readonly code: AgentFailureCode) {
    super(code);
    this.name = "AgentRunFailure";
  }
}

/** Typed provider metadata only. Never classify by private response text. */
export function providerFailureCode(error: unknown): AgentFailureCode {
  if (error instanceof AgentRunFailure) return error.code;
  if (LoadAPIKeyError.isInstance(error)) return "PROVIDER_AUTHENTICATION";
  if (APICallError.isInstance(error)) {
    if (error.statusCode === 401 || error.statusCode === 403) return "PROVIDER_AUTHENTICATION";
    if (error.statusCode === 429) return "PROVIDER_RATE_LIMIT";
    if (error.statusCode === 408 || error.statusCode === 504) return "PROVIDER_TIMEOUT";
    if (error.statusCode === 400 && isRecord(error.data) && isRecord(error.data.error)
      && error.data.error.code === "context_length_exceeded") return "CONTEXT_TOO_LARGE";
    return "PROVIDER_UNAVAILABLE";
  }
  // Node fetch rejects an interrupted SSE body with its native TypeError,
  // outside the SDK's HTTP-status wrapper. Inspect only the transport code;
  // private exception messages and socket details never cross this boundary.
  if (error instanceof TypeError && error.cause instanceof Error
    && "code" in error.cause && error.cause.code === "UND_ERR_SOCKET") {
    return "PROVIDER_UNAVAILABLE";
  }
  if (error instanceof DOMException && error.name === "TimeoutError") return "PROVIDER_TIMEOUT";
  // Mastra does not export this class; its public timeout contract carries
  // this name and bounded scope, never a provider-specific message pattern.
  if (error instanceof Error && error.name === "MastraTimeoutError" && "timeoutType" in error) {
    if (error.timeoutType === "step") return "PROVIDER_TIMEOUT";
    if (error.timeoutType === "total") return "AGENT_LIMIT";
  }
  if (
    InvalidResponseDataError.isInstance(error) || EmptyResponseBodyError.isInstance(error)
    || NoContentGeneratedError.isInstance(error) || TypeValidationError.isInstance(error)
    || JSONParseError.isInstance(error)
  ) return "PROVIDER_MALFORMED_STREAM";
  // After output starts, the native SDK emits validated Responses error
  // frames as objects instead of APICallError. Read only their code metadata.
  if (isRecord(error) && !(error instanceof Error)
    && typeof error.sequence_number === "number" && Number.isSafeInteger(error.sequence_number)
    && error.sequence_number >= 0) {
    const detail = error.type === "error" ? (isRecord(error.error) ? error.error : error)
      : error.type === "response.failed" && isRecord(error.response) ? error.response.error : undefined;
    if (isRecord(detail) && typeof detail.message === "string"
      && (typeof detail.code === "string" || detail.code === null || detail.code === undefined)) {
      if (detail.code === "rate_limit_exceeded" || detail.code === "insufficient_quota") return "PROVIDER_RATE_LIMIT";
      if (detail.code === "context_length_exceeded") return "CONTEXT_TOO_LARGE";
      return "PROVIDER_UNAVAILABLE";
    }
  }
  return "INTERNAL_FAILURE";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
