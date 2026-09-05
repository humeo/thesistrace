import {
  supportedReasoningEfforts,
  type ReasoningEffort,
} from "./modelCatalog";

export type AgentSessionPreference = Readonly<{
  model_key: string;
  reasoning_effort: ReasoningEffort;
}>;

export class AgentSessionPreferenceNotFoundError extends Error {
  constructor() {
    super("Agent Chat Session was not found");
    this.name = "AgentSessionPreferenceNotFoundError";
  }
}

export class AgentSessionPreferenceInvalidError extends Error {
  constructor() {
    super("Agent Chat Session preference is invalid");
    this.name = "AgentSessionPreferenceInvalidError";
  }
}

class AgentSessionPreferenceUnavailableError extends Error {
  constructor() {
    super("Agent Chat Session preference is unavailable");
    this.name = "AgentSessionPreferenceUnavailableError";
  }
}

export async function loadAgentSessionPreference(
  threadId: string,
  signal?: AbortSignal,
): Promise<AgentSessionPreference> {
  let response: Response;
  try {
    response = await fetch(
      `/api/agent/sessions/${encodeURIComponent(threadId)}/preferences`,
      { credentials: "same-origin", signal },
    );
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new AgentSessionPreferenceUnavailableError();
  }
  if (response.status === 404) throw new AgentSessionPreferenceNotFoundError();
  if (!response.ok) throw new AgentSessionPreferenceUnavailableError();
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new AgentSessionPreferenceInvalidError();
  }
  return decodeAgentSessionPreference(value);
}

export function decodeAgentSessionPreference(value: unknown): AgentSessionPreference {
  if (
    !isExactRecord(value, ["model_key", "reasoning_effort"])
    || typeof value.model_key !== "string"
    || !/^[a-z0-9][a-z0-9._-]{0,63}$/.test(value.model_key)
    || typeof value.reasoning_effort !== "string"
    || !(supportedReasoningEfforts as readonly string[]).includes(
      value.reasoning_effort,
    )
  ) {
    throw new AgentSessionPreferenceInvalidError();
  }
  return {
    model_key: value.model_key,
    reasoning_effort: value.reasoning_effort as ReasoningEffort,
  };
}

function isExactRecord(
  value: unknown,
  keys: readonly string[],
): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length
    && actual.every((key, index) => key === expected[index]);
}
