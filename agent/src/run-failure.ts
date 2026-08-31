import {
  APICallError, EmptyResponseBodyError, InvalidResponseDataError,
  JSONParseError, LoadAPIKeyError, NoContentGeneratedError, TypeValidationError,
} from "@ai-sdk/provider";
import { EventType, type RunErrorEvent } from "@ag-ui/core";

import { runFailureEvent as failureEvent, type AgentFailureCode } from "../../contracts/agent-failure.mjs";

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
  return "INTERNAL_FAILURE";
}
