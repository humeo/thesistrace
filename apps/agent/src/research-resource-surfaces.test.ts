import { expect, test } from "vitest";
import { projectResearchA2UIContent, RESEARCH_A2UI_CATALOG_ID, RESEARCH_A2UI_PROTOCOL_VERSION } from "@thesistrace/contracts/research-a2ui";
const runId = "run_0123456789abcdef0123";
const envelope = (component: Record<string, unknown>) => ({ a2ui_operations: [
  { version: RESEARCH_A2UI_PROTOCOL_VERSION, createSurface: { catalogId: RESEARCH_A2UI_CATALOG_ID, surfaceId: "resources" } },
  { version: RESEARCH_A2UI_PROTOCOL_VERSION, updateComponents: { surfaceId: "resources", components: [{ id: "root", ...component }] } },
] });
test("research cards accept references and reject model-authored facts", () => {
  expect(projectResearchA2UIContent(envelope({ component: "ResearchRun", runId })).valid).toBe(true);
  expect(projectResearchA2UIContent(envelope({ component: "ResearchComparison", runIds: [runId] })).valid).toBe(true);
  expect(projectResearchA2UIContent(envelope({ component: "DailyTrack", trackId: "track_0123456789abcdef0123" })).valid).toBe(true);
  for (const extra of [{ status: "succeeded" }, { metrics: [] }, { formula: "close" }]) {
    expect(projectResearchA2UIContent(envelope({ component: "ResearchRun", runId, ...extra })).valid).toBe(false);
  }
  for (const component of ["ResearchRunStatus", "ResultMetrics", "Provenance"]) {
    expect(projectResearchA2UIContent(envelope({ component, runId, status: "succeeded", formula: "close", title: "Result", metrics: [{ label: "Sharpe", value: "99" }] })).valid).toBe(false);
  }
  expect(projectResearchA2UIContent(envelope({ component: "ResearchComparison", runIds: [runId, runId] })).valid).toBe(false);
});
test("projection retains only safe diagnostic codes", () => {
  const invalid = projectResearchA2UIContent(envelope({ component: "unknown" }));
  expect(invalid.content).toMatchObject({ status: "failed", errorCode: "INVALID_OPERATIONS" });
  expect(projectResearchA2UIContent(invalid.content).content).toEqual(invalid.content);
  const failed = projectResearchA2UIContent({ status: "failed", error: "secret", errorCode: "secret" });
  expect(JSON.stringify(failed)).not.toContain("secret");
});
