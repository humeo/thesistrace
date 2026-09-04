import type { ChatTurn } from "./chatProtocol";
import type { AgentModel, AgentModelCatalog, ReasoningEffort } from "./modelCatalog";

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
    : model.reasoning_efforts.find((candidate) => candidate === requestedReasoningEffort);
  if (reasoningEffort === undefined) return null;
  return { model, reasoningEffort };
}

export type ChatPhase =
  | "new"
  | "opening"
  | "idle"
  | "active"
  | "waiting_for_user"
  | "stopping"
  | "recovering";

export type DraftValidity = "empty" | "valid" | "invalid";
export type ChatMainActionKind = "send" | "stage" | "stop" | "answer" | "continue";
export type ChatMainAction = Readonly<{
  enabled: boolean;
  kind: ChatMainActionKind;
  label: string;
}>;

export function deriveChatPhase(options: Readonly<{
  currentTurn: ChatTurn | null;
  localCommand: "none" | "stopping" | "recovering";
  opening: boolean;
  sessionExists: boolean;
}>): ChatPhase {
  if (options.localCommand === "recovering") return "recovering";
  if (options.localCommand === "stopping") return "stopping";
  if (options.opening) return "opening";
  if (!options.sessionExists) return "new";
  switch (options.currentTurn?.status) {
    case "running": return "active";
    case "waiting_for_user": return "waiting_for_user";
    case "stopping": return "stopping";
    default: return "idle";
  }
}

export function deriveMainAction(options: Readonly<{
  canContinue: boolean;
  draft: DraftValidity;
  phase: ChatPhase;
  settingsValid: boolean;
}>): ChatMainAction {
  const { canContinue, draft, phase, settingsValid } = options;
  if (phase === "active") {
    return {
      enabled: draft === "empty" || draft === "valid",
      kind: draft === "empty" ? "stop" : "stage",
      label: draft === "empty" ? "Stop" : "Stage",
    };
  }
  if (phase === "waiting_for_user") {
    return { enabled: draft !== "invalid", kind: draft === "empty" ? "stop" : "answer", label: draft === "empty" ? "Stop" : "Send answer" };
  }
  if (phase === "stopping") return { enabled: false, kind: "stop", label: "Stopping" };
  if (phase === "opening" || phase === "recovering") {
    return { enabled: false, kind: "send", label: phase === "opening" ? "Opening" : "Recovering" };
  }
  if (draft === "empty" && canContinue) {
    return { enabled: settingsValid, kind: "continue", label: "Continue" };
  }
  return {
    enabled: draft === "valid" && settingsValid,
    kind: "send",
    label: "Send",
  };
}

export function shouldSubmitFromEnter(options: Readonly<{
  action: ChatMainAction;
  composing: boolean;
  key: string;
  shiftKey: boolean;
}>): boolean {
  return options.key === "Enter"
    && !options.shiftKey
    && !options.composing
    && options.action.enabled
    && ["send", "stage", "answer"].includes(options.action.kind);
}
