const SAFE_TOOL_RESULT_TYPE = "thesistrace.tool-result";
const SAFE_TOOL_RESULT_VERSION = 1;
const MAX_RAW_TOOL_RESULT_BYTES = 512 * 1024;
const RESEARCH_RUN_ID_PATTERN = /^run_[a-f0-9]{20}$/;
const RESEARCH_RUN_STATUSES = new Set([
  "queued",
  "running",
  "cancelling",
  "succeeded",
  "failed",
  "cancelled",
]);

type SafeResearchRunResource = Readonly<{
  id: string;
  kind: "research_run";
  status: string;
}>;

export type SafeToolResult = Readonly<{
  outcome: "completed" | "failed";
  resource?: SafeResearchRunResource;
  failureCode?: ToolFailureCode;
}>;

export const SAFE_TOOL_COMPLETED = encodeMarker({ outcome: "completed" });
export const SAFE_TOOL_FAILED = encodeMarker({ outcome: "failed", failureCode: "TOOL_ERROR" });

export function projectSafeToolResult(
  rawResult: unknown,
  failed: boolean,
): string {
  if (failed) {
    const payload = unwrapToolResult(rawResult);
    const marker = parseSafeToolResult(rawResult);
    return encodeMarker({ outcome: "failed", failureCode: marker?.outcome === "failed"
      ? marker.failureCode : toolFailureCode(isRecord(payload) ? payload.code : undefined) });
  }
  const resource = readResearchRunResource(rawResult);
  return resource === undefined
    ? SAFE_TOOL_COMPLETED
    : encodeMarker({ outcome: "completed", resource });
}

export function parseSafeToolResult(value: unknown): SafeToolResult | null {
  if (typeof value !== "string" || Buffer.byteLength(value, "utf8") > 512) {
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
  const resource = readExactResearchRunResource(parsed.resource);
  return resource === undefined
    ? null
    : { outcome: "completed", resource };
}

function readResearchRunResource(value: unknown): SafeResearchRunResource | undefined {
  const payload = unwrapToolResult(value);
  if (!isRecord(payload)) return undefined;
  const status = payload.status;
  const id = typeof payload.run_id === "string"
    ? payload.run_id
    : typeof payload.id === "string"
      ? payload.id
      : undefined;
  if (
    id === undefined
    || !RESEARCH_RUN_ID_PATTERN.test(id)
    || typeof status !== "string"
    || !RESEARCH_RUN_STATUSES.has(status)
  ) {
    return undefined;
  }
  return { id, kind: "research_run", status };
}

function unwrapToolResult(value: unknown): unknown {
  if (typeof value === "string") {
    if (Buffer.byteLength(value, "utf8") > MAX_RAW_TOOL_RESULT_BYTES) return undefined;
    try {
      return unwrapToolResult(JSON.parse(value));
    } catch {
      return undefined;
    }
  }
  if (!isRecord(value)) return value;
  if (value.type === "json" && "value" in value) {
    return unwrapToolResult(value.value);
  }
  if (isRecord(value.structuredContent)) {
    return unwrapToolResult(value.structuredContent);
  }
  return value;
}

function readExactResearchRunResource(
  value: unknown,
): SafeResearchRunResource | undefined {
  if (
    !isRecord(value)
    || !hasExactKeys(value, ["id", "kind", "status"])
    || value.kind !== "research_run"
    || typeof value.id !== "string"
    || !RESEARCH_RUN_ID_PATTERN.test(value.id)
    || typeof value.status !== "string"
    || !RESEARCH_RUN_STATUSES.has(value.status)
  ) {
    return undefined;
  }
  return { id: value.id, kind: "research_run", status: value.status };
}

function encodeMarker(marker: SafeToolResult): string {
  return JSON.stringify({
    outcome: marker.outcome,
    ...(marker.failureCode === undefined ? {} : { failureCode: marker.failureCode }),
    ...(marker.resource === undefined ? {} : { resource: marker.resource }),
    type: SAFE_TOOL_RESULT_TYPE,
    version: SAFE_TOOL_RESULT_VERSION,
  });
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
import { isToolFailureCode, toolFailureCode, type ToolFailureCode } from "@thesistrace/contracts/agent-failure";
