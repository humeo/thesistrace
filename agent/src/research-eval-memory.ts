import { readFileSync } from "node:fs";
import { convertMessages, type MastraDBMessage } from "@mastra/core/agent";
import { Pool } from "pg";
import { z } from "zod";

import { ResearchEvalError } from "./research-eval.js";

const date = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const runId = z.string().regex(/^run_[a-f0-9]{20}$/);
const runSchema = z.object({
  id: runId,
  formula: z.string().min(1).max(4096), start_date: date, end_date: date,
  universe: z.string().min(1).max(64), neutralization: z.string().min(1).max(64),
  research_kind: z.literal("factor_evaluation"),
}).strict();
const expectationSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("formula"), original_formula: z.string().min(1).max(4096), run: runSchema }).strict(),
  z.object({ kind: z.literal("admission"), requested_start: date, run: runSchema }).strict(),
  z.object({ kind: z.literal("batch-results"), run_ids: z.tuple([runId, runId])
    .refine(([first, second]) => first !== second) }).strict(),
]);
const requestSchema = z.object({
  thread_id: z.string().uuid(), researcher_id: z.string().uuid(), expectation: expectationSchema.nullable(),
}).strict();
export type ResearchEvalMemoryExpectation = z.infer<typeof expectationSchema>;
export const researchEvalMemoryFactsSchema = z.object({
  formula_corrected: z.boolean(), admission_corrected: z.boolean(), unresolved_admission_rejection: z.boolean(),
  batch_results_inspected: z.boolean(),
}).strict();
export type ResearchEvalMemoryFacts = z.infer<typeof researchEvalMemoryFactsSchema>;
type ModelStep = Readonly<{ message: number; step: number }>;

/** Private Memory is inspected in place; only closed booleans leave the oracle. */
export function researchEvalMemoryFacts(
  messages: readonly MastraDBMessage[], expectation: ResearchEvalMemoryExpectation | null,
): ResearchEvalMemoryFacts {
  try {
    const expected = expectationSchema.nullable().parse(expectation);
    let invalidDiagnosis: ModelStep | undefined, validCorrection: ModelStep | undefined;
    let rejectedRequest: { id: string; observed: ModelStep } | undefined;
    let acceptedTarget = false;
    const starts = new Map<string, ModelStep>();
    const rejectedTools = new Map<string, ModelStep>();
    const inspectedResults = new Set<string>();
    const facts = { formula_corrected: false, admission_corrected: false, unresolved_admission_rejection: false, batch_results_inspected: false };
    // Keep native pending calls: the display format drops them and can make an
    // already-started parallel call look like a decision made after an error.
    for (const [messageIndex, message] of convertMessages([...messages]).to("Mastra.V2").entries()) {
      if (message.role !== "assistant") continue;
      let markerStep = -1, unmarkedStep = -1;
      for (const part of message.content.parts) {
        if (part.type === "step-start") {
          // Native Memory may omit the first marker. A later marker still
          // starts a new step, not the step containing the initial Tool result.
          markerStep = markerStep < 0 ? unmarkedStep + 1 : markerStep + 1;
          continue;
        }
        if (part.type !== "tool-invocation") continue;
        const call = part.toolInvocation;
        const step = call.step ?? Math.max(0, markerStep);
        if (!Number.isSafeInteger(step) || step < 0) throw new ResearchEvalError("REPORT_INVALID");
        if (markerStep < 0) unmarkedStep = Math.max(unmarkedStep, step);
        const observed = { message: messageIndex, step: markerStep < 0 ? step : markerStep };
        if (!starts.has(call.toolCallId)) starts.set(call.toolCallId, { ...observed, step: Math.min(observed.step, step) });
        const started = starts.get(call.toolCallId)!;
        if (call.state !== "result" || !isRecord(call.args) || !isRecord(call.result)) continue;
        if (("isError" in call && call.isError === true) || call.result.isError === true) continue;
        const name = call.toolName.replace(/^thesistrace_/, "");
        const input = call.args, output = call.result;
        if (name === "submit_research_run" || name === "submit_research_batch") {
          if (output.outcome === "rejected") rejectedTools.set(name, observed);
          if (output.outcome === "accepted" && startsAfter(started, rejectedTools.get(name))) rejectedTools.delete(name);
        }
        if (expected?.kind === "batch-results" && name === "get_research_run_result"
          && typeof input.run_id === "string" && expected.run_ids.includes(input.run_id)
          && input.section === "factor" && output.section === "factor" && output.run_id === input.run_id
          && output.research_kind === "factor_evaluation" && isRecord(output.factor)) {
          inspectedResults.add(input.run_id);
        }
        if (expected === null || expected.kind === "batch-results") continue;
        if (expected.kind === "formula" && name === "diagnose_alpha_formula") {
          if (input.source === expected.original_formula && output.valid === false
            && Array.isArray(output.diagnostics) && output.diagnostics.length > 0) invalidDiagnosis ??= observed;
          if (startsAfter(started, invalidDiagnosis) && input.source === expected.run.formula && output.valid === true) validCorrection ??= observed;
        }
        if (name !== "submit_research_run") continue;
        const sameResearch = ["formula", "end_date", "universe", "neutralization", "research_kind"]
          .every((key) => input[key] === expected.run[key as keyof typeof expected.run]);
        if (expected.kind === "admission" && sameResearch && input.start_date === expected.requested_start
          && output.outcome === "rejected" && typeof input.request_id === "string"
          && Array.isArray(output.issues) && output.issues.some((issue) => isRecord(issue)
            && issue.code === "INSUFFICIENT_CALCULATION_WARMUP" && issue.field === "start_date")) {
          rejectedRequest ??= { id: input.request_id, observed };
        }
        if (!acceptedTarget && output.outcome === "accepted" && output.run_id === expected.run.id) {
          acceptedTarget = true;
          const matches = sameResearch && input.start_date === expected.run.start_date;
          facts.formula_corrected = expected.kind === "formula" && matches && startsAfter(started, validCorrection);
          facts.admission_corrected = expected.kind === "admission" && matches && rejectedRequest !== undefined
            && startsAfter(started, rejectedRequest.observed)
            && typeof input.request_id === "string" && input.request_id !== rejectedRequest.id
            && expected.run.start_date > expected.requested_start;
          // An already accepted Run cannot later be presented as a correction.
        }
      }
    }
    facts.unresolved_admission_rejection = rejectedTools.size > 0;
    facts.batch_results_inspected = expected?.kind === "batch-results" && expected.run_ids.every((id) => inspectedResults.has(id));
    return facts;
  } catch {
    throw new ResearchEvalError("REPORT_INVALID");
  }
}

export async function readResearchEvalMemoryFacts(pool: Pool, value: unknown): Promise<ResearchEvalMemoryFacts> {
  const parsed = requestSchema.safeParse(value);
  if (!parsed.success) throw new ResearchEvalError("CONFIG_INVALID");
  const input = parsed.data;
  try {
    const result = await pool.query<{
      id: string; content: string; role: MastraDBMessage["role"]; created_at: Date; resource_id: string | null;
    }>(`
      SELECT message.id, message.content, message.role,
        message."createdAtZ" AS created_at, message."resourceId" AS resource_id
      FROM agent.mastra_messages AS message
      JOIN agent.chat_session AS session ON message.thread_id = session.id::text
      WHERE session.id = $1::uuid AND session.researcher_id = $2::uuid
        AND (message."resourceId" = $2::uuid::text OR message."resourceId" IS NULL)
      ORDER BY message."createdAtZ", message.id LIMIT 129
    `, [input.thread_id, input.researcher_id]);
    if (result.rows.length === 0 || result.rows.length > 128) throw new ResearchEvalError("REPORT_INVALID");
    const messages = result.rows.map((row): MastraDBMessage => ({
      id: row.id, role: row.role, content: JSON.parse(row.content), createdAt: row.created_at,
      threadId: input.thread_id, resourceId: row.resource_id ?? undefined,
    }));
    return researchEvalMemoryFacts(messages, input.expectation);
  } catch {
    throw new ResearchEvalError("REPORT_INVALID");
  }
}

/** Explicit isolated Operator CLI, never imported or started by Agent Host. */
export async function runResearchEvalMemoryOracle(): Promise<void> {
  let pool: Pool | undefined;
  try {
    if (process.env.THESISTRACE_AGENT_EVAL_ORACLE !== "isolated"
      || !process.env.THESISTRACE_AGENT_DATABASE_URL) throw new ResearchEvalError("CONFIG_INVALID");
    const encoded = readFileSync(0, "utf8");
    if (Buffer.byteLength(encoded) > 16 * 1024) throw new ResearchEvalError("CONFIG_INVALID");
    const input: unknown = JSON.parse(encoded);
    pool = new Pool({ connectionString: process.env.THESISTRACE_AGENT_DATABASE_URL, max: 1, query_timeout: 5000 });
    process.stdout.write(`${JSON.stringify(await readResearchEvalMemoryFacts(pool, input))}\n`);
  } catch {
    process.stderr.write("RESEARCH_EVAL_MEMORY_ORACLE_FAILED\n");
    process.exitCode = 2;
  } finally {
    await pool?.end().catch(() => { process.stderr.write("RESEARCH_EVAL_MEMORY_ORACLE_FAILED\n"); process.exitCode = 2; });
  }
}

function startsAfter(started: ModelStep, observed: ModelStep | undefined): boolean {
  return observed !== undefined && (started.message > observed.message
    || (started.message === observed.message && started.step > observed.step));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
