import { describe, expect, it } from "vitest";

import {
  chatNavigationReducer,
  initialChatNavigationState,
  resolveModelSelection,
} from "./chatState";
import type { AgentModelCatalog } from "./modelCatalog";

const catalog: AgentModelCatalog = {
  default_model_key: "primary",
  models: [
    {
      default_reasoning_effort: "medium",
      display_name: "Primary",
      key: "primary",
      reasoning_efforts: ["low", "medium"],
    },
    {
      default_reasoning_effort: "high",
      display_name: "Deep",
      key: "deep",
      reasoning_efforts: ["high", "xhigh"],
    },
  ],
};

describe("Chat shell state", () => {
  it("toggles desktop collapse independently of the mobile drawer", () => {
    const collapsed = chatNavigationReducer(initialChatNavigationState, {
      type: "toggle-sidebar",
    });
    const opened = chatNavigationReducer(collapsed, {
      type: "open-mobile-navigation",
    });
    const closed = chatNavigationReducer(opened, {
      type: "close-mobile-navigation",
    });

    expect(collapsed).toEqual({ mobileNavigationOpen: false, sidebarCollapsed: true });
    expect(opened).toEqual({ mobileNavigationOpen: true, sidebarCollapsed: true });
    expect(closed).toEqual({ mobileNavigationOpen: false, sidebarCollapsed: true });
  });

  it("constrains reasoning to the selected model and uses registered defaults", () => {
    expect(resolveModelSelection(catalog, null, null)).toMatchObject({
      model: { key: "primary" },
      reasoningEffort: "medium",
    });
    expect(resolveModelSelection(catalog, "deep", "low")).toBeNull();
    expect(resolveModelSelection(catalog, "removed", "high")).toBeNull();
    expect(resolveModelSelection(catalog, "deep", "xhigh")).toMatchObject({
      model: { key: "deep" },
      reasoningEffort: "xhigh",
    });
  });
});
