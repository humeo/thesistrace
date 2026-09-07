import type { AgentFailureCode } from "../../contracts/agent-failure.mjs";
import type { ModelRequestBudget } from "./model-context.js";

export type ModelRecoveryCause = "OUTPUT_LIMIT" | "CONTEXT_TOO_LARGE";

/** Eligibility alone never authorizes a retry; a durable claim and improvement are also required. */
export function mayRecoverModelStep(enabled: boolean, cause: ModelRecoveryCause, budget: ModelRequestBudget): boolean {
  return enabled && (cause === "CONTEXT_TOO_LARGE" || budget.outputTokens < budget.desiredOutputTokens);
}

/** Validate the complete replacement request before publishing its checkpoint. */
export function recoveryImprovesBudget(cause: ModelRecoveryCause, before: ModelRequestBudget, after: ModelRequestBudget): boolean {
  return after.contextWindow === before.contextWindow
    && after.desiredOutputTokens === before.desiredOutputTokens
    && after.inputTokens < before.inputTokens
    && Number.isSafeInteger(after.outputTokens) && after.outputTokens > 0
    && (cause === "CONTEXT_TOO_LARGE" || after.outputTokens > before.outputTokens);
}

export type ModelStepRecovery = Readonly<{
  runId: string;
  originalMessageId: string;
  replacementMessageId: string | null;
  attempts: 0 | 1;
  /** True until a valid completion is persisted, and on any later invalidation. */
  invalidReplacement: boolean;
  cause: ModelRecoveryCause;
  status: "recovering" | "succeeded" | "failed";
  beforeBudget: ModelRequestBudget;
  afterBudget: ModelRequestBudget | null;
  errorCode: AgentFailureCode | null;
}>;

/** Failure of a Run does not invalidate earlier successful tools in its replacement step. */
export function invalidRecoveryMessageIds(recoveries: readonly ModelStepRecovery[]): string[] {
  return recoveries.flatMap((recovery) => [recovery.originalMessageId,
    ...(recovery.invalidReplacement && recovery.replacementMessageId ? [recovery.replacementMessageId] : [])]);
}
