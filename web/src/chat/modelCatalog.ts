export const supportedReasoningEfforts = [
  "none",
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
] as const;

export type ReasoningEffort = (typeof supportedReasoningEfforts)[number];
export type AgentModel = Readonly<{
  default_reasoning_effort: ReasoningEffort;
  display_name: string;
  key: string;
  reasoning_efforts: readonly ReasoningEffort[];
}>;
export type AgentModelCatalog = Readonly<{
  default_model_key: string;
  models: readonly AgentModel[];
}>;

export class AgentCatalogAuthenticationRequiredError extends Error {
  constructor() {
    super("Agent authentication is required");
    this.name = "AgentCatalogAuthenticationRequiredError";
  }
}

class AgentCatalogUnavailableError extends Error {
  constructor() {
    super("Agent model catalog is unavailable");
    this.name = "AgentCatalogUnavailableError";
  }
}

export class AgentCatalogInvalidError extends Error {
  constructor() {
    super("Agent model catalog is invalid");
    this.name = "AgentCatalogInvalidError";
  }
}

export async function loadAgentModelCatalog(
  signal?: AbortSignal,
): Promise<AgentModelCatalog> {
  let response: Response;
  try {
    response = await fetch("/api/agent/models", {
      credentials: "same-origin",
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new AgentCatalogUnavailableError();
  }
  if (response.status === 401) throw new AgentCatalogAuthenticationRequiredError();
  if (!response.ok) throw new AgentCatalogUnavailableError();
  try {
    return decodeAgentModelCatalog(await response.json());
  } catch (error) {
    if (error instanceof AgentCatalogInvalidError) throw error;
    throw new AgentCatalogInvalidError();
  }
}

export function decodeAgentModelCatalog(value: unknown): AgentModelCatalog {
  if (!isExactRecord(value, ["default_model_key", "models"])) {
    throw new AgentCatalogInvalidError();
  }
  if (
    typeof value.default_model_key !== "string"
    || !isModelKey(value.default_model_key)
    || !Array.isArray(value.models)
    || value.models.length === 0
    || value.models.length > 64
  ) {
    throw new AgentCatalogInvalidError();
  }

  const modelKeys = new Set<string>();
  const displayNames = new Set<string>();
  const models = value.models.map((candidate): AgentModel => {
    if (
      !isExactRecord(candidate, [
        "default_reasoning_effort",
        "display_name",
        "key",
        "reasoning_efforts",
      ])
      || typeof candidate.key !== "string"
      || !isModelKey(candidate.key)
      || typeof candidate.display_name !== "string"
      || !isCanonicalText(candidate.display_name)
      || candidate.display_name.length > 80
      || !Array.isArray(candidate.reasoning_efforts)
      || candidate.reasoning_efforts.length === 0
      || !candidate.reasoning_efforts.every(isReasoningEffort)
      || !isReasoningEffort(candidate.default_reasoning_effort)
      || !candidate.reasoning_efforts.includes(candidate.default_reasoning_effort)
      || new Set(candidate.reasoning_efforts).size !== candidate.reasoning_efforts.length
    ) {
      throw new AgentCatalogInvalidError();
    }
    const displayIdentity = candidate.display_name
      .normalize("NFKC")
      .toLocaleLowerCase("en-US");
    if (modelKeys.has(candidate.key) || displayNames.has(displayIdentity)) {
      throw new AgentCatalogInvalidError();
    }
    modelKeys.add(candidate.key);
    displayNames.add(displayIdentity);
    return {
      default_reasoning_effort: candidate.default_reasoning_effort,
      display_name: candidate.display_name,
      key: candidate.key,
      reasoning_efforts: [...candidate.reasoning_efforts],
    };
  });
  if (!modelKeys.has(value.default_model_key)) throw new AgentCatalogInvalidError();
  return { default_model_key: value.default_model_key, models };
}

export function reasoningEffortLabel(value: ReasoningEffort): string {
  if (value === "xhigh") return "X-high";
  return `${value.slice(0, 1).toUpperCase()}${value.slice(1)}`;
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

function isModelKey(value: string): boolean {
  return /^[a-z0-9][a-z0-9._-]{0,63}$/.test(value);
}

function isCanonicalText(value: string): boolean {
  return value.trim() === value
    && value.length > 0
    && !/[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/u.test(value);
}

function isReasoningEffort(value: unknown): value is ReasoningEffort {
  return typeof value === "string"
    && (supportedReasoningEfforts as readonly string[]).includes(value);
}
