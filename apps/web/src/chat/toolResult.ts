const SAFE_TOOL_RESULT_TYPE = "thesistrace.tool-result";
const SAFE_TOOL_RESULT_VERSION = 1;
const MAX_MARKER_BYTES = 512;
const RESEARCH_RUN_ID_PATTERN = /^run_[a-f0-9]{20}$/;
const RESEARCH_RUN_STATUSES = new Set([
  "queued",
  "running",
  "cancelling",
  "succeeded",
  "failed",
  "cancelled",
]);

export type SafeResearchRunResource = Readonly<{
  id: string;
  kind: "research_run";
  status: string;
}>;

export type SafeToolResult = Readonly<{
  outcome: "completed" | "failed";
  resource?: SafeResearchRunResource;
  failureCode?: ToolFailureCode;
}>;

export function parseSafeToolResult(value: unknown): SafeToolResult | null {
  if (
    typeof value !== "string"
    || new TextEncoder().encode(value).byteLength > MAX_MARKER_BYTES
  ) {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    return null;
  }
  if (
    !isRecord(parsed)
    || !hasExactKeys(parsed, ["outcome", "type", "version"], ["resource", "failureCode"])
    || parsed.type !== SAFE_TOOL_RESULT_TYPE
    || parsed.version !== SAFE_TOOL_RESULT_VERSION
    || (parsed.outcome !== "completed" && parsed.outcome !== "failed")
  ) {
    return null;
  }
  if (parsed.outcome === "failed") {
    return parsed.resource === undefined && isToolFailureCode(parsed.failureCode)
      ? { outcome: "failed", failureCode: parsed.failureCode } : null;
  }
  if (parsed.failureCode !== undefined) return null;
  if (parsed.resource === undefined) {
    return { outcome: parsed.outcome };
  }
  const resource = readResearchRunResource(parsed.resource);
  return resource === null
    ? null
    : { outcome: "completed", resource };
}

export function researchRunHref(resource: SafeResearchRunResource): string {
  return `/research-runs/${resource.id}`;
}

export function parseResearchRunHref(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const match = /^\/research-runs\/(run_[a-f0-9]{20})$/.exec(value);
  return match === null ? null : value;
}

function readResearchRunResource(value: unknown): SafeResearchRunResource | null {
  if (
    !isRecord(value)
    || !hasExactKeys(value, ["id", "kind", "status"])
    || value.kind !== "research_run"
    || typeof value.id !== "string"
    || !RESEARCH_RUN_ID_PATTERN.test(value.id)
    || typeof value.status !== "string"
    || !RESEARCH_RUN_STATUSES.has(value.status)
  ) {
    return null;
  }
  return { id: value.id, kind: "research_run", status: value.status };
}

function hasExactKeys(
  value: Record<string, unknown>,
  required: readonly string[],
  optional: readonly string[] = [],
): boolean {
  const allowed = new Set([...required, ...optional]);
  return required.every((key) => key in value)
    && Object.keys(value).every((key) => allowed.has(key));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
import { isToolFailureCode, type ToolFailureCode } from "@thesistrace/contracts/agent-failure";
