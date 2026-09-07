import { createTool } from "@mastra/core/tools";
import { toStandardSchema } from "@mastra/core/schema";

import {
  RESEARCH_A2UI_CATALOG_ID,
  RESEARCH_A2UI_INLINE_CATALOG,
  RESEARCH_A2UI_MAX_COMPONENTS,
  RESEARCH_A2UI_PROTOCOL_VERSION,
  projectResearchA2UIContent,
} from "@thesistrace/contracts/research-a2ui";

export const RESEARCH_A2UI_TOOL_NAME = "render_a2ui";

// The same catalog drives model-visible fields and input validation. A generic
// record schema hides the component contract and makes the model guess it.
const inputSchema = toStandardSchema<{
  components: Record<string, unknown>[];
  data?: Record<string, never>;
  surfaceId: string;
}>({
  type: "object",
  additionalProperties: false,
  required: ["surfaceId", "components"],
  properties: {
    surfaceId: { type: "string", pattern: "^[a-z][a-z0-9-]{0,63}$", description: "Unique lowercase-hyphenated surface ID." },
    data: { type: "object", additionalProperties: false, maxProperties: 0, description: "Omit or use an empty object; data bindings are forbidden." },
    components: {
      type: "array", minItems: 1, maxItems: RESEARCH_A2UI_MAX_COMPONENTS,
      description: "Flat A2UI v0.9 component array, with id root. Layout children reference IDs, not nested objects. Use literal registered fields only.",
      items: {
        anyOf: Object.entries(RESEARCH_A2UI_INLINE_CATALOG.components).map(([component, definition]) => ({
          ...definition,
          properties: {
            id: { type: "string" as const, pattern: "^[A-Za-z][A-Za-z0-9_-]{0,63}$" },
            component: { type: "string" as const, const: component },
            ...definition.properties,
          },
          required: ["id", "component", ...(definition.required ?? [])],
        })),
      },
    },
  },
});

export const researchA2UITool = createTool({
  id: RESEARCH_A2UI_TOOL_NAME,
  description: "Render one validated ThesisTrace A2UI research surface.",
  inputSchema,
  execute: async (input) => {
    if (input.data !== undefined && Object.keys(input.data).length !== 0) {
      throw new Error("INVALID_RESEARCH_A2UI");
    }
    const content = {
      a2ui_operations: [
        {
          createSurface: {
            catalogId: RESEARCH_A2UI_CATALOG_ID,
            surfaceId: input.surfaceId,
          },
          version: RESEARCH_A2UI_PROTOCOL_VERSION,
        },
        {
          updateComponents: {
            components: input.components,
            surfaceId: input.surfaceId,
          },
          version: RESEARCH_A2UI_PROTOCOL_VERSION,
        },
      ],
    };
    const projected = projectResearchA2UIContent(content);
    if (!projected.valid || projected.kind !== "ready") {
      throw new Error("INVALID_RESEARCH_A2UI");
    }
    return projected.content;
  },
});
