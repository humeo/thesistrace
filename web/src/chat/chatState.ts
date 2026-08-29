import type {
  AgentModel,
  AgentModelCatalog,
  ReasoningEffort,
} from "./modelCatalog";

export type ChatNavigationState = Readonly<{
  mobileNavigationOpen: boolean;
  sidebarCollapsed: boolean;
}>;
export type ChatNavigationAction =
  | Readonly<{ type: "close-mobile-navigation" }>
  | Readonly<{ type: "open-mobile-navigation" }>
  | Readonly<{ type: "toggle-sidebar" }>;

export const initialChatNavigationState: ChatNavigationState = {
  mobileNavigationOpen: false,
  sidebarCollapsed: false,
};

export function chatNavigationReducer(
  state: ChatNavigationState,
  action: ChatNavigationAction,
): ChatNavigationState {
  switch (action.type) {
    case "close-mobile-navigation":
      return { ...state, mobileNavigationOpen: false };
    case "open-mobile-navigation":
      return { ...state, mobileNavigationOpen: true };
    case "toggle-sidebar":
      return { ...state, sidebarCollapsed: !state.sidebarCollapsed };
  }
}

export type ResolvedModelSelection = Readonly<{
  model: AgentModel;
  reasoningEffort: ReasoningEffort;
}>;

export function resolveModelSelection(
  catalog: AgentModelCatalog,
  requestedModelKey: string | null,
  requestedReasoningEffort: string | null,
): ResolvedModelSelection {
  const model = catalog.models.find((candidate) => candidate.key === requestedModelKey)
    ?? catalog.models.find((candidate) => candidate.key === catalog.default_model_key);
  if (model === undefined) throw new Error("Agent model Catalog has no default model");
  const reasoningEffort = model.reasoning_efforts.find(
    (candidate) => candidate === requestedReasoningEffort,
  ) ?? model.default_reasoning_effort;
  return { model, reasoningEffort };
}
