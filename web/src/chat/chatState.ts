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
): ResolvedModelSelection | null {
  const model = requestedModelKey === null
    ? catalog.models.find((candidate) => candidate.key === catalog.default_model_key)
    : catalog.models.find((candidate) => candidate.key === requestedModelKey);
  if (model === undefined) {
    if (requestedModelKey !== null) return null;
    throw new Error("Agent model Catalog has no default model");
  }
  const reasoningEffort = requestedReasoningEffort === null
    ? model.default_reasoning_effort
    : model.reasoning_efforts.find(
        (candidate) => candidate === requestedReasoningEffort,
      );
  if (reasoningEffort === undefined) return null;
  return { model, reasoningEffort };
}
