import { randomUUID } from "node:crypto";
import { createTool } from "@mastra/core/tools";
import { toStandardSchema } from "@mastra/core/schema";
import {
  RESEARCH_A2UI_VIEW_SCHEMA,
  RESEARCH_A2UI_VIEW_JSON_SCHEMA,
  createResearchA2UIView,
  projectResearchA2UIContent,
  type ResearchA2UIViewInput,
} from "@thesistrace/contracts/research-a2ui";
import { RESEARCH_A2UI_TOOL_NAME, researchA2UIModelOutput } from "./research-a2ui-model-output.js";

export { RESEARCH_A2UI_TOOL_NAME } from "./research-a2ui-model-output.js";
const inputSchema = toStandardSchema<ResearchA2UIViewInput>(RESEARCH_A2UI_VIEW_JSON_SCHEMA);
export const researchA2UITool = createTool({
  id: RESEARCH_A2UI_TOOL_NAME,
  description: "Display a fixed research_runs list, unsubmitted alpha_proposal, or daily_track view. Supply authoritative resource IDs or proposal fields; the application owns layout. Write explanations and ordinary tables in the normal Markdown response. Successful UI output is display-only: an empty model result means success and must not cause a retry. Validation errors remain visible for correction.",
  inputSchema,
  toModelOutput: researchA2UIModelOutput,
  execute: async input => {
    const validation = RESEARCH_A2UI_VIEW_SCHEMA.safeParse(input);
    if (!validation.success) {
      return { error: true, code: "INVALID_RESEARCH_VIEW", issues: validation.error.issues.map(issue => ({
        path: issue.path.join("."), message: issue.message,
      })) };
    }
    const content = createResearchA2UIView(validation.data, `research-${randomUUID().replaceAll("-", "")}`);
    const projected = projectResearchA2UIContent(content);
    if (!projected.valid || projected.kind !== "ready") {
      return { error: true, code: "RESEARCH_VIEW_SIZE_LIMIT", issues: [{ path: "proposal", message: "The encoded view exceeds 64 KiB. Shorten the proposal text." }] };
    }
    return projected.content;
  },
});
