export class OperatorCapabilityUnavailableError extends Error {
  constructor() {
    super("Operator capability is unavailable");
    this.name = "OperatorCapabilityUnavailableError";
  }
}

export async function loadOperatorCapability(
  request: typeof globalThis.fetch = (...args) => globalThis.fetch(...args),
): Promise<boolean> {
  let response: Response;
  try {
    response = await request("/api/auth/operator/capability", {
      credentials: "same-origin",
    });
  } catch {
    throw new OperatorCapabilityUnavailableError();
  }
  if (response.status === 404) return false;
  if (!response.ok) throw new OperatorCapabilityUnavailableError();
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new OperatorCapabilityUnavailableError();
  }
  if (
    !isRecord(value)
    || Object.keys(value).length !== 1
    || value.operator !== true
  ) {
    throw new OperatorCapabilityUnavailableError();
  }
  return true;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
