import { readFileSync } from "node:fs";
import type { LanguageModelV3CallOptions } from "@ai-sdk/provider";
import { SCRIPTED_FACTOR_IDEA_PROMPT, scriptedResearchDecision } from "./scripted-research-model.js";
import { latestUserText, type ScriptedResearchDecision } from "./scripted-research-support.js";

// Private deterministic-provider fixtures, never a real-model instruction or
// browser import. The same catalog drives raw-log scans and canary assertions.
export const PRIVACY_CANARIES: Readonly<Record<string, string>> = Object.freeze(JSON.parse(
  readFileSync(new URL("../../tests/fixtures/agent-privacy-canaries.json", import.meta.url), "utf8"),
));

export function scriptedPrivacyDecision(options: LanguageModelV3CallOptions): ScriptedResearchDecision | null {
  const latest = latestUserText(options);
  if (latest?.text !== PRIVACY_CANARIES.user) return null;
  if (!options.prompt.some((message) => message.role === "system" && message.content.includes(PRIVACY_CANARIES.system!))) {
    throw new Error("SCRIPTED_PRIVACY_SYSTEM_NOT_INJECTED");
  }
  const decision = scriptedResearchDecision({
    ...options,
    prompt: options.prompt.map((message, index) => index === latest.index
      ? { role: "user", content: [{ type: "text", text: SCRIPTED_FACTOR_IDEA_PROMPT }] }
      : message),
  });
  if (decision === null) throw new Error("SCRIPTED_PRIVACY_FIXTURE_INVALID");
  if (decision.kind === "text") return { kind: "text", text: PRIVACY_CANARIES.assistant! };
  const input = { ...decision.input };
  if (decision.name === "diagnose_alpha_formula") input.source = PRIVACY_CANARIES.formula;
  if (decision.name === "submit_research_run") {
    input.formula = PRIVACY_CANARIES.formula;
    input.hypothesis = PRIVACY_CANARIES.hypothesis;
    input.name = PRIVACY_CANARIES.mcp_argument;
  }
  if (decision.name === "render_a2ui" && Array.isArray(input.components)) {
    input.components = input.components.map((component) => component.component === "AlphaProposal" ? {
      ...component, formula: PRIVACY_CANARIES.formula, hypothesis: PRIVACY_CANARIES.hypothesis, explanation: PRIVACY_CANARIES.a2ui,
    } : component.component === "Formula" ? { ...component, expression: PRIVACY_CANARIES.formula } : component);
  }
  return { ...decision, input };
}
