import { APICallError, InvalidResponseDataError, LoadAPIKeyError } from "@ai-sdk/provider";
import { expect, test } from "vitest";

import { agentFailure, AGENT_FAILURE_CODES, runFailureEvent } from "../../contracts/agent-failure.mjs";
import { AgentRunFailure, providerFailureCode } from "./run-failure.js";

test.each([
  [401, "PROVIDER_AUTHENTICATION"], [403, "PROVIDER_AUTHENTICATION"],
  [429, "PROVIDER_RATE_LIMIT"], [408, "PROVIDER_TIMEOUT"],
  [504, "PROVIDER_TIMEOUT"], [503, "PROVIDER_UNAVAILABLE"],
])("classifies provider HTTP %s without returning provider content", (statusCode, code) => {
  const error = new APICallError({
    message: "private-provider-response-canary", url: "https://provider.invalid/private",
    requestBodyValues: { prompt: "private-prompt-canary" }, responseBody: "private-key-canary", statusCode,
  });
  expect(providerFailureCode(error)).toBe(code);
  expect(JSON.stringify(runFailureEvent(providerFailureCode(error)))).not.toMatch(/canary|provider\.invalid/);
});

test("handles typed malformed, credential and internal errors without message heuristics", () => {
  expect(providerFailureCode(new InvalidResponseDataError({ data: "private", message: "private" })))
    .toBe("PROVIDER_MALFORMED_STREAM");
  expect(providerFailureCode(new LoadAPIKeyError({ message: "private" }))).toBe("PROVIDER_AUTHENTICATION");
  expect(providerFailureCode(new DOMException("private", "TimeoutError"))).toBe("PROVIDER_TIMEOUT");
  expect(providerFailureCode(new Error("401 429 timeout private"))).toBe("INTERNAL_FAILURE");
  const safe = new AgentRunFailure("AGENT_LIMIT");
  expect(providerFailureCode(safe)).toBe("AGENT_LIMIT");
  expect(safe.cause).toBeUndefined();
});

test("every closed failure has safe copy and an explicit legal next action", () => {
  expect(new Set(AGENT_FAILURE_CODES).size).toBe(AGENT_FAILURE_CODES.length);
  for (const code of AGENT_FAILURE_CODES) {
    expect(agentFailure(code).code).toBe(code);
    expect(agentFailure(code).message.length).toBeGreaterThan(0);
    expect(agentFailure(code).action.length).toBeGreaterThan(0);
    expect(runFailureEvent(code)).toEqual({ type: "RUN_ERROR", code, message: agentFailure(code).message });
  }
  expect(agentFailure("<script>private</script>").code).toBe("INTERNAL_FAILURE");
  expect(agentFailure("__proto__").code).toBe("INTERNAL_FAILURE");
});
