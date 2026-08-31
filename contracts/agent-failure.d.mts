export type AgentFailureCode =
  | "AUTHENTICATION_REQUIRED" | "AGENT_UNAVAILABLE" | "INVALID_MODEL"
  | "UNSUPPORTED_REASONING" | "PROVIDER_AUTHENTICATION" | "PROVIDER_RATE_LIMIT"
  | "PROVIDER_TIMEOUT" | "PROVIDER_UNAVAILABLE" | "PROVIDER_REFUSAL"
  | "PROVIDER_MALFORMED_STREAM" | "AGENT_LIMIT" | "MCP_AUTHENTICATION"
  | "MCP_TRANSIENT" | "TOOL_REJECTION" | "TOOL_ERROR" | "INTERNAL_FAILURE"
  | "AGENT_RUN_INTERRUPTED" | "AGENT_RUN_CONFLICT" | "INVALID_CHAT_REQUEST"
  | "CHAT_SESSION_NOT_FOUND";
export type AgentFailureAction = "sign-in" | "retry" | "select-model" | "revise" | "reconnect" | "new-chat";
export type AgentFailure = Readonly<{
  action: AgentFailureAction;
  code: AgentFailureCode;
  label: string;
  message: string;
}>;
export const AGENT_FAILURE_CODES: readonly AgentFailureCode[];
export function isAgentFailureCode(code: unknown): code is AgentFailureCode;
export function agentFailure(code: unknown): AgentFailure;
export function runFailureEvent(code: unknown): { type: "RUN_ERROR"; code: AgentFailureCode; message: string };
export type ToolFailureCode = "TOOL_REJECTION" | "TOOL_ERROR" | "MCP_TRANSIENT" | "MCP_AUTHENTICATION" | "AGENT_LIMIT";
export function isToolFailureCode(code: unknown): code is ToolFailureCode;
export function toolFailureCode(code: unknown): ToolFailureCode;
