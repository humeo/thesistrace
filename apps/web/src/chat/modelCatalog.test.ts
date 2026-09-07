import { describe, expect, it } from "vitest";

import { AgentCatalogInvalidError, decodeAgentModelCatalog } from "./modelCatalog";

const catalog = {
  default_model_key: "research-primary",
  models: [
    {
      default_reasoning_effort: "medium",
      display_name: "Research Primary",
      key: "research-primary",
      reasoning_efforts: ["low", "medium", "high"],
    },
    {
      default_reasoning_effort: "high",
      display_name: "Research Deep",
      key: "research-deep",
      reasoning_efforts: ["high", "xhigh"],
    },
  ],
};

describe("Agent model Catalog", () => {
  it("decodes only the exact browser-safe schema", () => {
    expect(decodeAgentModelCatalog(catalog)).toEqual(catalog);
  });

  it.each([
    { ...catalog, provider_secret: "secret-canary" },
    { ...catalog, default_model_key: "missing" },
    { ...catalog, models: [] },
    {
      ...catalog,
      models: [{ ...catalog.models[0], provider_model_id: "private-provider-id" }],
    },
    {
      ...catalog,
      models: [{ ...catalog.models[0], reasoning_efforts: ["automatic"] }],
    },
    {
      ...catalog,
      models: [{ ...catalog.models[0], display_name: "Research\u202ePrimary" }],
    },
    {
      ...catalog,
      models: [catalog.models[0], { ...catalog.models[1], key: "research-primary" }],
    },
  ])("rejects an invalid or expanded Catalog payload", (payload) => {
    expect(() => decodeAgentModelCatalog(payload)).toThrow(AgentCatalogInvalidError);
  });
});
