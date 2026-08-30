import { createTool } from "@mastra/core/tools";
import { z } from "zod";

import {
  RESEARCH_A2UI_CATALOG_ID,
  RESEARCH_A2UI_PROTOCOL_VERSION,
  projectResearchA2UIContent,
} from "../../contracts/research-a2ui.mjs";

export const RESEARCH_A2UI_TOOL_NAME = "render_a2ui";

const inputSchema = z.object({
  components: z.array(z.record(z.string(), z.unknown())),
  data: z.record(z.string(), z.unknown()).refine(
    (value) => Object.keys(value).length === 0,
    "A2UI data bindings are not allowed",
  ).optional(),
  surfaceId: z.string(),
}).strict();

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
