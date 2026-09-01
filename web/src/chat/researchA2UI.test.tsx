// @vitest-environment happy-dom

import type { ActivityMessage } from "@ag-ui/core";
import {
  CopilotKitContext,
  CopilotKitCoreReact,
  EMPTY_SET,
} from "@copilotkit/react-core/v2/context";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  RESEARCH_A2UI_ACTIVITY_TYPE,
  RESEARCH_A2UI_CATALOG_ID,
  RESEARCH_A2UI_PROTOCOL_VERSION,
} from "../../../contracts/research-a2ui.mjs";
import {
  ResearchA2UIActivity,
  researchA2UICatalogDefinitions,
} from "./researchA2UI";

const RUN_ID = "run_0123456789abcdef0123";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean })
  .IS_REACT_ACT_ENVIRONMENT = true;

afterEach(() => {
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

describe("Research A2UI renderer", () => {
  it("keeps the Web catalog exact and rejects extra props in every component", () => {
    expect(Object.keys(researchA2UICatalogDefinitions).sort()).toEqual([
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
    for (const definition of Object.values(researchA2UICatalogDefinitions)) {
      expect(definition.props.safeParse({ unsafeExtraProp: true }).success).toBe(false);
    }
  });

  it("renders the reviewed components through CopilotKit and keeps interactions local", async () => {
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    const root = await mount(activityMessage(readyContent()));

    await vi.waitFor(() => {
      expect(document.querySelector('[aria-label="Alpha proposal: Low-volatility factor"]'))
        .not.toBeNull();
    });
    expect(document.body.textContent).toContain("Research evidence");
    expect(document.body.textContent).toContain("Succeeded");
    expect(document.querySelector(`[aria-label="ResearchRun ${RUN_ID}: succeeded"]`))
      .not.toBeNull();
    expect(document.querySelector('a[href="/research-runs/run_0123456789abcdef0123"]')?.textContent)
      .toContain("Open authoritative ResearchRun");
    expect(document.querySelector("img, iframe, script, style")).toBeNull();

    const copy = [...document.querySelectorAll("button")].find((button) => (
      button.textContent === "Copy"
    ));
    if (copy === undefined) throw new Error("Formula copy control was not rendered");
    await act(async () => copy.click());
    expect(writeText).toHaveBeenCalledWith("rank(-abs(pct_change(close, 1)))");
    expect(document.body.textContent).toContain("Formula copied");

    const metrics = [...document.querySelectorAll("button")].find((button) => (
      button.textContent?.includes("Inspect metrics") === true
    ));
    if (metrics === undefined) throw new Error("Metric disclosure was not rendered");
    expect(metrics.getAttribute("aria-expanded")).toBe("false");
    await act(async () => metrics.click());
    expect(metrics.getAttribute("aria-expanded")).toBe("true");
    const table = document.querySelector("table");
    expect(table?.querySelector("caption")?.textContent).toBe("Authoritative result metrics");
    expect(table?.querySelector('td[data-label="Metric"] .chat-a2ui-cell-value')?.textContent)
      .toBe("Rank IC");

    const provenance = [...document.querySelectorAll("button")].find((button) => (
      button.textContent?.includes("Inspect provenance") === true
    ));
    if (provenance === undefined) throw new Error("Provenance disclosure was not rendered");
    await act(async () => provenance.click());
    expect(document.body.textContent).toContain("Result section");
    expect(document.body.textContent).toContain("factor");

    await act(async () => root.unmount());
  });

  it("renders canonical DailyTrack navigation without enabling Track mutations", async () => {
    const href = "/daily-tracks/track_0123456789abcdef0123";
    const root = await mount(activityMessage(readyContent([{
      component: "Navigation", id: "root", label: "Open DailyTrack", href,
    }])));
    await vi.waitFor(() => expect(document.querySelector(`a[href="${href}"]`)?.textContent).toBe("Open DailyTrack"));
    expect(document.querySelector("button, form, input")).toBeNull();
    await act(async () => root.unmount());
  });

  it("preserves explicit column associations for a large bounded table", async () => {
    const columns = Array.from({ length: 12 }, (_, index) => `Field ${index + 1}`);
    const rows = Array.from({ length: 100 }, (_, row) => (
      columns.map((_, column) => `row ${row + 1}, field ${column + 1}`)
    ));
    const root = await mount(activityMessage(readyContent([{
      caption: "Large authoritative result",
      columns,
      component: "Table",
      id: "root",
      initiallyExpanded: true,
      rows,
      summary: "Inspect all result fields",
    }])));
    await vi.waitFor(() => expect(document.querySelectorAll('td[role="cell"]')).toHaveLength(1_200));
    const headers = [...document.querySelectorAll('th[role="columnheader"]')];
    expect(headers.map((header) => header.textContent)).toEqual(columns);
    expect(document.querySelectorAll('tbody tr[role="row"]')).toHaveLength(100);
    for (const cell of document.querySelectorAll('td[role="cell"]')) {
      const header = document.getElementById(cell.getAttribute("headers") ?? "");
      expect(header?.textContent).toBe(cell.getAttribute("data-label"));
      expect(cell.querySelector(".chat-a2ui-cell-label")?.getAttribute("aria-hidden"))
        .toBe("true");
    }
    await act(async () => root.unmount());
  });

  it("shows deterministic loading and safe-error text without partially rendering invalid UI", async () => {
    const loading = await mount(activityMessage({
      debugExposure: "hidden",
      status: "retrying",
    }, "a2ui-surface-loading"));
    expect(document.querySelector('[role="status"]')?.textContent).toContain(
      "Rebuilding research view",
    );
    await act(async () => loading.unmount());

    const invalid = await mount(activityMessage({
      a2ui_operations: [{
        createSurface: {
          catalogId: RESEARCH_A2UI_CATALOG_ID,
          surfaceId: "unsafe",
        },
        version: RESEARCH_A2UI_PROTOCOL_VERSION,
      }, {
        updateComponents: {
          components: [{
            action: { name: "cancel_research_run" },
            component: "Text",
            id: "root",
            text: "Do not partially render me",
          }],
          surfaceId: "unsafe",
        },
        version: RESEARCH_A2UI_PROTOCOL_VERSION,
      }],
    }, "a2ui-surface-invalid"));
    expect(document.querySelector('[role="alert"]')?.textContent).toContain(
      "could not be displayed",
    );
    expect(document.body.textContent).not.toContain("Do not partially render me");
    expect(document.querySelector("button, a")).toBeNull();
    await act(async () => invalid.unmount());
  });
});

async function mount(message: ActivityMessage): Promise<Root> {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  const copilotkit = new CopilotKitCoreReact({
    deferInitialConnection: true,
    runtimeTransport: "rest",
    runtimeUrl: "/api/agent/copilotkit",
  });
  await act(async () => {
    root.render(
      <CopilotKitContext.Provider value={{ copilotkit, executingToolCallIds: EMPTY_SET }}>
        <ResearchA2UIActivity message={message} />
      </CopilotKitContext.Provider>,
    );
    await Promise.resolve();
  });
  return root;
}

function activityMessage(
  content: Record<string, unknown>,
  id = "a2ui-surface-ready",
): ActivityMessage {
  return {
    activityType: RESEARCH_A2UI_ACTIVITY_TYPE,
    content,
    id,
    role: "activity",
  };
}

function readyContent(components = allComponents()): Record<string, unknown> {
  return {
    a2ui_operations: [
      {
        createSurface: {
          catalogId: RESEARCH_A2UI_CATALOG_ID,
          surfaceId: "research-result",
        },
        version: RESEARCH_A2UI_PROTOCOL_VERSION,
      },
      {
        updateComponents: {
          components,
          surfaceId: "research-result",
        },
        version: RESEARCH_A2UI_PROTOCOL_VERSION,
      },
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
      rows: [["Rank IC", "0.1200"]],
      summary: "Inspect metrics",
    },
    {
      component: "Provenance",
      entries: [
        { label: "ResearchRun", value: RUN_ID },
        { label: "Result section", value: "factor" },
      ],
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
