import { describe, expect, it } from "vitest";
import { standardSchemaToJSONSchema } from "@mastra/core/schema";

import {
  RESEARCH_A2UI_CATALOG_ID,
  RESEARCH_A2UI_PROTOCOL_VERSION,
} from "../../contracts/research-a2ui.mjs";
import { researchA2UITool } from "./research-a2ui-tool.js";

describe("researchA2UITool", () => {
  it("advertises the registered flat component fields to the model", () => {
    const schema = standardSchemaToJSONSchema(researchA2UITool.inputSchema!, { io: "input" });
    expect(schema).toMatchObject({
      properties: {
        components: {
          minItems: 1,
          maxItems: 64,
          items: { anyOf: expect.arrayContaining([
            expect.objectContaining({
              additionalProperties: false,
              properties: expect.objectContaining({
                id: expect.objectContaining({ type: "string" }),
                component: { type: "string", const: "Text" },
                text: expect.objectContaining({ type: "string" }),
              }),
              required: ["id", "component", "text"],
            }),
            expect.objectContaining({
              properties: expect.objectContaining({
                component: { type: "string", const: "Column" },
                children: expect.objectContaining({ type: "array", items: expect.objectContaining({ type: "string" }) }),
              }),
              required: ["id", "component", "children"],
            }),
          ]) },
        },
      },
    });
  });

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
    const result = await researchA2UITool.execute?.({
      components: [{ component: "Button", id: "root" }],
      surfaceId: "unsafe-surface",
    }, { agent: { messages: [], toolCallId: "render-call" } } as never);
    expect(result).toMatchObject({
      error: true,
      validationErrors: { fields: { components: expect.any(Object) } },
    });
    expect(result).not.toHaveProperty("a2ui_operations");
  });

  it("rejects model-authored data bindings instead of silently discarding them", async () => {
    const result = await researchA2UITool.execute?.({
      components: [{ component: "Text", id: "root", text: "Unsafe binding" }],
      data: { secret: "must-not-render" },
      surfaceId: "unsafe-data-binding",
    } as never, { agent: { messages: [], toolCallId: "render-call" } } as never);

    expect(result).toMatchObject({
      error: true,
      validationErrors: {
        fields: { data: { errors: expect.arrayContaining([expect.any(String)]) } },
      },
    });
    expect(result).not.toHaveProperty("a2ui_operations");
  });

  it("still rejects invalid graph references after component-schema validation", async () => {
    await expect(researchA2UITool.execute?.({
      components: [{ component: "Column", id: "root", children: ["missing-child"] }],
      surfaceId: "invalid-references",
    }, { agent: { messages: [], toolCallId: "render-call" } } as never)).rejects
      .toThrow("INVALID_RESEARCH_A2UI");
  });
});
