// The browser and Host share codes/copy, never provider exception messages.
const definitions = {
  AUTHENTICATION_REQUIRED: ["Sign in required", "Your login session is no longer active. Sign in before sending another message.", "sign-in"],
  AGENT_UNAVAILABLE: ["Agent unavailable", "The Agent connection is unavailable. Reconnect to check the accepted run before sending again.", "reconnect"],
  INVALID_MODEL: ["Model unavailable", "This model is no longer enabled. Choose a registered model for the next run.", "select-model"],
  UNSUPPORTED_REASONING: ["Reasoning unavailable", "Choose a reasoning level supported by the selected model.", "select-model"],
  PROVIDER_AUTHENTICATION: ["Provider authentication failed", "The provider rejected its configured credential. Choose another registered model or contact the operator.", "select-model"],
  PROVIDER_RATE_LIMIT: ["Provider rate limit", "The provider is rate limited. Wait before explicitly retrying, or choose another registered model.", "retry"],
  PROVIDER_TIMEOUT: ["Provider timed out", "The provider did not finish within its time limit. You can explicitly retry or choose another model.", "retry"],
  PROVIDER_UNAVAILABLE: ["Provider unavailable", "The selected provider is unavailable. You can explicitly retry or choose another model.", "retry"],
  PROVIDER_REFUSAL: ["Provider declined the request", "The provider declined this request. Revise the message before trying again.", "revise"],
  PROVIDER_MALFORMED_STREAM: ["Invalid provider response", "The provider returned an incomplete or invalid response. You can explicitly retry or choose another model.", "retry"],
  AGENT_LIMIT: ["Execution limit reached", "This run reached an execution limit. Narrow the request or start a new Chat. Admitted research continues independently.", "revise"],
  CONTEXT_TOO_LARGE: ["Conversation exceeds model capacity", "Choose a model with a larger context window or start a new Chat. Your history and completed research are retained; do not resubmit successful operations.", "select-model"],
  CONTEXT_COMPACTION_FAILED: ["Conversation compression failed", "The Agent could not safely prepare a complete context snapshot. Original history and completed research are retained. Choose a larger model or retry; do not resubmit successful operations.", "select-model"],
  OUTPUT_LIMIT: ["Answer was truncated", "The model stopped at its output allowance. Split the requested answer or choose a model with more available capacity. Completed research is retained; do not resubmit successful operations.", "revise"],
  MCP_AUTHENTICATION: ["Research access denied", "Research tool authentication or scope validation failed. Sign in again; no alternate access path was used.", "sign-in"],
  MCP_TRANSIENT: ["Research temporarily unavailable", "A research tool is temporarily unavailable. Reopen this Chat to inspect retained research before retrying.", "retry"],
  TOOL_REJECTION: ["Research request rejected", "The research tool rejected this request. Review the explanation and revise the requested research.", "revise"],
  TOOL_ERROR: ["Research tool failed", "A research tool could not complete. Retained research is unchanged; you can ask the Agent to inspect it.", "revise"],
  INTERNAL_FAILURE: ["Agent run failed", "The Agent could not complete this run. Completed research is retained. You can explicitly retry.", "retry"],
  AGENT_RUN_INTERRUPTED: ["Agent run interrupted", "This run was interrupted. Completed research continues independently. You can ask the Agent to inspect it.", "revise"],
  AGENT_RUN_CONFLICT: ["Chat already running", "This Chat is already running. Reconnect to follow the current run.", "reconnect"],
  AGENT_CAPACITY: ["Agent at capacity", "All Agent execution slots are occupied. No new run was accepted. Wait before explicitly retrying.", "retry"],
  INVALID_CHAT_REQUEST: ["Invalid message", "The message could not be accepted. Revise it before sending again.", "revise"],
  CHAT_SESSION_NOT_FOUND: ["Chat not found", "This Chat is unavailable. Start a new Chat to continue.", "new-chat"],
};

export const AGENT_FAILURE_CODES = Object.freeze(Object.keys(definitions));
export function isAgentFailureCode(code) {
  return typeof code === "string" && Object.hasOwn(definitions, code);
}

export function agentFailure(value) {
  const code = isAgentFailureCode(value) ? value : "INTERNAL_FAILURE";
  const [label, message, action] = definitions[code];
  return { code, label, message, action };
}

export function runFailureEvent(value) {
  const { code, message } = agentFailure(value);
  return { type: "RUN_ERROR", code, message };
}

export function isToolFailureCode(code) {
  return ["TOOL_REJECTION", "TOOL_ERROR", "MCP_TRANSIENT", "MCP_AUTHENTICATION", "AGENT_LIMIT"].includes(code);
}

export function toolFailureCode(code) {
  if (isToolFailureCode(code)) return code;
  if (code === "FORBIDDEN") return "MCP_AUTHENTICATION";
  if (code === "TEMPORARILY_UNAVAILABLE") return "MCP_TRANSIENT";
  if (["INVALID_INPUT", "NOT_FOUND", "STATE_CONFLICT", "IDEMPOTENCY_CONFLICT"].includes(code)) return "TOOL_REJECTION";
  return "TOOL_ERROR";
}
