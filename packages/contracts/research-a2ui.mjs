import { z } from "zod";
import { zodToJsonSchema } from "zod-to-json-schema";

export const RESEARCH_A2UI_ACTIVITY_TYPE = "a2ui-surface";
export const RESEARCH_A2UI_CATALOG_ID = "urn:thesistrace:a2ui:research:v0.9";
export const RESEARCH_A2UI_PROTOCOL_VERSION = "v0.9";
const RESEARCH_A2UI_MAX_BYTES = 64 * 1024;
export const RESEARCH_A2UI_MAX_COMPONENTS = 64;
const RESEARCH_A2UI_MAX_DEPTH = 8;

const pairSchema = (labelLength, valueLength) => z.object({
  label: z.string().min(1).max(labelLength),
  value: z.string().min(1).max(valueLength),
}).strict();

export const RESEARCH_A2UI_DEFINITIONS = {
  Text: {
    description: "Bounded plain text.",
    props: z.object({
      text: z.string().min(1).max(4_000),
      variant: z.enum(["body", "caption", "label", "title"]).optional(),
    }).strict(),
  },
  Row: {
    description: "Horizontal child layout.",
    props: z.object({
      align: z.enum(["start", "center", "end", "stretch"]).optional(),
      children: z.array(z.string().regex(/^[A-Za-z][A-Za-z0-9_-]{0,63}$/)).min(1).max(16),
      gap: z.enum(["compact", "normal", "wide"]).optional(),
    }).strict(),
  },
  Column: {
    description: "Vertical child layout.",
    props: z.object({
      align: z.enum(["start", "center", "end", "stretch"]).optional(),
      children: z.array(z.string().regex(/^[A-Za-z][A-Za-z0-9_-]{0,63}$/)).min(1).max(16),
      gap: z.enum(["compact", "normal", "wide"]).optional(),
    }).strict(),
  },
  Divider: {
    description: "Hairline divider.",
    props: z.object({}).strict(),
  },
  Formula: {
    description: "Read-only Alpha formula with local copy.",
    props: z.object({
      expression: z.string().min(1).max(8_192),
      label: z.string().min(1).max(80).optional(),
    }).strict(),
  },
  AlphaProposal: {
    description: "Chat-owned Alpha proposal.",
    props: z.object({
      explanation: z.string().min(1).max(4_000),
      formula: z.string().min(1).max(8_192),
      hypothesis: z.string().min(1).max(2_000),
      period: z.string().min(1).max(120),
      researchType: z.string().min(1).max(80),
      strategy: z.array(pairSchema(80, 240)).min(1).max(16),
      title: z.string().min(1).max(160),
      universe: z.string().min(1).max(160),
    }).strict(),
  },
  ResearchRun: { description: "Current ResearchRun from Core.", props: z.object({ runId: z.string().regex(/^run_[a-f0-9]{20}$/) }).strict() },
  ResearchComparison: { description: "Ordered authoritative ResearchRuns.", props: z.object({ runIds: z.array(z.string().regex(/^run_[a-f0-9]{20}$/)).min(1).max(20).refine(ids => new Set(ids).size === ids.length, "Resource IDs must be distinct") }).strict() },
  DailyTrack: { description: "Current DailyTrack from Core.", props: z.object({ trackId: z.string().regex(/^track_[a-f0-9]{20}$/) }).strict() },
  Table: {
    description: "Bounded read-only result table.",
    props: z.object({
      caption: z.string().min(1).max(240),
      columns: z.array(z.string().min(1).max(80)).min(1).max(12),
      initiallyExpanded: z.boolean().optional(),
      rows: z.array(z.array(z.string().max(320)).min(1).max(12)).max(100),
      summary: z.string().min(1).max(160),
    }).strict(),
  },
  Navigation: {
    description: "Allowlisted same-origin product navigation.",
    props: z.object({
      href: z.string().min(1).max(240).refine(value => parseResearchA2UINavigationHref(value) !== null, "Use an allowlisted product route"),
      label: z.string().min(1).max(120),
    }).strict(),
  },
};

// JSON Schema is derived for transport; Zod is the shared field validator for
// the server projector and the official frontend catalog.
export const RESEARCH_A2UI_INLINE_CATALOG = Object.freeze({
  catalogId: RESEARCH_A2UI_CATALOG_ID,
  components: Object.freeze(Object.fromEntries(Object.entries(RESEARCH_A2UI_DEFINITIONS)
    .map(([name, definition]) => [name, { ...zodToJsonSchema(definition.props, { $refStrategy: "none" }), description: definition.description }]))),
});

const viewFields = { research_runs: "runIds", alpha_proposal: "proposal", daily_track: "trackId" };
export const RESEARCH_A2UI_VIEW_SCHEMA = z.object({
  view: z.enum(["research_runs", "alpha_proposal", "daily_track"]).describe("research_runs requires only runIds; alpha_proposal requires only proposal; daily_track requires only trackId."),
  runIds: RESEARCH_A2UI_DEFINITIONS.ResearchComparison.props.shape.runIds.optional(),
  proposal: RESEARCH_A2UI_DEFINITIONS.AlphaProposal.props.optional(),
  trackId: RESEARCH_A2UI_DEFINITIONS.DailyTrack.props.shape.trackId.optional(),
}).strict().superRefine((input, context) => {
  const required = viewFields[input.view];
  if (input[required] === undefined) context.addIssue({ code: "custom", path: [required], message: `Required for ${input.view}` });
  for (const field of Object.values(viewFields)) {
    if (field !== required && input[field] !== undefined) context.addIssue({ code: "custom", path: [field], message: `Not allowed for ${input.view}` });
  }
});
export const RESEARCH_A2UI_VIEW_JSON_SCHEMA = zodToJsonSchema(RESEARCH_A2UI_VIEW_SCHEMA, { $refStrategy: "none" });

const COMPONENT_ID = /^[A-Za-z][A-Za-z0-9_-]{0,63}$/;
const MESSAGE_ID = /^a2ui-surface-[A-Za-z0-9._:-]{1,200}$/;
const SURFACE_ID = /^[a-z][a-z0-9-]{0,63}$/;
const RESEARCH_RUN_ID = /^run_[a-f0-9]{20}$/;

const ERROR_CODES = new Set(["GENERATION_FAILED", "INVALID_PAYLOAD", "INVALID_ENVELOPE", "INVALID_OPERATIONS", "INVALID_LIFECYCLE", "TOOL_RESULT_MISSING", "TOOL_RESULT_INVALID_JSON"]);
export function safeResearchA2UIErrorContent(errorCode = "GENERATION_FAILED") {
  return {
    debugExposure: "hidden",
    error: "This research surface could not be displayed.",
    status: "failed",
    errorCode: ERROR_CODES.has(errorCode) ? errorCode : "GENERATION_FAILED",
  };
}

export function isResearchA2UIMessageId(value) {
  return typeof value === "string" && value.length <= 220 && MESSAGE_ID.test(value);
}

export function parseResearchA2UINavigationHref(value) {
  if (typeof value !== "string" || value.length > 240) return null;
  if (["/data", "/research", "/research-runs", "/daily-tracks"].includes(value)) {
    return value;
  }
  const match = /^\/research-runs\/(run_[a-f0-9]{20})$/.exec(value);
  if (match !== null && RESEARCH_RUN_ID.test(match[1])) return value;
  return /^\/daily-tracks\/track_[a-f0-9]{20}$/.test(value) ? value : null;
}

export function projectResearchA2UIContent(value) {
  if (!isBoundedJson(value, RESEARCH_A2UI_MAX_BYTES) || !isRecord(value)) {
    return invalid("payload");
  }
  if (Object.hasOwn(value, "a2ui_operations")) {
    if (!exactKeys(value, ["a2ui_operations"]) || !Array.isArray(value.a2ui_operations)) {
      return invalid("envelope");
    }
    const projected = projectOperations(value.a2ui_operations);
    return projected === null
      ? invalid("operations")
      : { content: { a2ui_operations: projected }, kind: "ready", valid: true };
  }
  return projectLifecycle(value);
}

/** Application-owned templates. The model supplies business fields only. */
export function createResearchA2UIView(input, surfaceId) {
  const component = input.view === "research_runs"
    ? { component: "ResearchComparison", runIds: input.runIds }
    : input.view === "daily_track"
      ? { component: "DailyTrack", trackId: input.trackId }
      : { component: "AlphaProposal", ...input.proposal };
  return { a2ui_operations: [
    { version: RESEARCH_A2UI_PROTOCOL_VERSION, createSurface: { catalogId: RESEARCH_A2UI_CATALOG_ID, surfaceId } },
    { version: RESEARCH_A2UI_PROTOCOL_VERSION, updateComponents: { surfaceId, components: [{ ...component, id: "root" }] } },
  ] };
}

function projectLifecycle(value) {
  const allowed = [
    "attempt",
    "attempts",
    "debugExposure",
    "error",
    "errors",
    "errorCode",
    "maxAttempts",
    "progressTokens",
    "status",
  ];
  if (!exactKeys(value, allowed)) return invalid("lifecycle");
  if (value.status === "failed") {
    return { content: safeResearchA2UIErrorContent(value.errorCode), kind: "error", valid: false };
  }
  if (value.status !== "building" && value.status !== "retrying") {
    return invalid("lifecycle");
  }
  const content = { debugExposure: "hidden", status: value.status };
  for (const key of ["attempt", "maxAttempts", "progressTokens"]) {
    if (value[key] === undefined) continue;
    if (!isBoundedInteger(value[key], 0, 1_000_000)) return invalid("lifecycle");
    content[key] = value[key];
  }
  return { content, kind: "loading", valid: true };
}

function projectOperations(operations) {
  if (operations.length < 2 || operations.length > 3) return null;
  let create = null;
  let components = null;
  for (const operation of operations) {
    if (!isRecord(operation) || operation.version !== RESEARCH_A2UI_PROTOCOL_VERSION) return null;
    const operationNames = ["createSurface", "updateComponents", "updateDataModel"]
      .filter((name) => Object.hasOwn(operation, name));
    if (operationNames.length !== 1 || !exactKeys(operation, ["version", operationNames[0]])) {
      return null;
    }
    const name = operationNames[0];
    const payload = operation[name];
    if (!isRecord(payload)) return null;
    if (name === "createSurface") {
      if (create !== null || !exactKeys(payload, ["catalogId", "surfaceId"])) return null;
      if (payload.catalogId !== RESEARCH_A2UI_CATALOG_ID || !isSurfaceId(payload.surfaceId)) return null;
      create = { catalogId: RESEARCH_A2UI_CATALOG_ID, surfaceId: payload.surfaceId };
      continue;
    }
    if (name === "updateComponents") {
      if (components !== null || !exactKeys(payload, ["components", "surfaceId"])) return null;
      if (!isSurfaceId(payload.surfaceId) || !Array.isArray(payload.components)) return null;
      const projectedComponents = projectComponents(payload.components);
      if (projectedComponents === null) return null;
      components = { components: projectedComponents, surfaceId: payload.surfaceId };
      continue;
    }
    if (
      !exactKeys(payload, ["path", "surfaceId", "value"])
      || !isSurfaceId(payload.surfaceId)
      || payload.path !== "/"
      || !isRecord(payload.value)
      || Object.keys(payload.value).length !== 0
    ) {
      return null;
    }
  }
  if (create === null || components === null || create.surfaceId !== components.surfaceId) return null;
  return [
    { version: RESEARCH_A2UI_PROTOCOL_VERSION, createSurface: create },
    {
      version: RESEARCH_A2UI_PROTOCOL_VERSION,
      updateComponents: { components: components.components, surfaceId: components.surfaceId },
    },
  ];
}

function projectComponents(values) {
  if (values.length === 0 || values.length > RESEARCH_A2UI_MAX_COMPONENTS) return null;
  const projected = [];
  const byId = new Map();
  for (const value of values) {
    const component = projectComponent(value);
    if (component === null || byId.has(component.id)) return null;
    projected.push(component);
    byId.set(component.id, component);
  }
  if (!byId.has("root")) return null;

  const parentCount = new Map();
  const childrenById = new Map();
  for (const component of projected) {
    const children = component.component === "Row" || component.component === "Column"
      ? component.children
      : [];
    childrenById.set(component.id, children);
    for (const child of children) {
      if (!byId.has(child) || child === component.id) return null;
      parentCount.set(child, (parentCount.get(child) ?? 0) + 1);
      if (parentCount.get(child) !== 1) return null;
    }
  }
  if ((parentCount.get("root") ?? 0) !== 0) return null;
  for (const id of byId.keys()) {
    if (id !== "root" && parentCount.get(id) !== 1) return null;
  }

  const visited = new Set();
  const active = new Set();
  const visit = (id, depth) => {
    if (depth > RESEARCH_A2UI_MAX_DEPTH || active.has(id)) return false;
    if (visited.has(id)) return true;
    active.add(id);
    for (const child of childrenById.get(id) ?? []) {
      if (!visit(child, depth + 1)) return false;
    }
    active.delete(id);
    visited.add(id);
    return true;
  };
  return visit("root", 1) && visited.size === byId.size ? projected : null;
}

function projectComponent(value) {
  if (!isRecord(value) || typeof value.id !== "string" || !COMPONENT_ID.test(value.id)) return null;
  if (typeof value.component !== "string" || !Object.hasOwn(RESEARCH_A2UI_DEFINITIONS, value.component)) return null;
  const definition = RESEARCH_A2UI_DEFINITIONS[value.component];
  const { id, component, ...props } = value;
  const result = definition.props.safeParse(props);
  if (!result.success) return null;
  // Cross-field table integrity cannot be represented by a property schema.
  if (component === "Table" && result.data.rows.some(row => row.length !== result.data.columns.length)) return null;
  return { component, id, ...result.data };
}

function invalid(reason) {
  return { content: safeResearchA2UIErrorContent(`INVALID_${reason.toUpperCase()}`), kind: "error", valid: false };
}

function isBoundedJson(value, maxBytes) {
  try {
    const json = JSON.stringify(value);
    return typeof json === "string" && new TextEncoder().encode(json).byteLength <= maxBytes;
  } catch {
    return false;
  }
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function exactKeys(value, allowed) {
  const allowedKeys = new Set(allowed);
  return Object.keys(value).every((key) => allowedKeys.has(key));
}

function isSurfaceId(value) {
  return typeof value === "string" && SURFACE_ID.test(value);
}

function isBoundedInteger(value, min, max) {
  return Number.isInteger(value) && value >= min && value <= max;
}
