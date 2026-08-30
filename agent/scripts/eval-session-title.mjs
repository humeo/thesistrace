import { readFile } from "node:fs/promises";

import { readModelRegistry } from "../dist/model-registry.js";
import { RegisteredModelRuntime } from "../dist/model-runtime.js";
import {
  parseSessionTitleEvalCorpus,
  sessionTitleMeetsEvalOutcome,
  summarizeSessionTitleEval,
} from "../dist/session-title-eval.js";
import { generateSessionTitle } from "../dist/session-title.js";
import { RunUsageCapture } from "../dist/usage-capture.js";

const registry = readModelRegistry(required("THESISTRACE_AGENT_MODEL_REGISTRY"), process.env);
const modelKey = required("THESISTRACE_AGENT_TITLE_EVAL_MODEL_KEY");
const reasoningEffort = required("THESISTRACE_AGENT_TITLE_EVAL_REASONING_EFFORT");
const repetitions = boundedInteger(
  process.env.THESISTRACE_AGENT_TITLE_EVAL_REPETITIONS ?? "3",
  2,
  20,
);
const inputUsdPerMillion = nonnegativeNumber(required(
  "THESISTRACE_AGENT_TITLE_EVAL_INPUT_USD_PER_MILLION",
));
const outputUsdPerMillion = nonnegativeNumber(required(
  "THESISTRACE_AGENT_TITLE_EVAL_OUTPUT_USD_PER_MILLION",
));
const corpus = parseSessionTitleEvalCorpus(JSON.parse(await readFile(
  new URL("../evals/session-title-corpus.json", import.meta.url),
  "utf8",
)));
const modelRuntime = new RegisteredModelRuntime(registry);
const observations = [];

for (let repetition = 0; repetition < repetitions; repetition += 1) {
  for (const testCase of corpus.cases) {
    const usageCapture = new RunUsageCapture();
    const selection = modelRuntime.resolve(modelKey, reasoningEffort, usageCapture);
    const startedAt = performance.now();
    let title = "";
    let generated = false;
    try {
      title = await generateSessionTitle({
        languageModel: selection.languageModel,
        message: testCase.message,
        providerOptions: selection.providerOptions,
      });
      generated = true;
    } catch {
      // Reports retain only fixed case identity and aggregate outcomes.
    }
    const durationMs = performance.now() - startedAt;
    const usage = usageCapture.value();
    const inputTokens = usage?.inputTokens.total;
    const outputTokens = usage?.outputTokens.total;
    const usageReported = inputTokens !== null
      && inputTokens !== undefined
      && outputTokens !== null
      && outputTokens !== undefined;
    observations.push({
      caseId: testCase.id,
      durationMs,
      estimatedCostUsd: usageReported
        ? (inputTokens * inputUsdPerMillion + outputTokens * outputUsdPerMillion) / 1_000_000
        : 0,
      inputTokens: usageReported ? inputTokens : 0,
      outputTokens: usageReported ? outputTokens : 0,
      succeeded: generated && usageReported && sessionTitleMeetsEvalOutcome(title, testCase),
      titleCharacters: generated ? [...title].length : 0,
    });
  }
}

const selected = registry.models.find((model) => model.key === modelKey && model.enabled);
if (selected === undefined) throw new Error("SESSION_TITLE_EVAL_MODEL_NOT_ENABLED");
process.stdout.write(`${JSON.stringify({
  case_summaries: corpus.cases.map((testCase) => ({
    case_id: testCase.id,
    ...summarizeSessionTitleEval(observations.filter((item) => item.caseId === testCase.id)),
  })),
  corpus_version: corpus.version,
  generated_at: new Date().toISOString(),
  model_key: selected.key,
  provider_adapter: selected.providerAdapter,
  provider_model_id: selected.providerModelId,
  reasoning_effort: reasoningEffort,
  repetitions,
  summary: summarizeSessionTitleEval(observations),
}, null, 2)}\n`);

function required(name) {
  const value = process.env[name];
  if (value === undefined || value.length === 0) throw new Error("SESSION_TITLE_EVAL_CONFIG_INVALID");
  return value;
}

function boundedInteger(value, minimum, maximum) {
  if (!/^[0-9]+$/.test(value)) throw new Error("SESSION_TITLE_EVAL_CONFIG_INVALID");
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error("SESSION_TITLE_EVAL_CONFIG_INVALID");
  }
  return parsed;
}

function nonnegativeNumber(value) {
  if (!/^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(value)) {
    throw new Error("SESSION_TITLE_EVAL_CONFIG_INVALID");
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) throw new Error("SESSION_TITLE_EVAL_CONFIG_INVALID");
  return parsed;
}
