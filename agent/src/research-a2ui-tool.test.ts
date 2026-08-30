import { describe, expect, it } from "vitest";

import {
  RESEARCH_A2UI_CATALOG_ID,
  RESEARCH_A2UI_PROTOCOL_VERSION,
} from "../../contracts/research-a2ui.mjs";
import { researchA2UITool } from "./research-a2ui-tool.js";

describe("researchA2UITool", () => {
  it("returns one catalog-owned v0.9 operations envelope", async () => {
    const result = await researchA2UITool.execute?.({
      components: [{
        component: "Text",
        id: "root",
        text: "Research result available",
      }],
      data: {},
      surfaceId: "research-result",
    }, { agent: { messages: [], toolCallId: "render-call" } } as never);

    expect(result).toEqual({
      a2ui_operations: [{
        createSurface: {
          catalogId: RESEARCH_A2UI_CATALOG_ID,
          surfaceId: "research-result",
        },
        version: RESEARCH_A2UI_PROTOCOL_VERSION,
      }, {
        updateComponents: {
          components: [{
            component: "Text",
            id: "root",
            text: "Research result available",
          }],
          surfaceId: "research-result",
        },
        version: RESEARCH_A2UI_PROTOCOL_VERSION,
      }],
    });
  });

  it("rejects a surface outside the registered catalog contract", async () => {
    await expect(researchA2UITool.execute?.({
      components: [{ component: "Button", id: "root" }],
      surfaceId: "unsafe-surface",
    }, { agent: { messages: [], toolCallId: "render-call" } } as never)).rejects
      .toThrow("INVALID_RESEARCH_A2UI");
  });

  it("rejects model-authored data bindings instead of silently discarding them", async () => {
    const result = await researchA2UITool.execute?.({
      components: [{ component: "Text", id: "root", text: "Unsafe binding" }],
      data: { secret: "must-not-render" },
      surfaceId: "unsafe-data-binding",
    }, { agent: { messages: [], toolCallId: "render-call" } } as never);

    expect(result).toMatchObject({
      error: true,
      validationErrors: {
        fields: { data: { errors: ["A2UI data bindings are not allowed"] } },
      },
    });
  });
});
