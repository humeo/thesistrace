import { APICallError, InvalidResponseDataError, LoadAPIKeyError } from "@ai-sdk/provider";
import { expect, test } from "vitest";

import { agentFailure, AGENT_FAILURE_CODES, runFailureEvent } from "@thesistrace/contracts/agent-failure";
import { AgentRunFailure, providerFailureCode } from "./run-failure.js";

test("classifies an explicit provider context rejection without reading private text", () => {
  const error = new APICallError({ message: "private", url: "https://private.invalid", statusCode: 400,
    requestBodyValues: {}, data: { error: { code: "context_length_exceeded", message: "private" } } });
  expect(providerFailureCode(error)).toBe("CONTEXT_TOO_LARGE");
  expect(providerFailureCode(new APICallError({ message: "context_length_exceeded", url: "https://private.invalid",
    statusCode: 400, requestBodyValues: {} }))).toBe("PROVIDER_UNAVAILABLE");
});

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

test.each([
  new TypeError("UND_ERR_SOCKET private-message-canary"),
  new TypeError("private-message-canary", { cause: Object.assign(new Error("private-cause-canary"), { code: "UNKNOWN" }) }),
  new TypeError("private-message-canary", { cause: { code: "UND_ERR_SOCKET" } }),
  { type: "unknown", sequence_number: 1, code: "server_error", message: "private-message-canary" },
  { type: "error", sequence_number: -1, code: "server_error", message: "private-message-canary" },
  { type: "error", sequence_number: "1", code: "server_error", message: "private-message-canary" },
])("unproven transport or frame metadata stays an internal failure %#", (error) => {
  expect(providerFailureCode(error)).toBe("INTERNAL_FAILURE");
});

test("private stream-error wording cannot change the public failure category", () => {
  const error = { type: "error", sequence_number: 1, code: "server_error", message: "401 429 timeout private-message-canary" };
  expect(providerFailureCode(error)).toBe("PROVIDER_UNAVAILABLE");
  expect(JSON.stringify(runFailureEvent(providerFailureCode(error)))).not.toMatch(/401|429|timeout|canary/);
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
