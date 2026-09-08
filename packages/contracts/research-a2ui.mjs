export const RESEARCH_A2UI_ACTIVITY_TYPE = "a2ui-surface";
export const RESEARCH_A2UI_CATALOG_ID = "urn:thesistrace:a2ui:research:v0.9";
export const RESEARCH_A2UI_PROTOCOL_VERSION = "v0.9";
const RESEARCH_A2UI_MAX_BYTES = 64 * 1024;
export const RESEARCH_A2UI_MAX_COMPONENTS = 64;
const RESEARCH_A2UI_MAX_DEPTH = 8;

const string = (maxLength, description) => ({
  description,
  maxLength,
  minLength: 1,
  type: "string",
});
const stringArray = (maxItems, maxLength, description) => ({
  description,
  items: string(maxLength),
  maxItems,
  minItems: 1,
  type: "array",
});
const objectArray = (maxItems, properties, required, description) => ({
  description,
  items: {
    additionalProperties: false,
    properties,
    required,
    type: "object",
  },
  maxItems,
  minItems: 1,
  type: "array",
});

export const RESEARCH_A2UI_INLINE_CATALOG = Object.freeze({
  catalogId: RESEARCH_A2UI_CATALOG_ID,
  components: Object.freeze({
    Text: {
      additionalProperties: false,
      description: "Bounded plain text. Never renders HTML.",
      properties: {
        text: string(4_000, "Literal display text."),
        variant: {
          enum: ["body", "caption", "label", "title"],
          type: "string",
        },
      },
      required: ["text"],
      type: "object",
    },
    Row: {
      additionalProperties: false,
      description: "Horizontal layout for referenced child component IDs.",
      properties: {
        align: { enum: ["start", "center", "end", "stretch"], type: "string" },
        children: stringArray(16, 64, "Child component IDs."),
        gap: { enum: ["compact", "normal", "wide"], type: "string" },
      },
      required: ["children"],
      type: "object",
    },
    Column: {
      additionalProperties: false,
      description: "Vertical layout for referenced child component IDs.",
      properties: {
        align: { enum: ["start", "center", "end", "stretch"], type: "string" },
        children: stringArray(16, 64, "Child component IDs."),
        gap: { enum: ["compact", "normal", "wide"], type: "string" },
      },
      required: ["children"],
      type: "object",
    },
    Divider: {
      additionalProperties: false,
      description: "One hairline section divider.",
      properties: {},
      type: "object",
    },
    Formula: {
      additionalProperties: false,
      description: "A read-only Alpha formula with a local copy control.",
      properties: {
        expression: string(8_192, "Validated Alpha expression to display."),
        label: string(80, "Short semantic label."),
      },
      required: ["expression"],
      type: "object",
    },
    AlphaProposal: {
      additionalProperties: false,
      description: "Chat-owned Alpha proposal; never implies a persisted ResearchRun.",
      properties: {
        explanation: string(4_000, "Why the proposal tests the hypothesis."),
        formula: string(8_192, "Proposed Alpha expression."),
        hypothesis: string(2_000, "Testable investment hypothesis."),
        period: string(120, "Proposed research period."),
        researchType: string(80, "Proposed Research type."),
        strategy: objectArray(16, {
          label: string(80, "Strategy parameter name."),
          value: string(240, "Strategy parameter display value."),
        }, ["label", "value"], "Proposed strategy parameters."),
        title: string(160, "Proposal title."),
        universe: string(160, "Proposed security universe."),
      },
      required: [
        "title",
        "hypothesis",
        "formula",
        "universe",
        "period",
        "researchType",
        "strategy",
        "explanation",
      ],
      type: "object",
    },
    ResearchRun: {
      additionalProperties: false,
      description: "Show a ResearchRun by ID. The client reads current authoritative status, formula and results; never supply those facts.",
      properties: { runId: { type: "string", pattern: "^run_[a-f0-9]{20}$" } },
      required: ["runId"], type: "object",
    },
    ResearchComparison: {
      additionalProperties: false,
      description: "Compare up to 20 ResearchRuns in the supplied order using client-fetched authoritative results.",
      properties: { runIds: { type: "array", minItems: 1, maxItems: 20, uniqueItems: true, items: { type: "string", pattern: "^run_[a-f0-9]{20}$" } } },
      required: ["runIds"], type: "object",
    },
    DailyTrack: {
      additionalProperties: false,
      description: "Show the current DailyTrack by ID, loaded by the authenticated client. This is a live view, not a historical snapshot.",
      properties: { trackId: { type: "string", pattern: "^track_[a-f0-9]{20}$" } },
      required: ["trackId"], type: "object",
    },
    Table: {
      additionalProperties: false,
      description: "Non-authoritative explanatory table. For research metrics use ResearchComparison; never copy Result values into this table.",
      properties: {
        caption: string(240, "Accessible table caption."),
        columns: stringArray(12, 80, "Column headings."),
        initiallyExpanded: { type: "boolean" },
        rows: {
          items: {
            items: { maxLength: 320, type: "string" },
            maxItems: 12,
            minItems: 1,
            type: "array",
          },
          maxItems: 100,
          type: "array",
        },
        summary: string(160, "Disclosure label."),
      },
      required: ["caption", "columns", "rows", "summary"],
      type: "object",
    },
    Navigation: {
      additionalProperties: false,
      description: "Link to an allowlisted same-origin ThesisTrace product route.",
      properties: {
        href: string(240, "Known same-origin product route."),
        label: string(120, "Accessible navigation label."),
      },
      required: ["label", "href"],
      type: "object",
    },
  }),
});

const COMPONENT_ID = /^[A-Za-z][A-Za-z0-9_-]{0,63}$/;
const MESSAGE_ID = /^a2ui-surface-[A-Za-z0-9._:-]{1,200}$/;
const SURFACE_ID = /^[a-z][a-z0-9-]{0,63}$/;
const RESEARCH_RUN_ID = /^run_[a-f0-9]{20}$/;

const TEXT_VARIANTS = new Set(["body", "caption", "label", "title"]);
const LAYOUT_ALIGNS = new Set(["start", "center", "end", "stretch"]);
const LAYOUT_GAPS = new Set(["compact", "normal", "wide"]);
const COMPONENT_NAMES = new Set(Object.keys(RESEARCH_A2UI_INLINE_CATALOG.components));

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
  if (typeof value.component !== "string" || !COMPONENT_NAMES.has(value.component)) return null;
  const base = { component: value.component, id: value.id };
  switch (value.component) {
    case "Text":
      if (!exactKeys(value, ["component", "id", "text", "variant"]) || !validString(value.text, 4_000)) return null;
      if (value.variant !== undefined && !TEXT_VARIANTS.has(value.variant)) return null;
      return { ...base, text: value.text, ...(value.variant === undefined ? {} : { variant: value.variant }) };
    case "Row":
    case "Column": {
      if (!exactKeys(value, ["align", "children", "component", "gap", "id"])) return null;
      if (!validStringArray(value.children, 16, 64, COMPONENT_ID)) return null;
      if (value.align !== undefined && !LAYOUT_ALIGNS.has(value.align)) return null;
      if (value.gap !== undefined && !LAYOUT_GAPS.has(value.gap)) return null;
      return {
        ...base,
        children: [...value.children],
        ...(value.align === undefined ? {} : { align: value.align }),
        ...(value.gap === undefined ? {} : { gap: value.gap }),
      };
    }
    case "Divider":
      return exactKeys(value, ["component", "id"]) ? base : null;
    case "Formula":
      if (!exactKeys(value, ["component", "expression", "id", "label"]) || !validString(value.expression, 8_192)) return null;
      if (value.label !== undefined && !validString(value.label, 80)) return null;
      return { ...base, expression: value.expression, ...(value.label === undefined ? {} : { label: value.label }) };
    case "AlphaProposal":
      return projectAlphaProposal(value, base);
    case "ResearchRun":
      return exactKeys(value, ["component", "id", "runId"]) && typeof value.runId === "string" && RESEARCH_RUN_ID.test(value.runId) ? { ...base, runId: value.runId } : null;
    case "ResearchComparison":
      return exactKeys(value, ["component", "id", "runIds"]) && validStringArray(value.runIds, 20, 24, RESEARCH_RUN_ID) && new Set(value.runIds).size === value.runIds.length ? { ...base, runIds: [...value.runIds] } : null;
    case "DailyTrack":
      return exactKeys(value, ["component", "id", "trackId"]) && typeof value.trackId === "string" && /^track_[a-f0-9]{20}$/.test(value.trackId) ? { ...base, trackId: value.trackId } : null;
    case "Table":
      return projectTable(value, base);
    case "Navigation": {
      if (!exactKeys(value, ["component", "href", "id", "label"]) || !validString(value.label, 120)) return null;
      const href = parseResearchA2UINavigationHref(value.href);
      return href === null ? null : { ...base, href, label: value.label };
    }
    default:
      return null;
  }
}

function projectAlphaProposal(value, base) {
  const keys = ["component", "explanation", "formula", "hypothesis", "id", "period", "researchType", "strategy", "title", "universe"];
  if (!exactKeys(value, keys)) return null;
  const limits = { explanation: 4_000, formula: 8_192, hypothesis: 2_000, period: 120, researchType: 80, title: 160, universe: 160 };
  for (const [key, limit] of Object.entries(limits)) {
    if (!validString(value[key], limit)) return null;
  }
  const strategy = projectPairs(value.strategy, 16, 80, 240);
  return strategy === null ? null : {
    ...base,
    explanation: value.explanation,
    formula: value.formula,
    hypothesis: value.hypothesis,
    period: value.period,
    researchType: value.researchType,
    strategy,
    title: value.title,
    universe: value.universe,
  };
}

function projectTable(value, base) {
  if (!exactKeys(value, ["caption", "columns", "component", "id", "initiallyExpanded", "rows", "summary"])) return null;
  if (!validString(value.caption, 240) || !validString(value.summary, 160)) return null;
  if (!validStringArray(value.columns, 12, 80) || !Array.isArray(value.rows) || value.rows.length > 100) return null;
  if (value.initiallyExpanded !== undefined && typeof value.initiallyExpanded !== "boolean") return null;
  const rows = [];
  for (const row of value.rows) {
    if (!Array.isArray(row) || row.length !== value.columns.length || !validStringArray(row, 12, 320, undefined, true)) return null;
    rows.push([...row]);
  }
  return {
    ...base,
    caption: value.caption,
    columns: [...value.columns],
    rows,
    summary: value.summary,
    ...(value.initiallyExpanded === undefined ? {} : { initiallyExpanded: value.initiallyExpanded }),
  };
}

function projectPairs(value, maxItems, labelLimit, valueLimit) {
  if (!Array.isArray(value) || value.length === 0 || value.length > maxItems) return null;
  const result = [];
  for (const entry of value) {
    if (!isRecord(entry) || !exactKeys(entry, ["label", "value"])) return null;
    if (!validString(entry.label, labelLimit) || !validString(entry.value, valueLimit)) return null;
    result.push({ label: entry.label, value: entry.value });
  }
  return result;
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

function validString(value, maxLength, allowEmpty = false) {
  return typeof value === "string" && value.length <= maxLength && (allowEmpty || value.length > 0);
}

function validStringArray(value, maxItems, maxLength, pattern, allowEmpty = false) {
  return Array.isArray(value)
    && value.length > 0
    && value.length <= maxItems
    && value.every((item) => validString(item, maxLength, allowEmpty) && (pattern === undefined || pattern.test(item)));
}

function isBoundedInteger(value, min, max) {
  return Number.isInteger(value) && value >= min && value <= max;
}
