import { describe, expect, it } from "vitest";

import {
  deriveChatPhase,
  deriveMainAction,
  resolveModelSelection,
  shouldSubmitFromEnter,
} from "./chatState";
import type { ChatTurn } from "./chatProtocol";
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

describe("Chat model selection", () => {
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

describe("Chat Turn state machine", () => {
  it.each([
    ["new", "empty", false, "send", false],
    ["new", "valid", false, "send", true],
    ["idle", "valid", false, "send", true],
    ["active", "valid", false, "stage", true],
    ["active", "empty", false, "stop", true],
    ["active", "invalid", false, "stage", false],
    ["waiting_for_user", "valid", false, "answer", true],
    ["waiting_for_user", "empty", false, "stop", true],
    ["stopping", "empty", false, "stop", false],
    ["opening", "valid", false, "send", false],
    ["recovering", "valid", false, "send", false],
    ["idle", "empty", true, "continue", true],
  ] as const)("maps %s + %s to %s", (phase, draft, canContinue, kind, enabled) => {
    expect(deriveMainAction({ canContinue, draft, phase, settingsValid: true }))
      .toMatchObject({ enabled, kind });
  });

  it("disables new-Turn operations when model settings are invalid without disabling Stop", () => {
    expect(deriveMainAction({ canContinue: false, draft: "valid", phase: "idle", settingsValid: false }).enabled).toBe(false);
    expect(deriveMainAction({ canContinue: true, draft: "empty", phase: "idle", settingsValid: false }).enabled).toBe(false);
    expect(deriveMainAction({ canContinue: false, draft: "empty", phase: "active", settingsValid: false }).enabled).toBe(true);
  });

  it("derives public UI phases only from the current Turn and local command", () => {
    expect(deriveChatPhase({ currentTurn: null, localCommand: "none", opening: false, sessionExists: false })).toBe("new");
    expect(deriveChatPhase({ currentTurn: turn("running"), localCommand: "none", opening: false, sessionExists: true })).toBe("active");
    expect(deriveChatPhase({ currentTurn: turn("waiting_for_user"), localCommand: "none", opening: false, sessionExists: true })).toBe("waiting_for_user");
    expect(deriveChatPhase({ currentTurn: turn("stopping"), localCommand: "none", opening: false, sessionExists: true })).toBe("stopping");
    expect(deriveChatPhase({ currentTurn: null, localCommand: "recovering", opening: false, sessionExists: true })).toBe("recovering");
  });

  it("allows Enter only for textual Send, Stage, and Answer actions", () => {
    const allowed = ["send", "stage", "answer"] as const;
    for (const kind of allowed) {
      expect(shouldSubmitFromEnter({ action: { enabled: true, kind, label: kind }, composing: false, key: "Enter", shiftKey: false })).toBe(true);
    }
    for (const kind of ["stop", "continue"] as const) {
      expect(shouldSubmitFromEnter({ action: { enabled: true, kind, label: kind }, composing: false, key: "Enter", shiftKey: false })).toBe(false);
    }
    expect(shouldSubmitFromEnter({ action: { enabled: true, kind: "send", label: "Send" }, composing: true, key: "Enter", shiftKey: false })).toBe(false);
    expect(shouldSubmitFromEnter({ action: { enabled: true, kind: "send", label: "Send" }, composing: false, key: "Enter", shiftKey: true })).toBe(false);
  });
});

function turn(status: ChatTurn["status"]): ChatTurn {
  return {
    id: "00000000-0000-4000-8000-000000000001",
    kind: "prompt",
    model_key: "primary",
    question: null,
    reasoning_effort: "medium",
    started_at: "2026-09-02T00:00:00.000000Z",
    status,
    terminal_error_code: null,
  };
}
