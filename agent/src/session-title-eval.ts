import { z } from "zod";

import { parseGeneratedSessionTitle } from "./session-title.js";

const caseSchema = z.object({
  forbidden_terms: z.array(z.string().min(1)).max(20),
  id: z.string().regex(/^[a-z0-9][a-z0-9-]{0,63}$/),
  message: z.string().min(1).max(16 * 1024),
  required_terms: z.array(z.string().min(1)).min(1).max(20),
}).strict();
const corpusSchema = z.object({
  cases: z.array(caseSchema).min(1).max(100),
  version: z.string().regex(/^[a-z0-9][a-z0-9-]{0,63}$/),
}).strict();

export type SessionTitleEvalCase = z.infer<typeof caseSchema>;
export type SessionTitleEvalCorpus = z.infer<typeof corpusSchema>;
export type SessionTitleEvalObservation = Readonly<{
  caseId: string;
  durationMs: number;
  estimatedCostUsd: number;
  inputTokens: number;
  outputTokens: number;
  succeeded: boolean;
  titleCharacters: number;
}>;

export function parseSessionTitleEvalCorpus(value: unknown): SessionTitleEvalCorpus {
  const parsed = corpusSchema.safeParse(value);
  if (!parsed.success || new Set(parsed.data.cases.map((item) => item.id)).size !== parsed.data.cases.length) {
    throw new Error("SESSION_TITLE_EVAL_CORPUS_INVALID");
  }
  return parsed.data;
}

export function sessionTitleMeetsEvalOutcome(
  value: unknown,
  testCase: SessionTitleEvalCase,
): boolean {
  let title: string;
  try {
    title = parseGeneratedSessionTitle(value);
  } catch {
    return false;
  }
  const normalized = title.normalize("NFKC").toLocaleLowerCase("en-US");
  return testCase.required_terms.every((term) => (
    normalized.includes(term.normalize("NFKC").toLocaleLowerCase("en-US"))
  )) && testCase.forbidden_terms.every((term) => (
    !normalized.includes(term.normalize("NFKC").toLocaleLowerCase("en-US"))
  ));
}

export function summarizeSessionTitleEval(
  observations: readonly SessionTitleEvalObservation[],
): Readonly<{
  duration_p50_ms: number;
  duration_p95_ms: number;
  duration_stddev_ms: number;
  estimated_cost_usd: number;
  input_tokens: number;
  invocation_count: number;
  output_tokens: number;
  success_rate: number;
  success_variance: number;
  title_length_stddev: number;
}> {
  if (observations.length === 0) throw new Error("SESSION_TITLE_EVAL_EMPTY");
  for (const observation of observations) {
    if (
      !Number.isFinite(observation.durationMs)
      || observation.durationMs < 0
      || !Number.isFinite(observation.estimatedCostUsd)
      || observation.estimatedCostUsd < 0
      || !Number.isSafeInteger(observation.inputTokens)
      || observation.inputTokens < 0
      || !Number.isSafeInteger(observation.outputTokens)
      || observation.outputTokens < 0
      || !Number.isSafeInteger(observation.titleCharacters)
      || observation.titleCharacters < 0
    ) {
      throw new Error("SESSION_TITLE_EVAL_OBSERVATION_INVALID");
    }
  }
  const durations = observations.map((item) => item.durationMs).sort((left, right) => left - right);
  const successes = observations.filter((item) => item.succeeded).length;
  const successRate = successes / observations.length;
  return {
    duration_p50_ms: percentile(durations, 0.5),
    duration_p95_ms: percentile(durations, 0.95),
    duration_stddev_ms: standardDeviation(durations),
    estimated_cost_usd: sum(observations.map((item) => item.estimatedCostUsd)),
    input_tokens: sum(observations.map((item) => item.inputTokens)),
    invocation_count: observations.length,
    output_tokens: sum(observations.map((item) => item.outputTokens)),
    success_rate: successRate,
    success_variance: successRate * (1 - successRate),
    title_length_stddev: standardDeviation(
      observations.map((item) => item.titleCharacters),
    ),
  };
}

function percentile(sorted: readonly number[], proportion: number): number {
  const index = Math.max(0, Math.ceil(sorted.length * proportion) - 1);
  return sorted[index] ?? 0;
}

function standardDeviation(values: readonly number[]): number {
  const mean = sum(values) / values.length;
  return Math.sqrt(sum(values.map((value) => (value - mean) ** 2)) / values.length);
}

function sum(values: readonly number[]): number {
  return values.reduce((total, value) => total + value, 0);
}
