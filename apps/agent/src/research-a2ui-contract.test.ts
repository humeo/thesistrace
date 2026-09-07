import { describe, expect, it } from "vitest";

import {
  isResearchA2UIMessageId,
  parseResearchA2UINavigationHref,
  projectResearchA2UIContent,
  RESEARCH_A2UI_CATALOG_ID,
  RESEARCH_A2UI_INLINE_CATALOG,
  RESEARCH_A2UI_PROTOCOL_VERSION,
  safeResearchA2UIErrorContent,
} from "@thesistrace/contracts/research-a2ui";

const RUN_ID = "run_0123456789abcdef0123";

describe("Research A2UI contract", () => {
  it("accepts the exact reviewed catalog and canonicalizes a complete surface", () => {
    expect(Object.keys(RESEARCH_A2UI_INLINE_CATALOG.components).sort()).toEqual([
      "AlphaProposal",
      "Column",
      "Divider",
      "Formula",
      "Navigation",
      "Provenance",
      "ResearchRunStatus",
      "ResultMetrics",
      "Row",
      "Table",
      "Text",
    ]);

    const projection = projectResearchA2UIContent(envelope(allComponents(), {}));
    expect(projection).toMatchObject({ kind: "ready", valid: true });
    expect(projection.content).toEqual(envelope(allComponents()));
    expect(JSON.stringify(projection.content)).not.toMatch(/onClick|javascript:|https?:\/\//u);
  });

  it("accepts only safe lifecycle snapshots and stable activity ids", () => {
    expect(projectResearchA2UIContent({
      attempt: 1,
      debugExposure: "visible",
      progressTokens: 12,
      status: "building",
    })).toEqual({
      content: {
        attempt: 1,
        debugExposure: "hidden",
        progressTokens: 12,
        status: "building",
      },
      kind: "loading",
      valid: true,
    });
    expect(projectResearchA2UIContent({
      error: "provider-secret",
      errors: [{ private: true }],
      status: "failed",
    })).toEqual({
      content: safeResearchA2UIErrorContent(),
      kind: "error",
      valid: false,
    });
    expect(isResearchA2UIMessageId("a2ui-surface-provider-call-1")).toBe(true);
    expect(isResearchA2UIMessageId("provider-call-1")).toBe(false);
  });

  it("allows only enumerated same-origin product navigation", () => {
    expect(parseResearchA2UINavigationHref("/data")).toBe("/data");
    expect(parseResearchA2UINavigationHref("/research")).toBe("/research");
    expect(parseResearchA2UINavigationHref(`/research-runs/${RUN_ID}`)).toBe(
      `/research-runs/${RUN_ID}`,
    );
    expect(parseResearchA2UINavigationHref("/daily-tracks/track_0123456789abcdef0123"))
      .toBe("/daily-tracks/track_0123456789abcdef0123");
    for (const value of [
      "https://example.com/research",
      "//example.com/research",
      "javascript:alert(1)",
      "/research-runs/00000000-0000-4000-8000-000000000001",
      "/research-runs/run_0123456789abcdef0123?delete=true",
      "/api/research-runs/run_0123456789abcdef0123",
      "/daily-tracks/track_0123456789abcdef0123/stop",
      "/daily-tracks/track_0123456789abcdef0123?stop=true",
      "/daily-tracks/track_0123456789abcdef0123#retry",
      "/daily-tracks/../api/daily-tracks/track_0123456789abcdef0123",
      "/api/daily-tracks/track_0123456789abcdef0123",
      "/daily-tracks/track_%30%31",
    ]) {
      expect(parseResearchA2UINavigationHref(value)).toBeNull();
    }
  });

  it("accepts a large bounded table while rejecting mismatched cells and oversized rows", () => {
    const table = {
      caption: "Large authoritative table",
      columns: Array.from({ length: 12 }, (_, index) => `Column ${index + 1}`),
      component: "Table",
      id: "root",
      rows: Array.from({ length: 100 }, () => Array.from({ length: 12 }, () => "x".repeat(51))),
      summary: "Inspect all result fields",
    };
    const content = envelope([table]);
    expect(new TextEncoder().encode(JSON.stringify(content)).byteLength).toBeLessThanOrEqual(65_536);
    expect(new TextEncoder().encode(JSON.stringify(content)).byteLength).toBeGreaterThan(64_000);
    expect(projectResearchA2UIContent(content)).toMatchObject({ kind: "ready", valid: true });
    expect(projectResearchA2UIContent(envelope([{ ...table, rows: [["one cell"]] }])))
      .toMatchObject({ kind: "error", valid: false });
    expect(projectResearchA2UIContent(envelope([{ ...table, rows: [...table.rows, table.rows[0]] }])))
      .toMatchObject({ kind: "error", valid: false });
  });

  it.each([
    ["unknown component", () => replaceComponent("formula", { component: "Video", id: "formula", src: "https://example.com/a" })],
    ["model-authored action", () => replaceComponent("formula", { ...component("formula"), onClick: { action: "cancel" } })],
    ["raw HTML", () => replaceComponent("text", { ...component("text"), html: "<script>alert(1)</script>" })],
    ["unsafe navigation", () => replaceComponent("navigation", { ...component("navigation"), href: "https://example.com" })],
    ["unsafe ResearchRun id", () => replaceComponent("status", { ...component("status"), runId: "../../etc/passwd" })],
    ["unresolved child", () => replaceComponent("root", { ...component("root"), children: ["missing"] })],
    ["multiple parents", () => replaceComponent("row", { ...component("row"), children: ["text", "formula"] })],
  ])("rejects %s as one stable safe error", (_name, mutate) => {
    expect(projectResearchA2UIContent(envelope(mutate()))).toEqual({
      content: safeResearchA2UIErrorContent(),
      kind: "error",
      valid: false,
    });
  });

  it("rejects cycles, excessive depth, excessive size, and incomplete operations", () => {
    const cyclic = [
      { children: ["second"], component: "Column", id: "root" },
      { children: ["root"], component: "Column", id: "second" },
    ];
    const deep = Array.from({ length: 9 }, (_, index) => ({
      children: [index === 8 ? "leaf" : `depth-${index + 1}`],
      component: "Column",
      id: index === 0 ? "root" : `depth-${index}`,
    })).concat([{ component: "Text", id: "leaf", text: "leaf" } as never]);
    const tooMany = [{
      children: Array.from({ length: 16 }, (_, index) => `group-${index}`),
      component: "Column",
      id: "root",
    }, ...Array.from({ length: 16 }, (_, group) => ({
      children: Array.from({ length: 4 }, (_, item) => `item-${group}-${item}`),
      component: "Column",
      id: `group-${group}`,
    })), ...Array.from({ length: 64 }, (_, index) => ({
      component: "Text",
      id: `item-${Math.floor(index / 4)}-${index % 4}`,
      text: "item",
    }))];
    const tooLarge = [{
      component: "Text",
      id: "root",
      text: "x".repeat(65 * 1024),
    }];
    const incomplete = {
      a2ui_operations: [envelope(allComponents()).a2ui_operations[0]],
    };

    for (const candidate of [
      envelope(cyclic),
      envelope(deep),
      envelope(tooMany),
      envelope(tooLarge),
      incomplete,
    ]) {
      expect(projectResearchA2UIContent(candidate)).toMatchObject({
        content: safeResearchA2UIErrorContent(),
        kind: "error",
        valid: false,
      });
    }
  });
});

function envelope(
  components: readonly Record<string, unknown>[],
  data?: Record<string, unknown>,
) {
  return {
    a2ui_operations: [
      {
        createSurface: { catalogId: RESEARCH_A2UI_CATALOG_ID, surfaceId: "research-result" },
        version: RESEARCH_A2UI_PROTOCOL_VERSION,
      },
      {
        updateComponents: { components, surfaceId: "research-result" },
        version: RESEARCH_A2UI_PROTOCOL_VERSION,
      },
      ...(data === undefined ? [] : [{
        updateDataModel: { path: "/", surfaceId: "research-result", value: data },
        version: RESEARCH_A2UI_PROTOCOL_VERSION,
      }]),
    ],
  };
}

function allComponents(): Record<string, unknown>[] {
  return [
    {
      children: ["row", "formula", "proposal", "status", "metrics", "table", "provenance", "navigation"],
      component: "Column",
      gap: "normal",
      id: "root",
    },
    { align: "center", children: ["text", "divider"], component: "Row", gap: "compact", id: "row" },
    { component: "Text", id: "text", text: "Research evidence", variant: "title" },
    { component: "Divider", id: "divider" },
    { component: "Formula", expression: "rank(-abs(pct_change(close, 1)))", id: "formula", label: "Alpha formula" },
    {
      component: "AlphaProposal",
      explanation: "Tests whether lower recent volatility identifies more stable stocks.",
      formula: "rank(-abs(pct_change(close, 1)))",
      hypothesis: "Lower recent volatility may predict stable near-term returns.",
      id: "proposal",
      period: "2026-01-01 to 2026-08-28",
      researchType: "Factor Evaluation",
      strategy: [{ label: "Neutralization", value: "none" }],
      title: "Low-volatility factor",
      universe: "top1000",
    },
    {
      component: "ResearchRunStatus",
      formula: "rank(-abs(pct_change(close, 1)))",
      id: "status",
      phase: "Result available",
      runId: RUN_ID,
      status: "succeeded",
    },
    {
      component: "ResultMetrics",
      id: "metrics",
      metrics: [{ label: "Rank IC", value: "0.1200" }],
      title: "Factor result",
    },
    {
      caption: "Authoritative result metrics",
      columns: ["Metric", "Value"],
      component: "Table",
      id: "table",
      initiallyExpanded: false,
      rows: [["Rank IC", "0.1200"]],
      summary: "Inspect metrics",
    },
    {
      component: "Provenance",
      entries: [{ label: "ResearchRun", value: RUN_ID }],
      id: "provenance",
      summary: "Inspect provenance",
    },
    {
      component: "Navigation",
      href: `/research-runs/${RUN_ID}`,
      id: "navigation",
      label: "Open authoritative ResearchRun",
    },
  ];
}

function component(id: string): Record<string, unknown> {
  const found = allComponents().find((candidate) => candidate.id === id);
  if (found === undefined) throw new Error(`Missing test component: ${id}`);
  return found;
}

function replaceComponent(id: string, replacement: Record<string, unknown>): Record<string, unknown>[] {
  return allComponents().map((candidate) => candidate.id === id ? replacement : candidate);
}
