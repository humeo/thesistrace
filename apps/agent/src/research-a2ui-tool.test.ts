import { describe, expect, it } from "vitest";
import { standardSchemaToJSONSchema } from "@mastra/core/schema";
import { projectResearchA2UIContent } from "@thesistrace/contracts/research-a2ui";
import { researchA2UITool } from "./research-a2ui-tool.js";

const runId = "run_0123456789abcdef0123";
const context = { agent: { messages: [], toolCallId: "render-call" } } as never;
describe("researchA2UITool", () => {
  it("renders ordered resource IDs without asking the model to build a component graph", async () => {
    const result = await researchA2UITool.execute?.({ view: "research_runs", runIds: [runId, "run_abcdef0123456789abcd"] } as never, context);
    expect(projectResearchA2UIContent(result)).toMatchObject({ valid: true, kind: "ready" });
    expect(result).toMatchObject({ a2ui_operations: [
      { createSurface: { surfaceId: expect.stringMatching(/^research-[a-f0-9]+$/) } },
      { updateComponents: { components: [{ id: "root", component: "ResearchComparison", runIds: [runId, "run_abcdef0123456789abcd"] }] } },
    ] });
    const schema = JSON.stringify(standardSchemaToJSONSchema(researchA2UITool.inputSchema!, { io: "input" }));
    expect(schema).toContain("research_runs");
    expect(schema).not.toMatch(/surfaceId|components|children|gap|align/);
  });
  it("renders a Chat-owned proposal and a current DailyTrack using fixed templates", async () => {
    const proposal = { title: "Momentum", hypothesis: "Recent strength persists", formula: "rank(close)",
      universe: "top1000", period: "2026-01-01 to 2026-09-30", researchType: "Factor Evaluation",
      strategy: [{ label: "Neutralization", value: "none" }], explanation: "Test cross-sectional persistence." };
    const result = await researchA2UITool.execute?.({ view: "alpha_proposal", proposal }, context);
    expect(result).toMatchObject({ a2ui_operations: [expect.any(Object), { updateComponents: {
      components: [{ id: "root", component: "AlphaProposal", ...proposal }],
    } }] });
    const track = await researchA2UITool.execute?.({ view: "daily_track", trackId: "track_0123456789abcdef0123" }, context);
    expect(projectResearchA2UIContent(track)).toMatchObject({ valid: true, kind: "ready" });
    expect(track).toMatchObject({ a2ui_operations: [expect.any(Object), { updateComponents: {
      components: [{ id: "root", component: "DailyTrack", trackId: "track_0123456789abcdef0123" }],
    } }] });
  });
  it("gives the model a field and reason for duplicate resources while keeping browser errors safe", async () => {
    const result = await researchA2UITool.execute?.({ view: "research_runs", runIds: [runId, runId] }, context);
    expect(result).toMatchObject({ error: true, code: "INVALID_RESEARCH_VIEW", issues: [
      { path: "runIds", message: "Resource IDs must be distinct" },
    ] });
    expect(result).not.toHaveProperty("a2ui_operations");
    expect(projectResearchA2UIContent(result).content).toMatchObject({ debugExposure: "hidden", status: "failed" });
    expect(JSON.stringify(projectResearchA2UIContent(result).content)).not.toContain("Resource IDs must be distinct");
  });
  it.each([
    { view: "research_runs", runIds: ["../../private"] },
    { view: "research_runs", runIds: [runId], components: [{ component: "Button" }] },
    { view: "daily_track", trackId: "track_0123456789abcdef0123", data: { secret: "private" } },
  ])("rejects invalid fields, component graphs and data bindings", async input => {
    const result = await researchA2UITool.execute?.(input as never, context);
    expect(result).toMatchObject({ error: true, validationErrors: expect.any(Object) });
    expect(result).not.toHaveProperty("a2ui_operations");
  });
});
